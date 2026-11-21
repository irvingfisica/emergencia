"""Simulador de comercios sobre los lotes de la red (modo génesis).

El número de comercios de cada giro es una entrada exógena y se mantiene fijo.
En cada paso:

  1. Cierre: de cada giro sale una fracción `rotacion` de sus comercios, elegidos con
     probabilidad proporcional a su regla de permanencia (uniforme si no tiene).
  2. Llegada: entra el mismo número de comercios de ese giro; cada uno elige un lote
     con probabilidad proporcional al atractivo que da su regla de localización,
     entre los lotes que tienen lugar (menos de CAPACIDAD comercios).

Los giros se procesan en orden aleatorio y cada uno ve las llegadas de los anteriores.
Todo lo que percibe un comercio es local (ver reglas.py).
"""
from __future__ import annotations

import numpy as np

from .lotes import CAPACIDAD, Lotes
from .reglas import Modelo

RADIOS = (100.0, 200.0)


class _Entorno:
    """Percepción perezosa: calcula solo las variables que usa la regla."""

    def __init__(self, sim: "Simulador", k: int, donde: np.ndarray | None = None, propio: bool = False,
                 edad: np.ndarray | None = None):
        self.s, self.k, self.donde, self.propio, self.edad = sim, k, donde, propio, edad
        self.cache = {}

    def _sel(self, v):
        return v if self.donde is None else v[self.donde]

    def __getitem__(self, nombre):
        if nombre in self.cache:
            return self.cache[nombre]
        s = self.s
        if nombre == "edad":
            v = self.edad
        elif nombre in ("pob200", "pob500"):
            v = self._sel(s.pob[nombre])
        elif nombre == "via":
            v = self._sel(s.via).astype(float)
        elif nombre == "avenida":
            v = self._sel(((s.via >= 1) & (s.via <= 3)).astype(float))
        elif nombre == "peatonal":
            v = self._sel((s.via == 4).astype(float))
        else:
            base, r = nombre[:-3], float(nombre[-3:])
            C = s.C[r]
            if base == "mismo":
                v = self._sel(C[:, self.k]) - (1 if self.propio else 0)
            elif base == "total":
                v = self._sel(C.sum(1)) - (1 if self.propio else 0)
            else:
                v = self._sel(C[:, s.indice[base]])
            v = v.astype(float)
        self.cache[nombre] = v
        return v


