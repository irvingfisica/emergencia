"""Espacio del simulador: lotes a lo largo de la red de calles.

    python -m emergencia.sim.lotes [--ciudad aguascalientes] [--paso 25]

Cada tramo se parte en lotes de unos `paso` metros. Un lote es un lugar donde pueden
instalarse hasta CAPACIDAD comercios. Para cada lote se guarda:

  tramo, t, x, y      posición sobre la red
  via                 jerarquía de la calle: 0 local, 1 terciaria, 2 secundaria,
                      3 primaria o troncal, 4 peatonal
  pob200, pob500      población (Censo 2020) a <= 200 m y <= 500 m sobre la red

y la matriz dispersa de distancias en red entre lotes a <= RMAX.
Salida: datos/ciudades/<ciudad>/lotes_<paso>.npz y lotes_<paso>.parquet.

Para la percepción de largo alcance (RADIOS_LARGOS) hay además una malla gruesa
(`malla`): celdas de CELDA m, cada una representada por su lote más poblado, con
distancias en red entre celdas. Un comercio percibe lo que hay en las celdas a <= r
de la suya. Se guarda en malla_<CELDA>.npz y se construye la primera vez que se pide.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import dijkstra

from ..ciudad import RAIZ, ciudades

RMAX = 200.0
R_POB = (200.0, 500.0)
CAPACIDAD = 3
CELDA = 200.0
RADIOS_LARGOS = (1000.0, 2000.0)
VIA = {"residential": 0, "living_street": 0, "unclassified": 0, "road": 0,
       "tertiary": 1, "tertiary_link": 1, "secondary": 2, "secondary_link": 2,
       "primary": 3, "primary_link": 3, "trunk": 3, "trunk_link": 3, "pedestrian": 4}


class Lotes:
    """Lotes de una ciudad con sus distancias en red."""

    def __init__(self, tabla: pd.DataFrame, D: sparse.csr_matrix, base: Path | None = None, paso: int = 25):
        self.tabla = tabla.reset_index(drop=True)
        self.D = D
        self.n = len(tabla)
        self.base, self.paso = base, paso
        self._W = {}
        self._malla = None

    def malla(self) -> dict:
        """Malla gruesa: celda de cada lote, población por celda y distancias en red
        entre celdas a <= max(RADIOS_LARGOS)."""
        if self._malla is None:
            cache = self.base / f"malla_{int(CELDA)}.npz"
            if not cache.exists():
                construir_malla(self, cache)
            z = np.load(cache)
            D = sparse.csr_matrix((z["d"], (z["i"], z["j"])), shape=(len(z["pob"]),) * 2)
            self._malla = {"celda": z["celda"], "pob": z["pob"], "D": D, "W": {}}
        return self._malla

    def Wm(self, r: float) -> sparse.csr_matrix:
        """Vecindad binaria entre celdas a <= r (incluye la propia)."""
        m = self.malla()
        if r not in m["W"]:
            W = m["D"].copy()
            W.data = (W.data <= r).astype(np.float32)
            W.eliminate_zeros()
            m["W"][r] = W.tocsr()
        return m["W"][r]

    def W(self, r: float) -> sparse.csr_matrix:
        """Vecindad binaria a <= r (incluye el propio lote)."""
        if r not in self._W:
            W = self.D.copy()
            W.data = (W.data <= r).astype(np.float32)
            W.eliminate_zeros()
            self._W[r] = W.tocsr()
        return self._W[r]

    def col(self, nombre: str) -> np.ndarray:
        return self.tabla[nombre].to_numpy()

    def ubicar(self, tramo: np.ndarray, t: np.ndarray) -> np.ndarray:
        """Lote más cercano a cada punto (tramo, t) de la red."""
        tab = self.tabla
        inicio = tab.groupby("tramo").cumcount().to_numpy() == 0
        primero = pd.Series(np.flatnonzero(inicio), index=tab.tramo.to_numpy()[inicio])
        n_por = tab.groupby("tramo").size()
        largo = tab.groupby("tramo").largo.first()
        i0 = primero.reindex(tramo).to_numpy()
        n = n_por.reindex(tramo).to_numpy()
        L = largo.reindex(tramo).to_numpy()
        k = np.clip((t / L * n).astype(int), 0, n - 1)
        return (i0 + k).astype(int)

    @staticmethod
    def cargar(ciudad: str, paso: int = 25, datos: Path | None = None) -> "Lotes":
        base = (datos or RAIZ / "datos" / "ciudades") / ciudad
        tabla = pd.read_parquet(base / f"lotes_{paso}.parquet")
        D = sparse.load_npz(base / f"lotes_{paso}.npz").tocsr()
        return Lotes(tabla, D, base, paso)


def construir_malla(L: Lotes, destino: Path) -> None:
    t0 = time.time()
    x, y = L.col("x"), L.col("y")
    cx, cy = np.floor(x / CELDA).astype(np.int64), np.floor(y / CELDA).astype(np.int64)
    clave = cx * 1_000_003 + cy
    celdas, celda = np.unique(clave, return_inverse=True)
    nc = len(celdas)
    # Representante: el lote con más población a 500 m (evita lotes aislados).
    orden = np.lexsort((-L.col("pob500"), celda))
    primero = np.r_[True, celda[orden][1:] != celda[orden][:-1]]
    rep = orden[primero]
    pob = np.bincount(celda, weights=L.col("pob"), minlength=nc)
    _, G = grafo(gpd.read_parquet(L.base / "tramos.parquet"), L.paso)
    I, J, V = [], [], []
    for i in range(0, nc, 256):
        d = dijkstra(G, directed=False, indices=rep[i:i + 256], limit=max(RADIOS_LARGOS))[:, rep]
        r, c = np.nonzero(np.isfinite(d))
        I.append(i + r); J.append(c); V.append(d[r, c].astype(np.float32))
    # Escritura atómica: varios procesos pueden pedir la malla a la vez.
    tmp = destino.with_name(f"{destino.stem}.{os.getpid()}.tmp.npz")
    np.savez_compressed(tmp, celda=celda.astype(np.int32), pob=pob, i=np.concatenate(I).astype(np.int32),
                        j=np.concatenate(J).astype(np.int32), d=np.concatenate(V))
    os.replace(tmp, destino)
    print(f"  malla de {CELDA:.0f} m: {nc:,} celdas, {sum(len(v) for v in V):,} pares, {time.time() - t0:.0f} s",
          flush=True)


def grafo(tramos: gpd.GeoDataFrame, paso: float) -> tuple[pd.DataFrame, sparse.csr_matrix]:
    """Tabla de lotes y grafo de la red (nodos 0..n-1 son lotes; después las
    intersecciones). Con el mismo paso, los lotes coinciden con los de `construir`."""
    tramos = tramos.sort_values("tramo").reset_index(drop=True)
    L = tramos.largo.to_numpy()
    n = np.maximum(1, np.round(L / paso)).astype(int)
    tr = np.repeat(tramos.tramo.to_numpy(), n)
    idx = np.concatenate([np.arange(k) for k in n])
    Lr = np.repeat(L, n)
    t = (idx + 0.5) * Lr / np.repeat(n, n)
    geom = tramos.geometry.to_numpy()
    pts = [geom[i].interpolate(tt) for i, tt in zip(np.repeat(np.arange(len(tramos)), n), t)]
    tabla = pd.DataFrame({
        "tramo": tr, "t": t, "largo": Lr,
        "x": [p.x for p in pts], "y": [p.y for p in pts],
        "via": np.repeat(tramos.highway.map(VIA).fillna(0).astype(int).to_numpy(), n),
    })
    nl = len(tabla)

    # Grafo: nodos 0..nl-1 son lotes; después las intersecciones.
    nodos = pd.Index(pd.unique(np.concatenate([tramos.u.to_numpy(), tramos.v.to_numpy()])))
    iu = nl + nodos.get_indexer(tramos.u.to_numpy())
    iv = nl + nodos.get_indexer(tramos.v.to_numpy())
    a, b, w = [], [], []
    inicio = np.concatenate([[0], np.cumsum(n)[:-1]])
    for k in range(len(tramos)):
        s, m, Lk = inicio[k], n[k], L[k]
        seg = Lk / m
        a += [iu[k], s + m - 1]
        b += [s, iv[k]]
        w += [seg / 2, seg / 2]
        if m > 1:
            a += list(range(s, s + m - 1))
            b += list(range(s + 1, s + m))
            w += [seg] * (m - 1)
    N = nl + len(nodos)
    w = np.maximum(np.array(w), 0.01)
    G = sparse.coo_matrix((w, (a, b)), shape=(N, N)).tocsr()
    return tabla, G


def construir(tramos: gpd.GeoDataFrame, pob: pd.DataFrame, paso: float) -> tuple[pd.DataFrame, sparse.csr_matrix]:
    tabla, G = grafo(tramos, paso)
    nl = len(tabla)

    def bloques(fuentes, limite, lote=128):
        for i in range(0, len(fuentes), lote):
            f = fuentes[i:i + lote]
            d = dijkstra(G, directed=False, indices=f, limit=limite)[:, :nl]
            yield f, d

    filas, cols, vals = [], [], []
    t0 = time.time()
    for f, d in bloques(np.arange(nl), RMAX):
        r, c = np.nonzero(np.isfinite(d))
        filas.append(f[r]); cols.append(c); vals.append(np.maximum(d[r, c], 0.001).astype(np.float32))
    D = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(filas), np.concatenate(cols))), shape=(nl, nl))
    print(f"  distancias <= {RMAX:.0f} m: {D.nnz:,} pares ({D.nnz / nl:.0f} por lote), {time.time() - t0:.0f} s", flush=True)

    # Población: cada manzana al lote más cercano, y suma a <= r sobre la red.
    lotes = Lotes(tabla, D)
    pob = pob[pob.tramo.isin(tabla.tramo)]
    lp = lotes.ubicar(pob.tramo.to_numpy(), pob.t.to_numpy())
    p = np.bincount(lp, weights=pob.pob.to_numpy(), minlength=nl)
    fuentes = np.flatnonzero(p > 0)
    acum = {r: np.zeros(nl) for r in R_POB}
    for f, d in bloques(fuentes, max(R_POB)):
        for r in R_POB:
            acum[r] += (p[f][:, None] * (d <= r)).sum(0)
    for r in R_POB:
        tabla[f"pob{int(r)}"] = acum[r]
    tabla["pob"] = p
    return tabla, D


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", nargs="*")
    ap.add_argument("--paso", type=int, default=25)
    ap.add_argument("--datos", type=Path, default=RAIZ / "datos" / "ciudades")
    a = ap.parse_args()
    for c in ciudades(a.ciudad):
        base = a.datos / c["id"]
        t0 = time.time()
        tabla, D = construir(gpd.read_parquet(base / "tramos.parquet"), pd.read_parquet(base / "poblacion.parquet"), a.paso)
        tabla.to_parquet(base / f"lotes_{a.paso}.parquet")
        sparse.save_npz(base / f"lotes_{a.paso}.npz", D)
        print(f"{c['nombre']}: {len(tabla):,} lotes, población {tabla.pob.sum():,.0f}, {time.time() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
