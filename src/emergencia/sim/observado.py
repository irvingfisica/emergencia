"""Lo observado: comercios reales del DENUE ubicados en los lotes del simulador.

    python -m emergencia.sim.observado [--ciudad aguascalientes] [--version 2026_05]

Decisiones (ver docs/fase2.md):

- Se dejan fuera los comercios dentro de centros y plazas comerciales, mercados y
  otros conglomerados (`tipo_cencom` no vacío). Su ubicación la decide quien
  construye el conglomerado, no cada comercio, y el simulador no tiene lotes con
  capacidad para decenas de locales. Son el 9 % de los giros usados.
- Cada comercio va al lote más cercano de su tramo. Si un lote queda con más de
  CAPACIDAD comercios, el exceso pasa al lote libre más cercano sobre la red
  (normalmente el de al lado, a 25 m). Afecta a cerca del 6 % de los comercios.

La salida es lo mismo que produce el simulador (lote y giro de cada comercio), así
que la firma de lo observado y la de lo simulado se calculan con la misma función.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from ..ciudad import RAIZ
from .firmas import firma
from .lotes import CAPACIDAD, Lotes


def comercios(L: Lotes, ciudad: str, version: str, giros: list[str],
              conglomerados: bool = False) -> tuple[np.ndarray, np.ndarray]:
    c = pd.read_parquet(RAIZ / "datos" / "ciudades" / ciudad / "comercios.parquet",
                        columns=["version", "grupo", "tramo", "t", "tipo_cencom"])
    c = c[(c.version == version) & c.grupo.isin(giros) & c.tramo.isin(L.tabla.tramo)]
    if not conglomerados:
        c = c[c.tipo_cencom.isna()]
    lote = L.ubicar(c.tramo.to_numpy(), c.t.to_numpy())
    giro = pd.Categorical(c.grupo, categories=giros).codes.astype(int)
    return _capacidad(L, lote), giro


def _capacidad(L: Lotes, lote: np.ndarray, capacidad: int = CAPACIDAD) -> np.ndarray:
    """Mueve el exceso de cada lote lleno al lote libre más cercano a <= 200 m
    (si no hay, se queda donde está)."""
    lote = lote.copy()
    ocup = np.bincount(lote, minlength=L.n)
    D = L.D
    for l in np.flatnonzero(ocup > capacidad):
        quienes = np.flatnonzero(lote == l)[capacidad:]
        vec = D.indices[D.indptr[l]:D.indptr[l + 1]]
        dist = D.data[D.indptr[l]:D.indptr[l + 1]]
        for i in quienes:
            libres = vec[ocup[vec] < capacidad]
            if len(libres) == 0:
                break
            dest = libres[np.argmin(dist[ocup[vec] < capacidad])]
            lote[i] = dest
            ocup[dest] += 1
            ocup[l] -= 1
    return lote


def observado(ciudad: str, version: str, giros: list[str]) -> dict:
    """Firma observada y número de comercios de cada giro."""
    from .calibrar import _lotes
    L = _lotes(ciudad)
    lote, giro = comercios(L, ciudad, version, giros)
    n = {g: int((giro == k).sum()) for k, g in enumerate(giros)}
    return {"firma": firma(L, lote, giro, len(giros)), "n": n, "lote": lote, "giro": giro}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", default="aguascalientes")
    ap.add_argument("--version", default="2026_05")
    ap.add_argument("--giros", nargs="*", default=["abarrotes", "ropa", "restaurantes"])
    a = ap.parse_args()
    o = observado(a.ciudad, a.version, a.giros)
    print(o["n"], f"más de {CAPACIDAD} por lote: {(np.bincount(o['lote'])[o['lote']] > CAPACIDAD).mean():.3f}")
    for k, v in o["firma"].items():
        print(f"{k:11s}", np.round(v, 2))


if __name__ == "__main__":
    main()
