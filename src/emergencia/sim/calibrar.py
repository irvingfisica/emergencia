"""Calibración interna: dados la estructura de las reglas, busca los parámetros.

Una *especificación* dice, para cada giro, el texto de sus reglas y el rango de
cada parámetro:

    {"ropa": {"localizacion": "(1+mismo200)**b * exp(c*avenida)",
              "params": {"b": [0, 3], "c": [0, 3]}},
     "abarrotes": {"localizacion": "pob500**a", "params": {"a": [0, 3]}}}

(con "permanencia" opcional). Los parámetros son independientes por giro.
La calibración usa CMA-ES en el cubo [0, 1] y evalúa cada punto con varias
réplicas en paralelo.
"""
from __future__ import annotations

import ast
import multiprocessing as mp
import os
import time
from dataclasses import dataclass, field

import cma
import numpy as np

from .firmas import GRUPOS, distancia, firma
from .lotes import Lotes
from .reglas import Modelo, Regla
from .simulador import Simulador

PASOS = 150
ROTACION = 0.05


@dataclass
class Escena:
    """Lo exógeno: ciudad, giros y número de comercios de cada uno."""
    ciudad: str
    n: dict[str, int]
    pasos: int = PASOS
    rotacion: float = ROTACION

    @property
    def giros(self) -> list[str]:
        return list(self.n)


def modelos(espec: dict, giros: list[str]) -> dict[str, Modelo]:
    out = {}
    for g in giros:
        e = espec[g]
        p = {k: tuple(v) for k, v in e.get("params", {}).items()}

        def regla(texto):
            usados = {n.id for n in ast.walk(ast.parse(texto, mode="eval")) if isinstance(n, ast.Name)}
            return Regla(texto, {k: v for k, v in p.items() if k in usados}, tuple(giros))
        loc = regla(e["localizacion"])
        per = regla(e["permanencia"]) if e.get("permanencia") else None
        out[g] = Modelo(loc, per)
    return out


def complejidad(espec: dict, giros: list[str]) -> int:
    return sum(m.complejidad for m in modelos(espec, giros).values())


def lista_params(espec: dict) -> list[tuple[str, str, float, float]]:
    return [(g, k, float(v[0]), float(v[1])) for g, e in espec.items() for k, v in e.get("params", {}).items()]


def a_valores(espec: dict, x01: np.ndarray) -> dict[str, dict[str, float]]:
    vals = {g: {} for g in espec}
    for (g, k, lo, hi), u in zip(lista_params(espec), x01):
        vals[g][k] = lo + float(np.clip(u, 0, 1)) * (hi - lo)
    return vals


# ------------------------------------------------------------ simulación en un proceso

_LOTES: dict[str, Lotes] = {}


def _lotes(ciudad: str) -> Lotes:
    if ciudad not in _LOTES:
        _LOTES[ciudad] = Lotes.cargar(ciudad)
    return _LOTES[ciudad]


def simular(escena: Escena, espec: dict, valores: dict, semilla: int, estado: bool = False):
    L = _lotes(escena.ciudad)
    s = Simulador(L, escena.giros, escena.n, modelos(espec, escena.giros), valores,
                  rotacion=escena.rotacion, semilla=semilla)
    s.iniciar()
    s.correr(escena.pasos)
    f = firma(L, s.lote, s.giro, len(escena.giros))
    return (f, s.lote, s.giro) if estado else f


def _tarea(args):
    return simular(*args)


def promedio(fs: list[dict]) -> dict[str, np.ndarray]:
    return {g: np.nanmean(np.stack([f[g] for f in fs]), 0) for g in GRUPOS}


def dispersion(fs: list[dict], piso: float = 0.05) -> dict[str, np.ndarray]:
    return {g: np.maximum(np.nan_to_num(np.nanstd(np.stack([f[g] for f in fs]), 0), nan=piso), piso) for g in GRUPOS}


class Banco:
    """Pool de procesos que simulan en paralelo."""

    def __init__(self, procesos: int | None = None):
        self.pool = mp.get_context("spawn").Pool(procesos or max(1, (os.cpu_count() or 2) - 1))

    def firmas(self, tareas: list[tuple]) -> list[dict]:
        return self.pool.map(_tarea, tareas)

    def cerrar(self):
        self.pool.close()
        self.pool.join()


@dataclass
class Resultado:
    espec: dict
    valores: dict
    distancia: dict
    complejidad: int
    evaluaciones: int
    segundos: float
    historia: list = field(default_factory=list)


def calibrar(banco: Banco, escena: Escena, espec: dict, objetivo: dict, escala: dict,
             replicas: int = 2, poblacion: int = 10, iteraciones: int = 12, semilla: int = 0,
             x0: np.ndarray | None = None) -> Resultado:
    t0 = time.time()
    P = lista_params(espec)
    giros = escena.giros
    comp = complejidad(espec, giros)

    def evaluar_todos(xs, base_semilla):
        tareas = [(escena, espec, a_valores(espec, x), base_semilla + 1000 * i + r)
                  for i, x in enumerate(xs) for r in range(replicas)]
        fs = banco.firmas(tareas)
        return [distancia(promedio(fs[i * replicas:(i + 1) * replicas]), objetivo, escala)
                for i in range(len(xs))]

    if not P:
        d = evaluar_todos([np.zeros(0)], semilla)[0]
        return Resultado(espec, a_valores(espec, np.zeros(0)), d, comp, replicas, time.time() - t0)

    if len(P) == 1:
        # CMA-ES no trabaja en 1D: rejilla gruesa y luego fina.
        rej = np.linspace(0, 1, poblacion + 1)
        ds = evaluar_todos([np.array([u]) for u in rej], semilla)
        i = int(np.argmin([d["total"] for d in ds]))
        paso = 1 / poblacion
        fina = np.clip(np.linspace(rej[i] - paso, rej[i] + paso, poblacion + 1), 0, 1)
        ds2 = evaluar_todos([np.array([u]) for u in fina], semilla + 7)
        todos = list(zip(np.concatenate([rej, fina]), ds + ds2))
        u, d = min(todos, key=lambda t: t[1]["total"])
        hist = [(float(a), b["total"]) for a, b in todos]
        return Resultado(espec, a_valores(espec, np.array([u])), d, comp, len(todos) * replicas,
                         time.time() - t0, hist)

    es = cma.CMAEvolutionStrategy(x0 if x0 is not None else np.full(len(P), 0.5), 0.25,
                                  {"bounds": [0, 1], "popsize": poblacion, "maxiter": iteraciones,
                                   "seed": semilla + 1, "verbose": -9})
    mejor, hist, n_eval = None, [], 0
    while not es.stop():
        xs = es.ask()
        ds = evaluar_todos(xs, semilla + 100_000 * es.countiter)
        n_eval += len(xs) * replicas
        es.tell(xs, [d["total"] for d in ds])
        for x, d in zip(xs, ds):
            if mejor is None or d["total"] < mejor[1]["total"]:
                mejor = (np.array(x), d)
        hist.append(min(d["total"] for d in ds))
    # La mejor de una sola evaluación está sesgada hacia abajo por el ruido:
    # se reevalúa la media de CMA-ES y el mejor punto con réplicas nuevas.
    cand = [mejor[0], np.clip(es.mean, 0, 1)]
    ds = evaluar_todos(cand, semilla + 999_999)
    i = int(np.argmin([d["total"] for d in ds]))
    return Resultado(espec, a_valores(espec, cand[i]), ds[i], comp, n_eval + 2 * replicas,
                     time.time() - t0, hist)
