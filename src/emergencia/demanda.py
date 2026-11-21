"""P4: relación del comercio con la demanda (población 2020 por manzana).

    python -m emergencia.demanda [--ciudad ...] [--version ...]

Para cada grupo de giro, en salida/<ciudad>/<versión>/demanda.csv:

  habitantes_por_comercio  población de la ciudad / comercios del grupo
  acceso_mediana_m         distancia mediana (sobre la red, ponderada por población)
                           de una manzana al comercio más cercano del grupo
  acceso_p90_m             percentil 90 de esa distancia
  acceso_razon             acceso_mediana / la misma medida si los comercios del grupo
                           estuvieran en puntos al azar de la calle (< 1: el grupo se
                           reparte para estar cerca de la gente; > 1: se concentra)
  demanda_local_razon      población a <= 500 m de los comercios del grupo / población
                           a <= 500 m de puntos al azar de la calle

La población es la del Censo 2020 para todas las versiones del DENUE.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

from .ciudad import RAIZ, ciudades, giros
from .patrones import dentro, distancias, red_de_sitios

R_DEMANDA = 500.0
CORTE_ACCESO = 5000.0
N_AZAR = 6000
REPETICIONES_NULO = 3


def puntos_azar(tramos: gpd.GeoDataFrame, n: int, rng) -> pd.DataFrame:
    p = tramos.largo.values / tramos.largo.sum()
    tr = rng.choice(len(tramos), size=n, p=p)
    return pd.DataFrame({"tramo": tr, "t": rng.random(n) * tramos.largo.values[tr]})


def _ponderada(valores, pesos, q):
    o = np.argsort(valores)
    v, w = valores[o], pesos[o]
    c = np.cumsum(w) / w.sum()
    return float(v[np.searchsorted(c, q)])


def acceso(G, fuentes_sitios, manzana_sitio, pob):
    d = nx.multi_source_dijkstra_path_length(G, {("s", s) for s in fuentes_sitios}, cutoff=CORTE_ACCESO, weight="w")
    dist = np.array([d.get(("s", s), CORTE_ACCESO) for s in manzana_sitio])
    return _ponderada(dist, pob, 0.5), _ponderada(dist, pob, 0.9)


def procesar(ciudad: dict, version: str, datos: Path, salida: Path, procesos: int, semilla=0) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    d = datos / ciudad["id"]
    tramos = gpd.read_parquet(d / "tramos.parquet")
    com = pd.read_parquet(d / "comercios.parquet")
    com = com[com.version == version]
    pob = pd.read_parquet(d / "poblacion.parquet")
    az = puntos_azar(tramos, N_AZAR, rng)
    pts = pd.concat([com[["tramo", "t", "grupo"]].assign(clase="comercio"),
                     pob[["tramo", "t", "pob"]].assign(clase="manzana"),
                     az.assign(clase="azar")], ignore_index=True)
    G, pts, sitios = red_de_sitios(tramos, pts)
    D = distancias(G, len(sitios), R_DEMANDA, procesos)
    man = pts[pts.clase == "manzana"]
    pob_sitio = np.bincount(man.sitio, weights=man.pob, minlength=len(sitios))
    dem = dentro(D, R_DEMANDA) @ pob_sitio
    azar = pts[pts.clase == "azar"].sitio.values
    dem_azar = dem[azar].mean()
    total = man.pob.sum()

    filas = []
    for g in [x for x in giros().grupo.unique() if x in set(com.grupo)]:
        s = pts[(pts.clase == "comercio") & (pts.grupo == g)].sitio.values
        med, p90 = acceso(G, set(s), man.sitio.values, man.pob.values)
        nulos = [acceso(G, set(rng.choice(azar, size=len(s), replace=len(s) > len(azar))), man.sitio.values, man.pob.values)[0]
                 for _ in range(REPETICIONES_NULO)]
        filas.append({"grupo": g, "comercios": len(s), "habitantes_por_comercio": total / len(s),
                      "acceso_mediana_m": med, "acceso_p90_m": p90, "acceso_nulo_m": float(np.mean(nulos)),
                      "acceso_razon": med / np.mean(nulos), "demanda_local_razon": dem[s].mean() / dem_azar})
    t = pd.DataFrame(filas)
    destino = salida / ciudad["id"] / version
    destino.mkdir(parents=True, exist_ok=True)
    t.round(3).to_csv(destino / "demanda.csv", index=False)
    figura(t, ciudad["nombre"], version, destino)
    return t


def figura(t: pd.DataFrame, nombre, version, destino):
    fig, ax = plt.subplots(figsize=(8, 7), dpi=150)
    ax.scatter(t.habitantes_por_comercio, t.acceso_razon, s=np.sqrt(t.comercios) * 3, color="#2166ac", alpha=0.7)
    for _, r in t.iterrows():
        ax.annotate(r.grupo, (r.habitantes_por_comercio, r.acceso_razon), fontsize=7, xytext=(3, 2), textcoords="offset points")
    ax.set_xscale("log")
    ax.axhline(1, color="#999999", linewidth=0.8)
    ax.set_xlabel("habitantes por comercio del grupo")
    ax.set_ylabel("acceso: distancia mediana real / al azar")
    ax.set_title(f"{nombre} · {version}: qué tan cerca de la gente se reparte cada giro\n(< 1: más cerca que al azar; > 1: concentrado)", fontsize=9)
    fig.tight_layout()
    fig.savefig(destino / "demanda.png")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", nargs="*")
    ap.add_argument("--version", nargs="*")
    ap.add_argument("--datos", type=Path, default=RAIZ / "datos" / "ciudades")
    ap.add_argument("--salida", type=Path, default=RAIZ / "salida")
    ap.add_argument("--procesos", type=int, default=5)
    a = ap.parse_args()
    for c in ciudades(a.ciudad):
        vs = a.version or sorted(pd.read_parquet(a.datos / c["id"] / "comercios.parquet", columns=["version"]).version.unique())
        for v in vs:
            t = procesar(c, v, a.datos, a.salida, a.procesos)
            print(f"{c['nombre']} {v}:", json.dumps(t.set_index("grupo").acceso_razon.round(2).to_dict(), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
