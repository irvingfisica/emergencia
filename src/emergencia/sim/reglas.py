"""El lenguaje de reglas (DSL).

Una regla es una expresión de texto, por ejemplo

    pob500**a * (1 + mismo200)**b * exp(c * avenida)

Se lee con `ast` y se evalúa con numpy, sin `eval`: solo se aceptan los nombres
de PERCEPCION (información local de un lote), los parámetros declarados y los
operadores y funciones de OPERADORES. Así se cumple la restricción de localidad:
ninguna regla puede usar información global de la ciudad.

Percepción (por lote y para el giro que decide):

  pob200, pob500       población a <= 200 / 500 m sobre la red (miles de habitantes)
  pob1000, pob2000     población a <= 1 / 2 km (malla gruesa, miles de habitantes)
  mismoR               comercios del mismo giro a <= R m
  totalR               comercios de cualquier giro a <= R m
  otrosR               comercios de otros giros a <= R m (totalR − mismoR)
  <giro>R              comercios de un giro concreto (p. ej. ropa200)
                       con R en RADIOS: 100 y 200 (red, lote a lote) o 1000 y 2000
                       (malla gruesa de celdas, ver lotes.py)
  via                  jerarquía de la calle (0 local … 3 primaria, 4 peatonal)
  avenida, peatonal    indicadores de tipo de calle
  edad                 pasos desde que llegó (solo en permanencia)

Complejidad = nodos del árbol + parámetros libres.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

import numpy as np

RADIOS = (100, 200, 1000, 2000)
CONTEOS = ("mismo", "total", "otros")
BASICOS = ({"pob200", "pob500", "pob1000", "pob2000", "via", "avenida", "peatonal", "edad"}
           | {f"{c}{r}" for c in CONTEOS for r in RADIOS})

OPERADORES = {
    "exp": lambda x: np.exp(np.clip(x, -50, 50)),
    "log1p": lambda x: np.log1p(np.maximum(x, 0)),
    "sat": lambda x, h: x / (x + np.abs(h) + 1e-9),          # saturación
    "umbral": lambda x, h: 1 / (1 + np.exp(-np.clip(x - h, -50, 50))),
    "min": np.minimum,
    "max": np.maximum,
}

_BIN = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply,
        ast.Div: lambda a, b: a / (b + 1e-9 * (b == 0)),
        ast.Pow: lambda a, b: np.power(np.maximum(a, 1e-9), b)}


class ReglaInvalida(ValueError):
    pass


@dataclass
class Regla:
    """Expresión del DSL con sus parámetros (nombre -> (mín, máx))."""
    texto: str
    params: dict[str, tuple[float, float]] = field(default_factory=dict)
    giros: tuple[str, ...] = ()

    def __post_init__(self):
        try:
            self.arbol = ast.parse(self.texto, mode="eval").body
        except SyntaxError as e:
            raise ReglaInvalida(f"no se puede leer: {self.texto!r}") from e
        self.nodos = 0
        self._revisar(self.arbol)

    @property
    def permitidos(self) -> set[str]:
        return BASICOS | {f"{g}{r}" for g in self.giros for r in RADIOS} | set(self.params)

    def _revisar(self, n):
        self.nodos += 1
        if isinstance(n, ast.Name):
            if n.id not in self.permitidos:
                raise ReglaInvalida(f"nombre no permitido: {n.id}")
        elif isinstance(n, ast.Constant):
            if not isinstance(n.value, (int, float)):
                raise ReglaInvalida("solo constantes numéricas")
        elif isinstance(n, ast.BinOp):
            if type(n.op) not in _BIN:
                raise ReglaInvalida(f"operador no permitido: {type(n.op).__name__}")
            self._revisar(n.left); self._revisar(n.right)
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            self._revisar(n.operand)
        elif isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.func.id not in OPERADORES or n.keywords:
                raise ReglaInvalida("función no permitida")
            for a in n.args:
                self._revisar(a)
        else:
            raise ReglaInvalida(f"expresión no permitida: {type(n).__name__}")

    @property
    def complejidad(self) -> int:
        return self.nodos + len(self.params)

    def usa(self) -> set[str]:
        return {n.id for n in ast.walk(self.arbol) if isinstance(n, ast.Name)} - set(self.params)

    def evaluar(self, entorno: dict, valores: dict[str, float]) -> np.ndarray:
        def ev(n):
            if isinstance(n, ast.Name):
                return valores[n.id] if n.id in self.params else entorno[n.id]
            if isinstance(n, ast.Constant):
                return float(n.value)
            if isinstance(n, ast.BinOp):
                return _BIN[type(n.op)](ev(n.left), ev(n.right))
            if isinstance(n, ast.UnaryOp):
                v = ev(n.operand)
                return -v if isinstance(n.op, ast.USub) else v
            return OPERADORES[n.func.id](*[ev(a) for a in n.args])
        with np.errstate(all="ignore"):
            v = ev(self.arbol)
        v = np.nan_to_num(np.asarray(v, dtype=float), nan=0.0, posinf=1e300, neginf=0.0)
        return v


@dataclass
class Modelo:
    """Reglas de un giro: localización (atractivo de un lote libre) y permanencia
    (riesgo relativo de cerrar). Si permanencia es None, todos cierran con la misma
    probabilidad."""
    localizacion: Regla
    permanencia: Regla | None = None

    @property
    def params(self) -> dict[str, tuple[float, float]]:
        p = dict(self.localizacion.params)
        if self.permanencia:
            p.update(self.permanencia.params)
        return p

    @property
    def complejidad(self) -> int:
        return self.localizacion.complejidad + (self.permanencia.complejidad if self.permanencia else 0)
