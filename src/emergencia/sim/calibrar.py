"""Calibración interna: dados la estructura de las reglas, busca los parámetros.

Una *especificación* dice, para cada giro, el texto de sus reglas y el rango de
cada parámetro:

    {"ropa": {"localizacion": "(1+mismo200)**b * exp(c*avenida)",
              "params": {"b": [0, 3], "c": [0, 3]}},
     "abarrotes": {"localizacion": "pob500**a", "params": {"a": [0, 3]}}}

(con "permanencia" opcional). Los parámetros son independientes por giro. Un rango
con tercer elemento "log" (p. ej. [0.001, 1, "log"]) se recorre en escala logarítmica.

La calibración usa CMA-ES en el cubo [0, 1] y evalúa cada punto con varias
réplicas en paralelo. Con `x0` (p. ej. los parámetros de una estructura más chica,
vía `a_cubo`) el primer arranque sale de ahí y ese punto compite en la evaluación
final, así que una estructura que contiene a otra no ajusta peor que ella salvo por
ruido. Con `arranques` > 1 corren varias CMA-ES a la vez desde
puntos iniciales distintos (contra los óptimos locales) y al final se reevalúan
el mejor punto y la media de cada una.
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
        p = {k: (float(v[0]), float(v[1])) for k, v in e.get("params", {}).items()}

        def regla(texto):
            usados = {n.id for n in ast.walk(ast.parse(texto, mode="eval")) if isinstance(n, ast.Name)}
            return Regla(texto, {k: v for k, v in p.items() if k in usados}, tuple(giros))
        loc = regla(e["localizacion"])
        per = regla(e["permanencia"]) if e.get("permanencia") else None
        out[g] = Modelo(loc, per)
    return out


def complejidad(espec: dict, giros: list[str]) -> int:
    return sum(m.complejidad for m in modelos(espec, giros).values())


def lista_params(espec: dict) -> list[tuple[str, str, float, float, bool]]:
    return [(g, k, float(v[0]), float(v[1]), len(v) > 2 and v[2] == "log")
            for g, e in espec.items() for k, v in e.get("params", {}).items()]


def a_cubo(espec: dict, valores: dict[str, dict[str, float]], neutros: dict[str, float] | None = None) -> np.ndarray:
    """Inversa de a_valores: los parámetros que faltan en `valores` toman su valor
    neutro (por nombre en `neutros`, 0 si no se da), recortado al rango."""
    neutros = neutros or {}
    x = []
    for g, k, lo, hi, log in lista_params(espec):
        v = valores.get(g, {}).get(k, neutros.get(k, 0.0))
        v = min(max(v, lo), hi)
        x.append(np.log(v / lo) / np.log(hi / lo) if log else (v - lo) / (hi - lo))
    return np.array(x)


def a_valores(espec: dict, x01: np.ndarray) -> dict[str, dict[str, float]]:
    vals = {g: {} for g in espec}
    for (g, k, lo, hi, log), u in zip(lista_params(espec), x01):
        u = float(np.clip(u, 0, 1))
        vals[g][k] = lo * (hi / lo) ** u if log else lo + u * (hi - lo)
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
    arranques: list = field(default_factory=list)   # (valores, distancia total) de cada arranque


def calibrar(banco: Banco, escena: Escena, espec: dict, objetivo: dict, escala: dict,
             replicas: int = 2, poblacion: int = 10, iteraciones: int = 12, semilla: int = 0,
             x0: np.ndarray | None = None, arranques: int = 1) -> Resultado:
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

    d = len(P)
    rng = np.random.default_rng(semilla)
    x0s = [x0 if x0 is not None else np.full(d, 0.5)] + [rng.uniform(0.1, 0.9, d) for _ in range(arranques - 1)]
    # Desde un punto heredado se explora más cerca (paso inicial menor).
    sigmas = [0.12 if x0 is not None else 0.25] + [0.25] * (arranques - 1)
    ess = [cma.CMAEvolutionStrategy(x, sigmas[j], {"bounds": [0, 1], "popsize": poblacion, "maxiter": iteraciones,
                                              "seed": semilla + 1 + j, "verbose": -9})
           for j, x in enumerate(x0s)]
    mejor = [None] * len(ess)
    hist, n_eval, it = [], 0, 0
    while not all(es.stop() for es in ess):
        activos = [j for j, es in enumerate(ess) if not es.stop()]
        xs = {j: ess[j].ask() for j in activos}
        planos = [x for j in activos for x in xs[j]]
        ds = evaluar_todos(planos, semilla + 100_000 * (it + 1))
        it += 1
        n_eval += len(planos) * replicas
        pos = 0
        for j in activos:
            dj = ds[pos:pos + len(xs[j])]
            pos += len(xs[j])
            ess[j].tell(xs[j], [x["total"] for x in dj])
            for x, dd in zip(xs[j], dj):
                if mejor[j] is None or dd["total"] < mejor[j][1]["total"]:
                    mejor[j] = (np.array(x), dd)
        hist.append(min(x["total"] for x in ds))
    # La mejor de una sola evaluación está sesgada hacia abajo por el ruido:
    # se reevalúan el mejor punto y la media de cada arranque con réplicas nuevas.
    cand = [c for j, es in enumerate(ess) for c in (mejor[j][0], np.clip(es.mean, 0, 1))]
    if x0 is not None:
        cand.append(np.asarray(x0))  # el punto heredado también compite al final
    ds = evaluar_todos(cand, semilla + 999_999)
    n_eval += len(cand) * replicas
    i = int(np.argmin([x["total"] for x in ds]))
    por_arranque = [(a_valores(espec, cand[2 * j + int(ds[2 * j + 1]["total"] < ds[2 * j]["total"])]),
                     min(ds[2 * j]["total"], ds[2 * j + 1]["total"])) for j in range(len(ess))]
    return Resultado(espec, a_valores(espec, cand[i]), ds[i], comp, n_eval, time.time() - t0, hist, por_arranque)