class Simulador:
    def __init__(self, lotes: Lotes, giros: list[str], n: dict[str, int], modelos: dict[str, Modelo],
                 valores: dict[str, dict[str, float]], rotacion: float = 0.05, capacidad: int = CAPACIDAD,
                 semilla: int | None = None):
        self.L = lotes
        self.giros = list(giros)
        self.indice = {g: i for i, g in enumerate(self.giros)}
        self.K = len(giros)
        self.n = n
        self.modelos = modelos
        self.valores = valores
        self.rotacion = rotacion
        self.capacidad = capacidad
        self.rng = np.random.default_rng(semilla)
        self.W = {r: lotes.W(r) for r in RADIOS}
        self.pob = {"pob200": lotes.col("pob200") / 1000, "pob500": lotes.col("pob500") / 1000}
        self.via = lotes.col("via")
        self.t = 0

    # ------------------------------------------------------------ estado
    def iniciar(self, lote: np.ndarray | None = None, giro: np.ndarray | None = None):
        """Sin argumentos, reparte los comercios al azar sobre los lotes."""
        if lote is None:
            giro = np.repeat(np.arange(self.K), [self.n[g] for g in self.giros])
            lote = np.empty(len(giro), dtype=int)
            ocup = np.zeros(self.L.n, dtype=int)
            pend = np.arange(len(giro))
            while len(pend):
                cand = self.rng.integers(0, self.L.n, len(pend))
                ok = np.zeros(len(pend), bool)
                for j, c in enumerate(cand):
                    if ocup[c] < self.capacidad:
                        ocup[c] += 1
                        ok[j] = True
                lote[pend[ok]] = cand[ok]
                pend = pend[~ok]
        self.lote = np.asarray(lote, dtype=int).copy()
        self.giro = np.asarray(giro, dtype=int).copy()
        self.nacio = np.zeros(len(self.lote), dtype=int)
        self.O = np.zeros((self.L.n, self.K), dtype=np.float32)
        np.add.at(self.O, (self.lote, self.giro), 1)
        self.C = {r: np.asarray(W @ self.O, dtype=np.float32) for r, W in self.W.items()}
        self.t = 0

    def _cambio(self, lotes: np.ndarray, k: int, signo: float):
        v = np.bincount(lotes, minlength=self.L.n).astype(np.float32) * signo
        self.O[:, k] += v
        for r, W in self.W.items():
            self.C[r][:, k] += W @ v

    def _redondeo(self, x: float) -> int:
        return int(np.floor(x) + (self.rng.random() < x - np.floor(x)))

    # ------------------------------------------------------------ dinámica
    def paso(self):
        orden = self.rng.permutation(self.K)
        salen = {}
        vivos = np.ones(len(self.lote), bool)
        for k in orden:
            g = self.giros[k]
            idx = np.flatnonzero(self.giro == k)
            m = min(self._redondeo(self.rotacion * len(idx)), len(idx))
            if m == 0:
                salen[k] = 0
                continue
            perm = self.modelos[g].permanencia
            if perm is None:
                fuera = self.rng.choice(idx, m, replace=False)
            else:
                ent = _Entorno(self, k, donde=self.lote[idx], propio=True, edad=(self.t - self.nacio[idx]).astype(float))
                h = np.maximum(perm.evaluar(ent, self.valores[g]), 0)
                h = h if h.sum() > 0 and np.all(np.isfinite(h)) else np.ones(len(idx))
                fuera = self.rng.choice(idx, m, replace=False, p=h / h.sum())
            self._cambio(self.lote[fuera], k, -1)
            vivos[fuera] = False
            salen[k] = m
        self.lote, self.giro, self.nacio = self.lote[vivos], self.giro[vivos], self.nacio[vivos]
        nuevos_l, nuevos_g = [], []
        for k in orden:
            m = salen[k]
            if m == 0:
                continue
            g = self.giros[k]
            A = np.maximum(self.modelos[g].localizacion.evaluar(_Entorno(self, k), self.valores[g]), 0)
            if np.ndim(A) == 0:
                A = np.full(self.L.n, float(A))
            libres = self.O.sum(1) < self.capacidad
            A = np.where(libres & np.isfinite(A), A, 0)
            if A.sum() <= 0:
                A = libres.astype(float)
            elegidos = self._elegir(A, m)
            self._cambio(elegidos, k, +1)
            nuevos_l.append(elegidos)
            nuevos_g.append(np.full(m, k))
        if nuevos_l:
            nl = np.concatenate(nuevos_l)
            self.lote = np.concatenate([self.lote, nl])
            self.giro = np.concatenate([self.giro, np.concatenate(nuevos_g)])
            self.nacio = np.concatenate([self.nacio, np.full(len(nl), self.t)])
        self.t += 1

    def _elegir(self, A: np.ndarray, m: int) -> np.ndarray:
        """m lotes con probabilidad ∝ A, sin pasar la capacidad."""
        libre = self.capacidad - self.O.sum(1)
        out = []
        p = A / A.sum()
        while len(out) < m:
            cand = self.rng.choice(self.L.n, m - len(out), p=p)
            for c in cand:
                if libre[c] > 0:
                    libre[c] -= 1
                    out.append(c)
            p = np.where(libre > 0, p, 0)
            if p.sum() <= 0:
                break
            p = p / p.sum()
        return np.array(out, dtype=int)

    def correr(self, pasos: int, cada: int | None = None, al_registrar=None):
        for _ in range(pasos):
            self.paso()
            if cada and al_registrar and self.t % cada == 0:
                al_registrar(self)
        return self
