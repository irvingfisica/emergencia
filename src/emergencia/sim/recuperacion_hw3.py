"""Prueba 1b, tercera ronda: cadena de estructuras con parámetros heredados.

    python -m emergencia.sim.recuperacion_hw3 [--ciudad aguascalientes] [--previo ARCHIVO]

Parte de la mejor regla de la segunda ronda,

    pob500**a * (1+mismo200)**b / (1+mismoR)**c

y la hace crecer paso a paso. Cada estructura arranca desde los parámetros
calibrados de su madre (el término nuevo en su valor neutro), y ese punto compite
en la evaluación final: así una estructura más grande no ajusta peor que la que
contiene, salvo por ruido.

  1. R = 2000 con c hasta 6 (en la segunda ronda c quedó en el tope, 3)
  2. R = 3000 y 3. R = 4000: ¿la competencia va más lejos?
  4. la mejor de 1–3 × exp(v*avenida): ¿cuenta el tipo de vía?
  5. la mejor hasta ahí × (1+otros1000)**e: ¿interacción con otros giros?
"""
from __future__ import annotations

import argparse
import ast
import json

from ..ciudad import RAIZ
from .calibrar import Banco, Escena, a_cubo, calibrar
from .recuperacion_hw import N, SECTORES, objetivo_hw, verdad_hw

RANGOS = {"a": [0, 3], "b": [0, 3], "c": [0, 6], "v": [-2, 3], "e": [-3, 1]}


def _espec(texto: str) -> dict:
    nombres = {n.id for n in ast.walk(ast.parse(texto, mode="eval")) if isinstance(n, ast.Name)}
    params = {k: v for k, v in RANGOS.items() if k in nombres}
    return {g: {"localizacion": texto, "params": params} for g in SECTORES}


def base(R: int) -> str:
    return f"pob500**a * (1+mismo200)**b / (1+mismo{R})**c"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", default="aguascalientes")
    ap.add_argument("--previo", help="JSON de la segunda ronda (punto de partida)")
    ap.add_argument("--arranques", type=int, default=2)
    ap.add_argument("--procesos", type=int)
    ap.add_argument("--rapido", action="store_true")
    a = ap.parse_args()
    destino = RAIZ / "salida" / "fase1"
    previo = a.previo or destino / f"recuperacion_hw_{a.ciudad}_v2.json"
    inicio = json.loads(open(previo, encoding="utf-8").read())["candidatas"]["aglom_comp"]["valores"]
    escena = Escena(a.ciudad, N, pasos=60 if a.rapido else 150)
    it, pob, rep = (2, 6, 4) if a.rapido else (12, 10, 8)
    h, W = verdad_hw(a.ciudad)
    banco = Banco(a.procesos)
    hechos = {}
    archivo = destino / f"recuperacion_hw_{a.ciudad}_v3.json"
    try:
        objetivo, escala, piso = objetivo_hw(banco, a.ciudad, h, W, rep)
        salida = {"piso": piso, "previo": str(previo), "candidatas": {}}

        def correr(nombre, texto, madre_valores, madre_nombre):
            espec = _espec(texto)
            x0 = a_cubo(espec, madre_valores)
            r = calibrar(banco, escena, espec, objetivo, escala, poblacion=pob, iteraciones=it,
                         arranques=a.arranques, x0=x0)
            vals = {g: {k: round(v, 3) for k, v in vs.items()} for g, vs in r.valores.items()}
            d = {k: round(v, 2) for k, v in r.distancia.items()}
            print(f"{nombre:14s} (madre {madre_nombre}) complejidad {r.complejidad:3d}  distancia {d['total']:7.2f}  "
                  f"{d}  {vals}  arranques {[round(t, 1) for _, t in r.arranques]}  "
                  f"({r.evaluaciones} sim, {r.segundos:.0f} s)", flush=True)
            hechos[nombre] = r
            salida["candidatas"][nombre] = {"espec": espec, "madre": madre_nombre, "valores": r.valores,
                                            "distancia": r.distancia, "complejidad": r.complejidad,
                                            "historia": r.historia, "arranques": r.arranques}
            archivo.write_text(json.dumps(salida, indent=1, default=float))
            return r

        correr("comp2000", base(2000), inicio, "aglom_comp (ronda 2)")
        correr("comp3000", base(3000), hechos["comp2000"].valores, "comp2000")
        correr("comp4000", base(4000), hechos["comp3000"].valores, "comp3000")
        mejor_R = min((2000, 3000, 4000), key=lambda R: hechos[f"comp{R}"].distancia["total"])
        madre = f"comp{mejor_R}"
        correr("via", base(mejor_R) + " * exp(v*avenida)", hechos[madre].valores, madre)
        madre = min((madre, "via"), key=lambda n: hechos[n].distancia["total"])
        texto = hechos[madre].espec["eta10"]["localizacion"] + " * (1+otros1000)**e"
        correr("otros", texto, hechos[madre].valores, madre)
    finally:
        banco.cerrar()


if __name__ == "__main__":
    main()
