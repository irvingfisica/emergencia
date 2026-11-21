"""Verdad para la prueba 1b: sistema dinámico de lugares centrales sobre la red.

Es el modelo de central_theory_sim (White 1977, tipo Harris–Wilson), sobre la red
de calles de una ciudad real en lugar de una rejilla:

    R_j = Σ_i P_i · W_j d_ij^-η / Σ_k W_k d_ik^-η      ingreso del centro j
    W_j ← W_j + g (R_j − W_j)                            crece si el ingreso supera el costo

P_i es la población (Censo 2020) agregada en celdas de CELDA_DEMANDA m; los centros
posibles son un lote por celda de CELDA_OFERTA m; d_ij es la distancia en red (km)
más D0. η es el exponente de la distancia: con η chico la competencia es de largo
alcance y sobreviven pocos centros grandes; con η grande, muchos chicos.

No es un modelo de agentes: el ingreso de cada centro depende de todos los demás.
Por eso sirve de prueba: el método debe encontrar una regla local que reproduzca sus
patrones, y los parámetros recuperados deben seguir a η.

Para pasar a comercios, el tamaño final de cada centro se convierte en un número de
comercios (multinomial) que se ponen en lotes a <= 100 m del centro.
"""
from __future__ import annotations

import time

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from ..ciudad import RAIZ
from .lotes import CAPACIDAD, Lotes, grafo

CELDA_OFERTA = 150.0
CELDA_DEMANDA = 300.0
D0 = 0.1  # km


def _por_celda(x, y, celda, peso):
    """Para cada celda, el índice del elemento de mayor peso (desempate: el primero)."""
    cx, cy = np.floor(x / celda).astype(np.int64), np.floor(y / celda).astype(np.int64)
    df = pd.DataFrame({"c": cx * 1_000_003 + cy, "p": peso, "i": np.arange(len(x))})
    return df.sort_values(["c", "p"], ascending=[True, False]).drop_duplicates("c").i.to_numpy(), df.c.to_numpy()


def preparar(ciudad: str, paso: int = 25) -> dict:
    """Centros posibles, puntos de demanda y distancias en red (se guarda en caché)."""
    base = RAIZ / "datos" / "ciudades" / ciudad
    cache = base / f"hw_{paso}.npz"
    if cache.exists():
        z = np.load(cache)
        return {k: z[k] for k in z.files}
    t0 = time.time()
    L = Lotes.cargar(ciudad, paso)
    x, y, p = L.col("x"), L.col("y"), L.col("pob")
    # Oferta: un lote por celda, el que tiene más población alrededor (evita lotes aislados).
    oferta, _ = _por_celda(x, y, CELDA_OFERTA, L.col("pob500"))
    # Demanda: población sumada por celda, ubicada en el lote más poblado de la celda.
    con = np.flatnonzero(p > 0)
    sel, celdas = _por_celda(x[con], y[con], CELDA_DEMANDA, p[con])
    suma = pd.Series(p[con]).groupby(celdas).sum()
    demanda = con[sel]
    P = suma.reindex(celdas[sel]).to_numpy()
    _, G = grafo(gpd.read_parquet(base / "tramos.parquet"), paso)
    d = np.vstack([dijkstra(G, directed=False, indices=demanda[i:i + 64])[:, oferta]
                   for i in range(0, len(demanda), 64)]).astype(np.float32) / 1000
    d[~np.isfinite(d)] = 1e3
    out = {"oferta": oferta, "demanda": demanda, "P": P, "d": d}
    np.savez_compressed(cache, **out)
    print(f"{ciudad}: {len(oferta):,} centros posibles, {len(demanda):,} puntos de demanda, "
          f"{time.time() - t0:.0f} s", flush=True)
    return out


def equilibrar(P: np.ndarray, d: np.ndarray, eta: float, rng, g: float = 1.0,
               pasos: int = 3000, tol: float = 1e-5) -> np.ndarray:
    """Equilibrio de W. Con costo lineal, el punto fijo W = R es la actualización EM de
    los pesos de una mezcla con núcleo d^-η, así que g = 1 llega al mismo equilibrio
    que la dinámica lenta de central_theory_sim, en menos pasos."""
    K = ((d + D0) ** (-eta)).astype(np.float32)
    P = P.astype(np.float32)
    J = d.shape[1]
    W = (P.sum() / J * (1 + 0.1 * rng.standard_normal(J)).clip(0.5)).astype(np.float32)
    for _ in range(pasos):
        R = W * ((P / (K @ W)) @ K)
        nuevo = np.maximum(W + g * (R - W), 0)
        if np.abs(nuevo - W).max() < tol * P.sum() / J:
            W = nuevo
            break
        W = nuevo
    return W


def vivos(W: np.ndarray, frac: float = 1e-3) -> int:
    return int((W > frac * W.max()).sum())


def a_comercios(L: Lotes, oferta: np.ndarray, W: np.ndarray, n: int, rng, ocup: np.ndarray,
                capacidad: int = CAPACIDAD) -> np.ndarray:
    """n comercios repartidos entre los centros ∝ W, en lotes a <= 100 m del centro."""
    p = np.asarray(W, dtype=np.float64)
    cuenta = rng.multinomial(n, p / p.sum())
    W100 = L.W(100.0)
    out = []
    for j in np.flatnonzero(cuenta):
        vecinos = W100.indices[W100.indptr[oferta[j]]:W100.indptr[oferta[j] + 1]]
        for _ in range(cuenta[j]):
            libres = vecinos[ocup[vecinos] < capacidad]
            if len(libres) == 0:
                vecinos = np.flatnonzero(ocup < capacidad)  # caso extremo: cualquier lote libre
                libres = vecinos
            c = rng.choice(libres)
            ocup[c] += 1
            out.append(c)
    return np.array(out, dtype=int)
