"""Prueba de recuperación 1a: la verdad es una regla del propio DSL.

    python -m emergencia.sim.recuperacion [--ciudad aguascalientes] [--rapido]

1. Se simula la regla verdadera (VERDAD, VALORES) varias veces sobre la red real y se
   toma su firma de patrones como "observación" (media y dispersión entre réplicas).
2. Se calibran varias estructuras candidatas (la verdadera, versiones con un término
   de menos, con uno de más, con una forma equivocada y el nulo) contra esa firma.
3. Se reporta el ajuste, la complejidad y los parámetros recuperados.

Si el método funciona: la estructura verdadera queda en el frente de Pareto (ajuste ×
complejidad), sus parámetros se acercan a los verdaderos, y las estructuras con un
término de menos ajustan peor.
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np

from ..ciudad import RAIZ
from .calibrar import Banco, Escena, calibrar, dispersion, promedio

GIROS_N = {"abarrotes": 3347, "ropa": 2150, "restaurantes": 7121}   # Aguascalientes 2026

ABARROTES = {"localizacion": "pob500**a", "params": {"a": [0, 3]}}
RESTAURANTES = {"localizacion": "(1+total200)**d", "params": {"d": [0, 3]}}
ROPA = {"localizacion": "(1+mismo200)**b * exp(c*avenida)", "params": {"b": [0, 3], "c": [0, 3]}}
VERDAD = {"abarrotes": ABARROTES, "ropa": ROPA, "restaurantes": RESTAURANTES}
VALORES = {"abarrotes": {"a": 1.0}, "ropa": {"b": 1.5, "c": 1.0}, "restaurantes": {"d": 0.5}}

UNO = {"localizacion": "1"}
CANDIDATAS = {
    "verdad": VERDAD,
    "ropa_sin_avenida": {**VERDAD, "ropa": {"localizacion": "(1+mismo200)**b", "params": {"b": [0, 3]}}},
    "ropa_sin_atraccion": {**VERDAD, "ropa": {"localizacion": "exp(c*avenida)", "params": {"c": [0, 3]}}},
    "abarrotes_sin_poblacion": {**VERDAD, "abarrotes": UNO},
    "abarrotes_con_atraccion": {**VERDAD, "abarrotes": {"localizacion": "pob500**a * (1+mismo200)**e",
                                                       "params": {"a": [0, 3], "e": [-2, 2]}}},
    "ropa_exponencial": {**VERDAD, "ropa": {"localizacion": "exp(b*mismo200 + c*avenida)",
                                           "params": {"b": [0, 0.5], "c": [0, 3]}}},
    "nulo": {g: UNO for g in GIROS_N},
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", default="aguascalientes")
    ap.add_argument("--rapido", action="store_true", help="menos pasos e iteraciones, para probar")
    ap.add_argument("--candidatas", nargs="*")
    ap.add_argument("--procesos", type=int)
    ap.add_argument("--arranques", type=int, default=1, help="CMA-ES en paralelo desde puntos distintos")
    ap.add_argument("--etiqueta", default="", help="sufijo del archivo de salida")
    a = ap.parse_args()
    escena = Escena(a.ciudad, GIROS_N, pasos=60 if a.rapido else 150)
    it, pob, rep_verdad = (3, 6, 4) if a.rapido else (12, 10, 8)
    destino = RAIZ / "salida" / "fase1"
    destino.mkdir(parents=True, exist_ok=True)
    banco = Banco(a.procesos)
    try:
        t0 = time.time()
        fs = banco.firmas([(escena, VERDAD, VALORES, 10_000 + i) for i in range(rep_verdad)])
        objetivo, escala = promedio(fs), dispersion(fs)
        print(f"verdad: {rep_verdad} réplicas en {time.time() - t0:.0f} s", flush=True)
        # Piso de ruido: la regla verdadera con sus parámetros y semillas nuevas.
        from .firmas import distancia
        ref = banco.firmas([(escena, VERDAD, VALORES, 20_000 + i) for i in range(2 * 4)])
        piso = [distancia(promedio(ref[i:i + 2]), objetivo, escala)["total"] for i in range(0, 8, 2)]
        print(f"piso de ruido (verdad con semillas nuevas, 2 réplicas): {np.mean(piso):.2f} ± {np.std(piso):.2f}",
              flush=True)
        salida = {"verdad": VERDAD, "valores": VALORES, "n": GIROS_N, "pasos": escena.pasos,
                  "piso": piso, "candidatas": {}}
        for nombre, espec in CANDIDATAS.items():
            if a.candidatas and nombre not in a.candidatas:
                continue
            r = calibrar(banco, escena, espec, objetivo, escala, poblacion=pob, iteraciones=it,
                         arranques=a.arranques)
            d = {k: round(v, 3) for k, v in r.distancia.items()}
            vals = {g: {k: round(v, 3) for k, v in vs.items()} for g, vs in r.valores.items() if vs}
            print(f"{nombre:26s} complejidad {r.complejidad:3d}  distancia {d['total']:7.2f}  {d}  {vals}  "
                  f"({r.evaluaciones} sim, {r.segundos:.0f} s)", flush=True)
            salida["candidatas"][nombre] = {"espec": espec, "valores": r.valores, "distancia": r.distancia,
                                            "complejidad": r.complejidad, "historia": r.historia,
                                            "arranques": r.arranques}
            (destino / f"recuperacion_dsl_{a.ciudad}{'_' + a.etiqueta if a.etiqueta else ''}.json").write_text(json.dumps(salida, indent=1, default=float))
    finally:
        banco.cerrar()


if __name__ == "__main__":
    main()
