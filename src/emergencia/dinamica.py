"""P5: dinámica entre versiones del DENUE (altas, bajas y dónde ocurren).

    python -m emergencia.dinamica [--ciudad ...] [--pares 2015:2020_11 2020_11:2025_05]

Sin --pares usa todas las versiones consecutivas. Se sigue cada unidad por su `id`.
Para cada par (v1 -> v2) y grupo de giro, en salida/<ciudad>/dinamica/<v1>__<v2>.csv:

  existentes, altas, bajas, supervivencia     conteos y fracción de v1 que sigue en v2
  cambian_giro, se_mueven                     sobrevivientes con otro grupo o a > 50 m
  altas_mismo_giro_razon   comercios del mismo grupo (de v1) a <= 200 m de las altas,
                           entre lo mismo para puntos al azar de la calle
  existentes_mismo_giro_razon  lo mismo para los comercios de v1 (sin contarse): si las
                           altas se agrupan más o menos que lo que ya había
  altas_total_razon        igual que altas_mismo_giro_razon, con todos los comercios
  baja_por_competencia     tasa de baja según el número de comercios del mismo grupo a
                           <= 200 m (sin contarse): ninguno / 1–2 / 3 o más

Y salida/<ciudad>/dinamica/serie.csv con los totales por versión y por par.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import sparse

from .ciudad import RAIZ, ciudades, giros
from .demanda import puntos_azar
from .patrones import dentro, distancias, red_de_sitios

R_DINAMICA = 200.0
MOVIMIENTO_M = 50.0
N_AZAR = 6000


def procesar_par(tramos, com, v1, v2, procesos, rng) -> pd.DataFrame:
    a = com[com.version == v1].drop_duplicates("id")
    b = com[com.version == v2].drop_duplicates("id")
    sigue = a.merge(b[["id", "grupo", "x", "y"]], on="id", suffixes=("", "_2"))
    altas = b[~b.id.isin(a.id)]
    baja = ~a.id.isin(b.id)
    az = puntos_azar(tramos, N_AZAR, rng)
    pts = pd.concat([a[["tramo", "t", "grupo"]].assign(clase="v1", baja=baja.values),
                     altas[["tramo", "t", "grupo"]].assign(clase="alta"),
                     az.assign(clase="azar")], ignore_index=True)
    pts["baja"] = pts.baja.fillna(False).astype(bool)
    G, pts, sitios = red_de_sitios(tramos, pts)
    W = dentro(distancias(G, len(sitios), R_DINAMICA, procesos), R_DINAMICA)
    nombres = [g for g in giros().grupo.unique() if g in set(pts.grupo.dropna())]
    k = {g: i for i, g in enumerate(nombres)}
    v1 = pts[pts.clase == "v1"]
    X = sparse.csr_matrix((np.ones(len(v1)), (v1.sitio, v1.grupo.map(k))), shape=(len(sitios), len(nombres)))
    C = np.asarray((W @ X).todense())
    tot = C.sum(1)
    sa = pts[pts.clase == "azar"].sitio.values
    filas = []
    for g in nombres:
        i = k[g]
        e = v1[v1.grupo == g]
        al = pts[(pts.clase == "alta") & (pts.grupo == g)]
        s = sigue[sigue.grupo == g]
        mismo = C[e.sitio.values, i] - 1  # vecinos del mismo grupo sin contarse
        tasas = {}
        for nombre, m in (("0", mismo == 0), ("1-2", (mismo >= 1) & (mismo <= 2)), ("3+", mismo >= 3)):
            tasas[f"baja_vecinos_{nombre}"] = float(e.baja.values[m].mean()) if m.sum() >= 10 else np.nan
            tasas[f"n_vecinos_{nombre}"] = int(m.sum())
        filas.append({
            "grupo": g, "existentes": len(e), "altas": len(al), "bajas": int(e.baja.sum()),
            "supervivencia": 1 - float(e.baja.mean()) if len(e) else np.nan,
            "cambian_giro": int((s.grupo_2 != g).sum()),
            "se_mueven": int((np.hypot(s.x - s.x_2, s.y - s.y_2) > MOVIMIENTO_M).sum()),
            "altas_mismo_giro_razon": C[al.sitio.values, i].mean() / C[sa, i].mean() if len(al) and C[sa, i].mean() > 0 else np.nan,
            "existentes_mismo_giro_razon": mismo.mean() / C[sa, i].mean() if C[sa, i].mean() > 0 else np.nan,
            "altas_total_razon": tot[al.sitio.values].mean() / tot[sa].mean() if len(al) else np.nan,
            **tasas,
        })
    return pd.DataFrame(filas)


def serie(com: pd.DataFrame, versiones: list[str]) -> pd.DataFrame:
    filas = []
    prev = None
    for v in versiones:
        ids = set(com.loc[com.version == v, "id"])
        fila = {"version": v, "comercios": len(ids)}
        if prev is not None:
            fila["altas"] = len(ids - prev)
            fila["bajas"] = len(prev - ids)
        filas.append(fila)
        prev = ids
    return pd.DataFrame(filas)


def figura_serie(s: pd.DataFrame, nombre: str, destino: Path):
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    x = np.arange(len(s))
    ax.plot(x, s.comercios, color="#333333", marker="o", label="comercios")
    ax.bar(x - 0.2, s.altas.fillna(0), width=0.4, color="#1b7837", label="altas desde la versión anterior")
    ax.bar(x + 0.2, s.bajas.fillna(0), width=0.4, color="#b2182b", label="bajas desde la versión anterior")
    ax.set_xticks(x, s.version, rotation=60, fontsize=7)
    ax.set_title(f"{nombre}: comercios en el DENUE por versión", fontsize=10)
    ax.legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(destino / "serie.png")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", nargs="*")
    ap.add_argument("--pares", nargs="*", help="pares v1:v2; por defecto, versiones consecutivas")
    ap.add_argument("--datos", type=Path, default=RAIZ / "datos" / "ciudades")
    ap.add_argument("--salida", type=Path, default=RAIZ / "salida")
    ap.add_argument("--procesos", type=int, default=5)
    a = ap.parse_args()
    rng = np.random.default_rng(0)
    for c in ciudades(a.ciudad):
        tramos = gpd.read_parquet(a.datos / c["id"] / "tramos.parquet")
        com = pd.read_parquet(a.datos / c["id"] / "comercios.parquet")
        vs = sorted(com.version.unique())
        destino = a.salida / c["id"] / "dinamica"
        destino.mkdir(parents=True, exist_ok=True)
        s = serie(com, vs)
        s.to_csv(destino / "serie.csv", index=False)
        figura_serie(s, c["nombre"], destino)
        pares = [tuple(p.split(":")) for p in a.pares] if a.pares else list(zip(vs, vs[1:]))
        for v1, v2 in pares:
            t = procesar_par(tramos, com, v1, v2, a.procesos, rng)
            t.round(3).to_csv(destino / f"{v1}__{v2}.csv", index=False)
            print(f"{c['nombre']} {v1}->{v2}: altas {t.altas.sum():,}, bajas {t.bajas.sum():,}, "
                  f"supervivencia {1 - t.bajas.sum() / t.existentes.sum():.2f}", flush=True)


if __name__ == "__main__":
    main()
