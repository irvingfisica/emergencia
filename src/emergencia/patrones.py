"""Patrones observados del comercio sobre la red de calles (fase 0).

    python -m emergencia.patrones [--ciudad merida ...] [--version 2026_05 ...]

Lee <datos>/ciudades/<ciudad>/{tramos,comercios}.parquet y escribe en
salida/<ciudad>/<versión>/:

  jensen_r<r>.csv   P1: coeficientes de Jensen M_ab entre grupos de giro a distancia r
                    sobre la red, con su media y desviación bajo permutación de giros
  centros.csv       P2: centros comerciales detectados (densidad sobre la red)
  tramos.parquet    P3: comercios y densidad por tramo
  resumen.json      cifras de los tres patrones
  mapa.png, jensen.png

Todas las distancias son sobre la red: cada sitio con comercios (tramo, posición)
se inserta como nodo en su tramo.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from .ciudad import RAIZ, ciudades, giros

R_JENSEN = (100.0, 200.0)   # m
R_CENTRO = 300.0            # m: radio de densidad para centros
ENLACE_CENTRO = 150.0       # m: sitios densos a menos de esto pertenecen al mismo centro
FACTOR_CENTRO = 1.0         # umbral de densidad = factor × densidad media vista desde cada comercio
FACTORES_SENSIBILIDAD = (1.25, 1.5, 2.0)
MIN_CENTRO = 20             # comercios mínimos para contar un centro
PERMUTACIONES = 30

# ---------------------------------------------------------------- red con sitios

def red_de_sitios(tramos: gpd.GeoDataFrame, com: pd.DataFrame):
    """Grafo con intersecciones y sitios (tramo, t redondeado a 1 m) como nodos."""
    com = com.copy()
    largo = tramos.largo.values
    com["t"] = np.clip(com.t.values, 0, largo[com.tramo.values]).round(0)
    sitios = com[["tramo", "t"]].drop_duplicates().sort_values(["tramo", "t"]).reset_index(drop=True)
    sitios["sitio"] = np.arange(len(sitios))
    com = com.merge(sitios, on=["tramo", "t"], how="left")
    en_tramo = defaultdict(list)
    for tr, t, s in zip(sitios.tramo.values, sitios.t.values, sitios.sitio.values):
        en_tramo[tr].append((t, s))
    G = nx.Graph()
    for tr, u, v, L in zip(tramos.tramo.values, tramos.u.values, tramos.v.values, largo):
        cadena = [(0.0, ("n", u))] + [(t, ("s", s)) for t, s in en_tramo.get(tr, [])] + [(L, ("n", v))]
        for (t1, a), (t2, b) in zip(cadena, cadena[1:]):
            w = max(t2 - t1, 0.01)
            if not G.has_edge(a, b) or G[a][b]["w"] > w:
                G.add_edge(a, b, w=w)
    return G, com, sitios


_G = None


def _desde(args):
    sitios, rmax = args
    filas = []
    for s in sitios:
        for nodo, d in nx.single_source_dijkstra_path_length(_G, ("s", s), cutoff=rmax, weight="w").items():
            if nodo[0] == "s":
                filas.append((s, nodo[1], d))
    return filas


def distancias(G, n_sitios: int, rmax: float, procesos: int = 5) -> sparse.csr_matrix:
    """Matriz dispersa de distancias en red entre sitios a menos de rmax (la diagonal
    se guarda como 0.001 para no perderla)."""
    global _G
    _G = G
    lotes = [(list(range(i, min(i + 500, n_sitios))), rmax) for i in range(0, n_sitios, 500)]
    with mp.get_context("fork").Pool(procesos) as p:
        partes = p.map(_desde, lotes)
    f = np.array([x for parte in partes for x in parte])
    d = np.maximum(f[:, 2], 0.001)
    return sparse.csr_matrix((d, (f[:, 0].astype(int), f[:, 1].astype(int))), shape=(n_sitios, n_sitios))


def dentro(D: sparse.csr_matrix, r: float) -> sparse.csr_matrix:
    W = D.copy()
    W.data = (W.data <= r).astype(np.float64)
    W.eliminate_zeros()
    return W

# ---------------------------------------------------------------- P1 Jensen

def jensen(W: sparse.csr_matrix, sitio: np.ndarray, cat: np.ndarray, K: int) -> np.ndarray:
    """Coeficientes de Jensen (2006) sobre la red. M_ab > 1: los de b están más cerca
    de los de a de lo que estarían si los giros se repartieran al azar entre los
    mismos comercios; M_ab < 1: se evitan."""
    N = len(cat)
    X = sparse.csr_matrix((np.ones(N), (sitio, cat)), shape=(W.shape[0], K))
    Ci = np.asarray((W @ X).todense())[sitio]          # vecinos por giro de cada comercio (incluye él mismo)
    Ci[np.arange(N), cat] -= 1
    Nt = Ci.sum(1)
    Na = np.bincount(cat, minlength=K).astype(float)
    M = np.full((K, K), np.nan)
    for a in range(K):
        idx = cat == a
        if Na[a] < 2:
            continue
        ci = Ci[idx]
        ok = Nt[idx] > 0
        M[a, a] = (N - 1) / (Na[a] * (Na[a] - 1)) * np.sum(ci[ok, a] / Nt[idx][ok])
        den = Nt[idx] - ci[:, a]
        ok = den > 0
        S = (ci[ok] / den[ok, None]).sum(0)
        otros = np.arange(K) != a
        M[a, otros] = (N - Na[a]) / (Na[a] * Na[otros]) * S[otros]
    return M


def jensen_con_nulo(W, sitio, cat, K, n=PERMUTACIONES, semilla=0):
    M = jensen(W, sitio, cat, K)
    rng = np.random.default_rng(semilla)
    nulos = np.stack([jensen(W, sitio, rng.permutation(cat), K) for _ in range(n)])
    return M, np.nanmean(nulos, 0), np.nanstd(nulos, 0)

# ---------------------------------------------------------------- P2 centros

def centros(D, com, sitios_xy, factor=None):
    n = D.shape[0]
    X = np.bincount(com.sitio.values, minlength=n).astype(float)
    dens = dentro(D, R_CENTRO) @ X                       # comercios a <= 300 m de cada sitio
    umbral = (factor or FACTOR_CENTRO) * np.average(dens, weights=X)  # media vista desde cada comercio
    activo = dens >= umbral
    E = dentro(D, ENLACE_CENTRO)[activo][:, activo]
    _, etiqueta = connected_components(E, directed=False)
    sitio_centro = np.full(n, -1)
    sitio_centro[np.flatnonzero(activo)] = etiqueta
    c = com.assign(centro=sitio_centro[com.sitio.values])
    c = c[c.centro >= 0]
    tabla = (c.groupby("centro")
              .agg(comercios=("id", "size"), grupos=("grupo", "nunique"), x=("x", "mean"), y=("y", "mean"))
              .query("comercios >= @MIN_CENTRO").sort_values("comercios", ascending=False).reset_index())
    return tabla, dens, umbral


def resumen_centros(tabla: pd.DataFrame, total: int) -> dict:
    if len(tabla) < 2:
        return {"n": int(len(tabla))}
    xy = tabla[["x", "y"]].values
    d = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1))
    np.fill_diagonal(d, np.inf)
    rango = np.arange(1, len(tabla) + 1)
    pendiente = np.polyfit(np.log(rango), np.log(tabla.comercios.values), 1)[0]
    return {
        "n": int(len(tabla)),
        "fraccion_comercios_en_centros": float(tabla.comercios.sum() / total),
        "tamanos": tabla.comercios.head(10).tolist(),
        "pendiente_rango_tamano": float(pendiente),
        "distancia_vecino_mediana_m": float(np.median(d.min(1))),
        "grupos_vs_tamano_corr": float(np.corrcoef(np.log(tabla.comercios), tabla.grupos)[0, 1]),
    }

# ---------------------------------------------------------------- P3 corredores

def corredores(tramos: gpd.GeoDataFrame, com: pd.DataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    n = np.bincount(com.tramo.values, minlength=len(tramos))
    t = tramos[["tramo", "highway", "nombre", "largo", "geometry"]].copy()
    t["comercios"] = n
    t["por_km"] = t.comercios / (t.largo / 1000)
    orden = t.sort_values("por_km", ascending=False)
    frac_largo = orden.largo.cumsum() / orden.largo.sum()
    frac_com = orden.comercios.cumsum() / max(orden.comercios.sum(), 1)
    # Gini de comercios respecto a longitud de calle (curva de Lorenz, de menos a más denso)
    lorenz_x = np.concatenate([[0], (orden.largo.values[::-1].cumsum() / orden.largo.sum())])
    lorenz_y = np.concatenate([[0], (orden.comercios.values[::-1].cumsum() / max(orden.comercios.sum(), 1))])
    gini = 1 - 2 * np.trapezoid(lorenz_y, lorenz_x)
    calles = (t[t.nombre.notna()].groupby("nombre").agg(comercios=("comercios", "sum"), largo=("largo", "sum")))
    calles = calles[calles.largo >= 500]
    calles["por_km"] = calles.comercios / (calles.largo / 1000)
    por_tipo = t.groupby("highway").agg(comercios=("comercios", "sum"), km=("largo", lambda s: s.sum() / 1000))
    por_tipo["por_km"] = por_tipo.comercios / por_tipo.km
    res = {
        "gini_por_longitud": float(gini),
        "fraccion_comercios_en_5pct_de_calle": float(frac_com[frac_largo <= 0.05].max() if (frac_largo <= 0.05).any() else 0),
        "fraccion_comercios_en_10pct_de_calle": float(frac_com[frac_largo <= 0.10].max()),
        "fraccion_calle_sin_comercio": float(t.largo[t.comercios == 0].sum() / t.largo.sum()),
        "por_km_por_tipo": por_tipo.por_km.round(1).sort_values(ascending=False).to_dict(),
        "calles_mas_densas": calles.sort_values("por_km", ascending=False).head(10).round(1).reset_index().to_dict("records"),
    }
    return t, res

# ---------------------------------------------------------------- figuras

def mapa(tramos, t_dens, com, tabla_c, nombre, version, destino):
    fig, ax = plt.subplots(1, 2, figsize=(18, 9), dpi=150)
    for a in ax:
        tramos.plot(ax=a, color="#cccccc", linewidth=0.25)
        a.set_axis_off()
    top = com.grupo.value_counts().index[:12]
    cmap = plt.get_cmap("tab20")
    for i, g in enumerate(top):
        s = com[com.grupo == g]
        ax[0].scatter(s.x, s.y, s=0.6, color=cmap(i), label=f"{g} ({len(s):,})", linewidths=0)
    resto = com[~com.grupo.isin(top)]
    ax[0].scatter(resto.x, resto.y, s=0.4, color="#888888", label=f"otros ({len(resto):,})", linewidths=0)
    ax[0].legend(markerscale=12, fontsize=7, loc="lower left", frameon=False)
    ax[0].set_title(f"{nombre} · DENUE {version}: comercios por giro", fontsize=10)
    umbral = t_dens.por_km.quantile(0.95)
    t_dens[t_dens.por_km >= umbral].plot(ax=ax[1], color="#b2182b", linewidth=1.2)
    ax[1].scatter(tabla_c.x, tabla_c.y, s=tabla_c.comercios / 4, facecolors="none", edgecolors="#2166ac", linewidths=0.8)
    ax[1].set_title(f"Corredores (5 % de tramos más densos, rojo) y centros (azul, área ∝ comercios)", fontsize=10)
    fig.tight_layout()
    fig.savefig(destino / "mapa.png")
    plt.close(fig)


def figura_jensen(M, nulo_m, nulo_s, nombres, r, nombre, version, destino):
    L = np.log2(M)
    z = (M - nulo_m) / np.where(nulo_s > 0, nulo_s, np.nan)
    fig, ax = plt.subplots(figsize=(9, 8), dpi=150)
    im = ax.imshow(np.clip(L, -2, 2), cmap="RdBu_r", vmin=-2, vmax=2)
    yy, xx = np.where(np.abs(z) < 2)
    ax.scatter(xx, yy, marker=".", s=6, color="#555555")
    ax.set_xticks(range(len(nombres)), nombres, rotation=90, fontsize=7)
    ax.set_yticks(range(len(nombres)), nombres, fontsize=7)
    ax.set_title(f"{nombre} · {version}: log2 M_ab a {int(r)} m sobre la red\n(rojo: b cerca de a más que al azar; azul: se evitan; punto: |z| < 2)", fontsize=9)
    fig.colorbar(im, shrink=0.7)
    fig.tight_layout()
    fig.savefig(destino / "jensen.png")
    plt.close(fig)

# ---------------------------------------------------------------- principal

def procesar(ciudad: dict, version: str, datos: Path, salida: Path, procesos: int) -> dict:
    d = datos / ciudad["id"]
    tramos = gpd.read_parquet(d / "tramos.parquet")
    com = pd.read_parquet(d / "comercios.parquet")
    com = com[com.version == version].reset_index(drop=True)
    destino = salida / ciudad["id"] / version
    destino.mkdir(parents=True, exist_ok=True)
    G, com, sitios = red_de_sitios(tramos, com)
    D = distancias(G, len(sitios), max(max(R_JENSEN), R_CENTRO), procesos)

    nombres = [g for g in giros().grupo.unique() if g in set(com.grupo)]
    cat = com.grupo.map({g: i for i, g in enumerate(nombres)}).values.astype(int)
    res = {"ciudad": ciudad["id"], "version": version, "comercios": int(len(com)), "sitios": int(len(sitios)),
           "por_grupo": com.grupo.value_counts().to_dict(), "jensen": {}}
    for r in R_JENSEN:
        M, m0, s0 = jensen_con_nulo(dentro(D, r), com.sitio.values, cat, len(nombres))
        filas = [{"a": nombres[i], "b": nombres[j], "M": M[i, j], "nulo_media": m0[i, j], "nulo_sd": s0[i, j]}
                 for i in range(len(nombres)) for j in range(len(nombres))]
        pd.DataFrame(filas).to_csv(destino / f"jensen_r{int(r)}.csv", index=False)
        diag = {nombres[i]: round(float(M[i, i]), 2) for i in range(len(nombres))}
        res["jensen"][f"r{int(r)}"] = {"autoatraccion": dict(sorted(diag.items(), key=lambda x: -x[1]))}
        if r == R_JENSEN[-1]:
            figura_jensen(M, m0, s0, nombres, r, ciudad["nombre"], version, destino)

    tabla_c, dens, umbral = centros(D, com, sitios)
    tabla_c.to_csv(destino / "centros.csv", index=False)
    res["centros"] = resumen_centros(tabla_c, len(com)) | {"umbral_comercios_300m": float(umbral)}
    res["centros"]["sensibilidad"] = {}
    for f in FACTORES_SENSIBILIDAD:
        t_f, _, u_f = centros(D, com, sitios, f)
        r_f = resumen_centros(t_f, len(com))
        res["centros"]["sensibilidad"][f"x{f}"] = {k: r_f.get(k) for k in ("n", "pendiente_rango_tamano", "fraccion_comercios_en_centros")}
    t_dens, res["corredores"] = corredores(tramos, com)
    t_dens.drop(columns="geometry").to_parquet(destino / "tramos.parquet")
    mapa(tramos, t_dens, com, tabla_c, ciudad["nombre"], version, destino)
    (destino / "resumen.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", nargs="*")
    ap.add_argument("--version", nargs="*")
    ap.add_argument("--datos", type=Path, default=RAIZ / "datos" / "ciudades")
    ap.add_argument("--salida", type=Path, default=RAIZ / "salida")
    ap.add_argument("--procesos", type=int, default=5)
    a = ap.parse_args()
    for c in ciudades(a.ciudad):
        versiones = a.version or sorted(pd.read_parquet(a.datos / c["id"] / "comercios.parquet", columns=["version"]).version.unique())
        for v in versiones:
            r = procesar(c, v, a.datos, a.salida, a.procesos)
            print(f"{c['nombre']} {v}: {r['comercios']:,} comercios; centros: {r['centros'].get('n')}; "
                  f"Gini corredores: {r['corredores']['gini_por_longitud']:.2f}", flush=True)


if __name__ == "__main__":
    main()
