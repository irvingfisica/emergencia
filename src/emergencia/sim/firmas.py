"""Firma de patrones de una configuración de comercios sobre los lotes.

Se usa la misma función para lo observado (DENUE ubicado en lotes) y lo simulado,
así la comparación no depende de cómo se midió cada uno. Es una versión rápida de
P1–P4 de la fase 0:

  P1 jensen        log2 M_ab a <= 200 m (K×K)
  P2 centros       para umbrales f = 1, 1.5, 2 × la densidad media que ve un comercio:
                   log(1 + número de centros) y fracción de comercios en centros;
                   pendiente rango–tamaño con f = 1
  P3 corredores    Gini de comercios contra longitud de calle, fracción en el 5 % de
                   la calle más densa, fracción de calle sin comercio, y comercios
                   por km en cada tipo de vía entre comercios por km en total (log)
  P4 demanda       por giro, log de la población a <= 500 m de sus comercios entre
                   la media de los lotes
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from ..patrones import jensen
from .lotes import Lotes

FACTORES = (1.0, 1.5, 2.0)
MIN_CENTRO = 20
GRUPOS = ("jensen", "centros", "corredores", "demanda")


def firma(L: Lotes, lote: np.ndarray, giro: np.ndarray, K: int) -> dict[str, np.ndarray]:
    W200, W100 = L.W(200.0), L.W(100.0)
    n = L.n
    out = {}
    # P1
    M = jensen(W200, lote, giro, K)
    out["jensen"] = np.log2(np.clip(M, 1 / 16, 16)).ravel()
    # P2
    X = np.bincount(lote, minlength=n).astype(float)
    dens = W200 @ X
    media = dens[lote].mean()
    vals = []
    pendiente = np.nan
    for f in FACTORES:
        denso = np.flatnonzero((dens >= f * media) & (X > 0))
        if len(denso) == 0:
            vals += [0.0, 0.0]
            continue
        sub = W100[denso][:, denso]
        nc, etiq = connected_components(sub, directed=False)
        tam = np.bincount(etiq, weights=X[denso])
        tam = np.sort(tam[tam >= MIN_CENTRO])[::-1]
        vals += [np.log1p(len(tam)), tam.sum() / len(lote)]
        if f == 1.0 and len(tam) >= 3:
            pendiente = np.polyfit(np.log(np.arange(1, len(tam) + 1)), np.log(tam), 1)[0]
    out["centros"] = np.array(vals + [pendiente if np.isfinite(pendiente) else -3.0])
    # P3
    tramo = L.col("tramo")
    largo = L.tabla.groupby("tramo").largo.first()
    por_tramo = pd.Series(np.bincount(np.searchsorted(largo.index.to_numpy(), tramo[lote]),
                                      minlength=len(largo)), index=largo.index)
    dl = (por_tramo / largo).to_numpy()
    orden = np.argsort(-dl)
    Ls = largo.to_numpy()[orden]
    cs = por_tramo.to_numpy()[orden]
    x = np.concatenate([[0], np.cumsum(Ls) / Ls.sum()])
    y = np.concatenate([[0], np.cumsum(cs) / cs.sum()])
    gini = 2 * np.trapezoid(y, x) - 1
    top5 = np.interp(0.05, x, y)
    vacia = Ls[cs == 0].sum() / Ls.sum()
    via = L.col("via")
    km = np.bincount(via, minlength=5) * 1.0   # lotes ≈ longitud uniforme
    por_via = np.bincount(via[lote], minlength=5) / np.maximum(km, 1)
    total = len(lote) / km.sum()
    out["corredores"] = np.concatenate([[gini, top5, vacia], np.log(np.maximum(por_via, 1e-3) / total)])
    # P4
    p = L.col("pob500")
    pm = p.mean()
    out["demanda"] = np.array([np.log(max(p[lote[giro == k]].mean(), 1) / pm) if np.any(giro == k) else 0.0
                               for k in range(K)])
    return out


def vector(f: dict[str, np.ndarray]) -> np.ndarray:
    return np.concatenate([f[g] for g in GRUPOS])


def distancia(fs: dict[str, np.ndarray], objetivo: dict[str, np.ndarray], escala: dict[str, np.ndarray],
              pesos: dict[str, float] | None = None) -> dict[str, float]:
    """Error cuadrático medio estandarizado por grupo de patrones y su suma."""
    pesos = pesos or {g: 1.0 for g in GRUPOS}
    d = {}
    for g in GRUPOS:
        z = (fs[g] - objetivo[g]) / escala[g]
        z = z[np.isfinite(z)]
        d[g] = float(np.mean(z ** 2)) if len(z) else 0.0
    d["total"] = sum(pesos[g] * d[g] for g in GRUPOS) / sum(pesos.values())
    return d
