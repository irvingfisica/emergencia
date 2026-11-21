"""Figura de la serie completa (docs/img/fase0_serie.png).

    uv run python scripts/figura_serie.py

Requiere haber corrido emergencia.dinamica y emergencia.demanda sobre todas las versiones.
Las líneas verticales marcan las versiones que incorporan un Censo Económico (2019_11, 2024_11).
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

RAIZ = Path(__file__).resolve().parents[1]
S = RAIZ / "salida"
C = {"aguascalientes": "Aguascalientes", "merida": "Mérida", "hermosillo": "Hermosillo"}
COL = {"aguascalientes": "#1b9e77", "merida": "#d95f02", "hermosillo": "#7570b3"}
G = {"ropa": "-", "calzado": "--", "abarrotes": ":", "tortillerias": "-."}
CENSALES = ("2019_11", "2024_11")

fig, ax = plt.subplots(1, 2, figsize=(12, 4.6), dpi=150)
for c, n in C.items():
    s = pd.read_csv(S / c / "dinamica" / "serie.csv")
    x = np.arange(len(s))
    vs = s.version.tolist()
    ax[0].plot(x, s.bajas / s.comercios.shift(), marker="o", ms=3, color=COL[c], label=n)
    for g, ls in G.items():
        r = [pd.read_csv(S / c / v / "demanda.csv").set_index("grupo").acceso_razon.get(g, np.nan) for v in vs]
        ax[1].plot(x, r, ls=ls, color=COL[c], lw=1.3)
for a in ax:
    for v in CENSALES:
        a.axvline(vs.index(v), color="#999", lw=0.8, zorder=0)
    a.set_xticks(x, vs, rotation=70, fontsize=6.5)
ax[0].set_title("Fracción de comercios que desaparece respecto a la versión anterior", fontsize=9)
ax[0].legend(fontsize=7, frameon=False)
ax[1].axhline(1, color="#333", lw=0.6)
ax[1].set_title("Acceso a la población (razón contra azar; >1 = se concentra)", fontsize=9)
ax[1].legend([Line2D([], [], color="#333", ls=l) for l in G.values()], list(G), fontsize=7, frameon=False, ncol=2)
fig.tight_layout()
fig.savefig(RAIZ / "docs" / "img" / "fase0_serie.png")
