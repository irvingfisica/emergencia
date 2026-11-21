"""Prueba de recuperación 1b: la verdad es el modelo de lugares centrales (Harris–Wilson).

    python -m emergencia.sim.recuperacion_hw [--ciudad aguascalientes] [--rapido]

Tres sectores independientes con distinto exponente de distancia η, a los dos lados
de la transición (pocos centros grandes ↔ muchos chicos). Su firma de patrones es la
"observación". Después se calibran reglas locales de agentes (las mismas para los
tres sectores, con parámetros propios de cada uno).

Lo que se espera si el método funciona:
  - alguna regla local reproduce la firma casi tan bien como el ruido de la verdad;
  - los parámetros recuperados ordenan a los sectores como η (por ejemplo, menos
    atracción por el propio giro cuanto mayor es η).
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np

from ..ciudad import RAIZ
from .calibrar import Banco, Escena, _lotes, calibrar, dispersion, promedio
from .firmas import distancia, firma
from .harris_wilson import a_comercios, equilibrar, preparar, vivos

SECTORES = {"eta10": 1.0, "eta15": 1.5, "eta25": 2.5}
N = {"eta10": 2150, "eta15": 3347, "eta25": 7121}


def _por_sector(texto, params):
    return {g: {"localizacion": texto, "params": params} for g in SECTORES}


CANDIDATAS = {
    "pob_mismo": _por_sector("pob500**a * (1+mismo200)**b", {"a": [0, 3], "b": [0, 3]}),
    "pob_total": _por_sector("pob500**a * (1+total200)**b", {"a": [0, 3], "b": [0, 3]}),
    "pob_exp": _por_sector("pob500**a * exp(b*mismo200)", {"a": [0, 3], "b": [0, 1]}),
    "mismo": _por_sector("(1+mismo200)**b", {"b": [0, 3]}),
    "pob": _por_sector("pob500**a", {"a": [0, 3]}),
    "nulo": _por_sector("1", {}),
}


def firma_hw(ciudad: str, oferta: np.ndarray, W: dict[str, np.ndarray], semilla: int):
    """Una réplica de la verdad: comercios puestos según los tamaños de equilibrio."""
    L = _lotes(ciudad)
    rng = np.random.default_rng(semilla)
    ocup = np.zeros(L.n, dtype=int)
    lotes, giros = [], []
    for k, g in enumerate(SECTORES):
        l = a_comercios(L, oferta, W[g], N[g], rng, ocup)
        lotes.append(l)
        giros.append(np.full(len(l), k))
    return firma(L, np.concatenate(lotes), np.concatenate(giros), len(SECTORES))


def _tarea_hw(args):
    return firma_hw(*args)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ciudad", default="aguascalientes")
    ap.add_argument("--rapido", action="store_true")
    ap.add_argument("--candidatas", nargs="*")
    ap.add_argument("--procesos", type=int)
    a = ap.parse_args()
    escena = Escena(a.ciudad, N, pasos=60 if a.rapido else 150)
    it, pob, rep = (3, 6, 4) if a.rapido else (12, 10, 8)
    destino = RAIZ / "salida" / "fase1"
    destino.mkdir(parents=True, exist_ok=True)
    h = preparar(a.ciudad)
    rng = np.random.default_rng(0)
    W = {}
    for g, eta in SECTORES.items():
        W[g] = equilibrar(h["P"], h["d"], eta, rng)
        print(f"{g}: η = {eta}, centros vivos {vivos(W[g])}", flush=True)
    banco = Banco(a.procesos)
    try:
        fs = banco.pool.map(_tarea_hw, [(a.ciudad, h["oferta"], W, 10_000 + i) for i in range(rep)])
        objetivo, escala = promedio(fs), dispersion(fs)
        ref = banco.pool.map(_tarea_hw, [(a.ciudad, h["oferta"], W, 20_000 + i) for i in range(8)])
        piso = [distancia(promedio(ref[i:i + 2]), objetivo, escala)["total"] for i in range(0, 8, 2)]
        print(f"piso de ruido: {np.mean(piso):.2f} ± {np.std(piso):.2f}", flush=True)
        salida = {"sectores": SECTORES, "n": N, "pasos": escena.pasos, "piso": piso,
                  "centros_vivos": {g: vivos(w) for g, w in W.items()},
                  "objetivo": {k: v.tolist() for k, v in objetivo.items()}, "candidatas": {}}
        for nombre, espec in CANDIDATAS.items():
            if a.candidatas and nombre not in a.candidatas:
                continue
            r = calibrar(banco, escena, espec, objetivo, escala, poblacion=pob, iteraciones=it)
            d = {k: round(v, 3) for k, v in r.distancia.items()}
            vals = {g: {k: round(v, 3) for k, v in vs.items()} for g, vs in r.valores.items() if vs}
            print(f"{nombre:12s} complejidad {r.complejidad:3d}  distancia {d['total']:7.2f}  {d}  {vals}  "
                  f"({r.evaluaciones} sim, {r.segundos:.0f} s)", flush=True)
            salida["candidatas"][nombre] = {"espec": espec, "valores": r.valores, "distancia": r.distancia,
                                            "complejidad": r.complejidad, "historia": r.historia}
            (destino / f"recuperacion_hw_{a.ciudad}.json").write_text(json.dumps(salida, indent=1, default=float))
    finally:
        banco.cerrar()


if __name__ == "__main__":
    main()
