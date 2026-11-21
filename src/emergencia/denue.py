"""Prepara versiones del DENUE (descarga masiva nacional del INEGI, CSV en ZIP).

Cada versión es una carpeta con los ZIP de esa fecha (p. ej. ``2019_11/``). Sale un
Parquet por versión, con columnas normalizadas y en UTF-8:

    python -m emergencia.denue --entrada DIR [DIR ...] --salida DIR_SALIDA [--version 2015 ...]

``--entrada`` puede ser una carpeta de versiones (con subcarpetas) o una carpeta
que ya es una versión (con los ZIP dentro); en ese caso el nombre de la versión
se toma de ``--nombre`` o de la carpeta.
"""
from __future__ import annotations

import argparse
import codecs
import csv
import re
import shutil
import tempfile
import unicodedata
import zipfile
from pathlib import Path

import duckdb

# columna de salida -> nombres posibles en las distintas versiones, ya normalizados
# con _norm (sin acentos, minúsculas, _). La versión 2015 usa nombres descriptivos.
COLUMNAS = {
    "id": ["id"],
    "clee": ["clee"],
    "nom_estab": ["nom_estab", "nombre_de_la_unidad_economica"],
    "scian": ["codigo_act", "codigo_de_la_clase_de_actividad_scian"],
    "per_ocu": ["per_ocu", "descripcion_estrato_personal_ocupado"],
    "cve_ent": ["cve_ent", "clave_entidad"],
    "cve_mun": ["cve_mun", "clave_municipio"],
    "cve_loc": ["cve_loc", "clave_localidad"],
    "ageb": ["ageb", "area_geoestadistica_basica"],
    "manzana": ["manzana"],
    "tipo_vial": ["tipo_vial", "tipo_de_vialidad"],
    "nom_vial": ["nom_vial", "nombre_de_la_vialidad"],
    "tipo_cencom": ["tipocencom", "tipo_centro_comercial"],
    "nom_cencom": ["nom_cencom", "corredor_industrial_centro_comercial_o_mercado_publico"],
    "tipo_uni": ["tipounieco", "tipo_de_establecimiento"],
    "lat": ["latitud"],
    "lon": ["longitud"],
    "fecha_alta": ["fecha_alta", "fecha_de_incorporacion_al_denue"],
}

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
         "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


