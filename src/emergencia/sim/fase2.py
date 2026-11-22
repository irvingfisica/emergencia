"""Fase 2, primer paso: la familia de reglas de la fase 1 contra el DENUE real.

    python -m emergencia.sim.fase2 [--ciudad aguascalientes] [--version 2026_05]

Antes de automatizar la búsqueda de estructuras, se calibra a mano una cadena de
estructuras anidadas sobre los datos reales (modo génesis). Cada una hereda los
parámetros de la anterior con el término nuevo en su valor neutro:

  nulo → pob500**a → × (1+mismo200)**b → ÷ (1+mismo2000)**c → × exp(v*avenida)
       → × (1+otros200)**e

La estructura es la misma para todos los giros; los parámetros, propios de cada uno.
Aquí b y e pueden ser negativos (repulsión), porque en los datos reales hay giros que
se evitan.

No hay réplicas de la "verdad", así que la escala de cada patrón es la dispersión
entre réplicas de un modelo de referencia (REFERENCIA): mide cuánto varía un patrón
por puro azar de la simulación. Lo que se reporta es la distancia por grupo de
patrones y la complejidad: el primer frente de Pareto con datos reales.
"""
from __future__ import annotations

import argparse
import ast
import json

import numpy as np

from ..ciudad import RAIZ
from .calibrar import Banco, Escena, a_cubo, calibrar, dispersion
from .firmas import distancia
from .observado import observado

GIROS = ["abarrotes", "ropa", "restaurantes"]
RANGOS = {"a": [0, 3], "b": [-2, 3], "c": [0, 6], "v": [-2, 3], "e": [-3, 3]}
REFERENCIA = ("pob500**a * (1+mismo200)**b", {"a": 1.0, "b": 0.5})
CADENA = [
    ("nulo", "1"),
    ("pob", "pob500**a"),
    ("pob_mismo", "pob500**a * (1+mismo200)**b"),
    ("competencia", "pob500**a * (1+mismo200)**b / (1+mismo2000)**c"),
    ("via", "pob500**a * (1+mismo200)**b / (1+mismo2000)**c * exp(v*avenida)"),
    ("otros", "pob500**a * (1+mismo200)**b / (1+mismo2000)**c * exp(v*avenida) * (1+otros200)**e"),
]


def espec(texto: str, giros: list[str]) -> dict:
    nombres = {n.id for n in ast.walk(ast.parse(texto, mode="eval")) if isinstance(n, ast.Name)}
    return {g: {"localizacion": texto, "params": {k: v for k, v in RANGOS.items() if k in nombres}} for g in giros}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", default="aguascalientes")
    ap.add_argument("--version", default="2026_05")
    ap.add_argument("--giros", nargs="*", default=GIROS)
    ap.add_argument("--arranques", type=int, default=2)
    ap.add_argument("--procesos", type=int)
    ap.add_argument("--rapido", action="store_true")
    a = ap.parse_args()
    obs = observado(a.ciudad, a.version, a.giros)
    objetivo = obs["firma"]
    escena = Escena(a.ciudad, obs["n"], pasos=60 if a.rapido else 150)
    it, pob = (2, 6) if a.rapido else (12, 10)
    destino = RAIZ / "salida" / "fase2"
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / f"familia_{a.ciudad}_{a.version}.json"
    banco = Banco(a.procesos)
    try:
        texto, vals = REFERENCIA
        ref = banco.firmas([(escena, espec(texto, a.giros), {g: vals for g in a.giros}, 30_000 + i)
                            for i in range(8)])
        escala = dispersion(ref)
        salida = {"ciudad": a.ciudad, "version": a.version, "n": obs["n"], "referencia": REFERENCIA,
                  "objetivo": {k: v.tolist() for k, v in objetivo.items()},
                  "escala": {k: v.tolist() for k, v in escala.items()}, "candidatas": {}}
        previo = {}
        for nombre, texto in CADENA:
            e = espec(texto, a.giros)
            x0 = a_cubo(e, previo) if previo and any(e[g]["params"] for g in e) else None
            r = calibrar(banco, escena, e, objetivo, escala, poblacion=pob, iteraciones=it,
                         arranques=a.arranques, x0=x0)
            vals = {g: {k: round(v, 3) for k, v in vs.items()} for g, vs in r.valores.items() if vs}
            d = {k: round(v, 2) for k, v in r.distancia.items()}
            print(f"{nombre:12s} complejidad {r.complejidad:3d}  distancia {d['total']:8.2f}  {d}  {vals}  "
                  f"arranques {[round(t, 1) for _, t in r.arranques]}  ({r.evaluaciones} sim, {r.segundos:.0f} s)",
                  flush=True)
            salida["candidatas"][nombre] = {"espec": e, "valores": r.valores, "distancia": r.distancia,
                                            "complejidad": r.complejidad, "historia": r.historia,
                                            "arranques": r.arranques}
            archivo.write_text(json.dumps(salida, indent=1, default=float))
            previo = r.valores
    finally:
        banco.cerrar()


if __name__ == "__main__":
    main()
