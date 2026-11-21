"""Estabilidad de los patrones entre versiones y entre ciudades (fase 0).

    python -m emergencia.comparar [--salida salida]

Compara las matrices de Jensen (log M_ab, solo pares significativos en ambas) y las
cifras de centros y corredores. Escribe salida/comparacion.json y lo imprime.
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .ciudad import RAIZ


def matriz(ruta: Path) -> pd.Series:
    j = pd.read_csv(ruta)
    z = (j.M - j.nulo_media) / j.nulo_sd.replace(0, np.nan)
    j = j.assign(logM=np.log2(j.M.replace(0, np.nan)), z=z).set_index(["a", "b"])
    return j


def correlacion(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    comunes = a.index.intersection(b.index)
    a, b = a.loc[comunes], b.loc[comunes]
    ok = np.isfinite(a.logM) & np.isfinite(b.logM)
    sig = ok & (a.z.abs() >= 2) & (b.z.abs() >= 2)
    signo = (np.sign(a.logM[sig]) == np.sign(b.logM[sig])).mean()
    return {"pares": int(ok.sum()), "r_todos": float(np.corrcoef(a.logM[ok], b.logM[ok])[0, 1]),
            "pares_significativos_en_ambas": int(sig.sum()), "mismo_signo": float(signo)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", type=Path, default=RAIZ / "salida")
    ap.add_argument("--r", type=int, default=200)
    a = ap.parse_args()
    casos = {(p.parent.name, p.name): p for p in sorted(a.salida.glob("*/*")) if (p / "resumen.json").exists()}
    M = {k: matriz(p / f"jensen_r{a.r}.csv") for k, p in casos.items()}
    R = {k: json.loads((p / "resumen.json").read_text(encoding="utf-8")) for k, p in casos.items()}
    out = {"entre_versiones": {}, "entre_ciudades": {}, "cifras": {}}
    for (c1, v1), (c2, v2) in itertools.combinations(casos, 2):
        clave = f"{c1}/{v1} vs {c2}/{v2}"
        grupo = "entre_versiones" if c1 == c2 else ("entre_ciudades" if v1 == v2 else None)
        if grupo:
            out[grupo][clave] = correlacion(M[(c1, v1)], M[(c2, v2)])
    for k, r in R.items():
        out["cifras"]["/".join(k)] = {
            "comercios": r["comercios"],
            "centros": r["centros"].get("n"),
            "pendiente_rango_tamano": round(r["centros"].get("pendiente_rango_tamano", float("nan")), 2),
            "fraccion_en_centros": round(r["centros"].get("fraccion_comercios_en_centros", float("nan")), 3),
            "gini_corredores": round(r["corredores"]["gini_por_longitud"], 3),
            "comercios_en_5pct_calle": round(r["corredores"]["fraccion_comercios_en_5pct_de_calle"], 3),
            "calle_sin_comercio": round(r["corredores"]["fraccion_calle_sin_comercio"], 3),
        }
    (a.salida / "comparacion.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