def _norm(nombre: str) -> str:
    s = unicodedata.normalize("NFKD", nombre.strip().lstrip("﻿")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _fecha(col: str) -> str:
    """'2019-11' se deja; 'JULIO 2010' (versión 2015) pasa a '2010-07'."""
    casos = " ".join(f"WHEN '{m}' THEN '{i + 1:02d}'" for i, m in enumerate(MESES))
    return (f"CASE WHEN regexp_matches(trim({col}), '^\\d{{4}}-\\d{{2}}') THEN left(trim({col}), 7) "
            f"WHEN regexp_matches(upper(trim({col})), '^[A-Z]+ \\d{{4}}$') THEN "
            f"split_part(trim({col}), ' ', 2) || '-' || (CASE upper(split_part(trim({col}), ' ', 1)) {casos} END) "
            f"ELSE NULLIF(trim({col}), '') END")


def _codificacion(f: Path) -> str:
    dec = codecs.getincrementaldecoder("utf-8")()
    try:
        with open(f, "rb") as fh:
            while trozo := fh.read(1 << 20):
                dec.decode(trozo)
            dec.decode(b"", final=True)
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def _a_utf8(f: Path) -> Path:
    """Devuelve una copia en UTF-8 si hace falta (DuckDB solo lee bien UTF-8)."""
    cod = _codificacion(f)
    if cod == "utf-8":
        return f
    g = f.with_suffix(".utf8.csv")
    with open(f, encoding=cod, errors="replace", newline="") as a, open(g, "w", encoding="utf-8", newline="") as b:
        shutil.copyfileobj(a, b, 1 << 22)
    f.unlink()
    return g


def _reparar_encabezado(f: Path) -> None:
    """Algunos CSV (2016_01) traen el encabezado y el primer registro en la misma línea
    ('...,"fecha_alta"6281881",...'). Si la primera línea tiene más campos que la segunda,
    se separan y se reescribe el archivo."""
    with open(f, encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        h, segunda = next(r, None), next(r, None)
    if not h or not segunda or len(h) <= len(segunda):
        return
    n = len(segunda)
    nombres, resto = h[:n], h[n:]
    nombre, _, pegado = nombres[-1].partition('"')
    nombres[-1] = nombre
    primero = [pegado] + resto if pegado else resto
    g = f.with_suffix(".rep.csv")
    with open(f, encoding="utf-8-sig", newline="") as a, open(g, "w", encoding="utf-8", newline="") as b:
        a.readline()  # la línea fusionada (sin saltos de línea entre comillas)
        w = csv.writer(b, quoting=csv.QUOTE_ALL, lineterminator="\n")
        w.writerow(nombres)
        if len(primero) == n:
            w.writerow(primero)
        shutil.copyfileobj(a, b, 1 << 22)
    g.replace(f)
    print(f"  {f.name}: encabezado pegado al primer registro; separado"
          + ("" if len(primero) == n else " (primer registro descartado)"), flush=True)


def _select(con: duckdb.DuckDBPyConnection, archivo: Path, version: str) -> str:
    lector = f"read_csv('{archivo.as_posix()}', all_varchar=true, header=true, quote='\"')"
    originales = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {lector}").fetchall()]
    por_norm = {_norm(c): c for c in originales}
    partes = []
    for salida, posibles in COLUMNAS.items():
        orig = next((por_norm[c] for c in posibles if c in por_norm), None)
        col = '"' + orig.replace('"', '""') + '"' if orig else None
        if col is None:
            expr = "NULL"
        elif salida in ("lat", "lon"):
            expr = f"TRY_CAST(replace({col}, ',', '.') AS DOUBLE)"
        elif salida == "id":
            expr = f"TRY_CAST({col} AS BIGINT)"
        elif salida == "fecha_alta":
            expr = _fecha(col)
        else:
            expr = f"NULLIF(trim({col}), '')"
        partes.append(f"{expr} AS {salida}")
    return f"SELECT '{version}' AS version, {', '.join(partes)} FROM {lector}"


def preparar_version(zips: list[Path], version: str, salida: Path, tmp_base: Path | None = None) -> Path:
    destino = salida / f"denue_{version}.parquet"
    if destino.exists():
        print(f"{version}: ya existe {destino.name}")
        return destino
    con = duckdb.connect()
    tmp = Path(tempfile.mkdtemp(dir=tmp_base))
    try:
        partes = []
        for zp in sorted(zips):
            with zipfile.ZipFile(zp) as z:
                for n in z.namelist():
                    nl = n.lower()
                    if not nl.endswith(".csv") or "diccionario" in nl or "metadato" in nl:
                        continue
                    archivo = _a_utf8(Path(z.extract(n, tmp)))
                    _reparar_encabezado(archivo)
                    p = tmp / f"parte_{len(partes):03d}.parquet"
                    con.execute(f"COPY ({_select(con, archivo, version)}) TO '{p.as_posix()}' (FORMAT parquet)")
                    archivo.unlink()
                    partes.append(p)
        con.execute(
            f"COPY (SELECT * FROM read_parquet('{tmp.as_posix()}/parte_*.parquet') ORDER BY cve_ent, cve_mun, id) "
            f"TO '{destino.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n, nid, sin_coord = con.execute(
        f"SELECT count(*), count(DISTINCT id), count(*) FILTER (WHERE lat IS NULL OR lon IS NULL) FROM '{destino.as_posix()}'"
    ).fetchone()
    print(f"{version}: {n:,} unidades, {nid:,} ids distintos, {sin_coord:,} sin coordenadas")
    return destino


def versiones(entradas: list[Path], nombre: str | None = None) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for e in entradas:
        zips_aqui = sorted(e.glob("*.zip"))
        if zips_aqui:
            out[nombre or e.name] = zips_aqui
            continue
        for d in sorted(p for p in e.iterdir() if p.is_dir()):
            z = sorted(d.glob("*.zip"))
            if z:
                out[d.name] = z
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", nargs="+", type=Path, required=True)
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--nombre", help="nombre de versión si --entrada es una sola versión")
    ap.add_argument("--version", nargs="*", help="solo estas versiones")
    ap.add_argument("--tmp", type=Path, help="carpeta para temporales (por defecto, la del sistema)")
    a = ap.parse_args()
    a.salida.mkdir(parents=True, exist_ok=True)
    for v, zips in versiones(a.entrada, a.nombre).items():
        if a.version and v not in a.version:
            continue
        preparar_version(zips, v, a.salida, a.tmp)


if __name__ == "__main__":
    main()
