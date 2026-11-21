"""Prepara cada ciudad de config/ciudades.toml: polígono, red de calles y comercios
del DENUE (todas las versiones disponibles) ubicados sobre la red.

    python -m emergencia.ciudad --denue DIR_PARQUET --marco 00l.parquet --osm mexico.osm.pbf \
        [--ciudad merida ...] [--salida datos/ciudades]

Sale en <salida>/<ciudad>/:
  limite.parquet     polígono de la localidad urbana (EPSG:6372)
  tramos.parquet     red de calles (ver emergencia.red)
  comercios.parquet  una fila por unidad y versión, con su grupo de giro y su
                     posición sobre la red (tramo, t = metros desde u)
  poblacion.parquet  (con --censo y --marco-estados) población 2020 por manzana,
                     ubicada sobre la red
"""
from __future__ import annotations

import argparse
import csv
import tomllib
import zipfile
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from . import red

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "config"
DIST_MAX_RED = 150.0  # m: comercios más lejos de cualquier calle se descartan


def ciudades(ids: list[str] | None = None) -> list[dict]:
    cs = tomllib.loads((CONFIG / "ciudades.toml").read_text(encoding="utf-8"))["ciudad"]
    return [c for c in cs if not ids or c["id"] in ids]


def giros() -> pd.DataFrame:
    with open(CONFIG / "giros.csv", encoding="utf-8") as f:
        filas = [(r["grupo"], r["nombre"], p) for r in csv.DictReader(f) for p in r["prefijos_scian"].split("|")]
    return pd.DataFrame(filas, columns=["grupo", "nombre", "prefijo"])


def asignar_grupo(scian: pd.Series) -> pd.Series:
    """Grupo de giro por el prefijo SCIAN más largo que coincide; NA si ninguno."""
    tabla = giros().sort_values("prefijo", key=lambda s: s.str.len(), ascending=False)
    out = pd.Series(pd.NA, index=scian.index, dtype="object")
    s = scian.fillna("").astype(str)
    for prefijo, grupo in zip(tabla.prefijo, tabla.grupo):
        m = out.isna() & s.str.startswith(prefijo)
        out[m] = grupo
    return out


def limites(marco: Path, cs: list[dict]) -> gpd.GeoDataFrame:
    claves = [c["cvegeo"] for c in cs]
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    lista = ", ".join(f"'{k}'" for k in claves)
    df = con.execute(
        f"SELECT CVEGEO, NOMGEO, ST_AsWKB(geom) AS wkb FROM read_parquet('{marco.as_posix()}') WHERE CVEGEO IN ({lista})"
    ).df()
    g = gpd.GeoDataFrame(df.drop(columns="wkb"), geometry=shapely.from_wkb(df.wkb.map(bytes)), crs=red.CRS_METRICO)
    faltan = set(claves) - set(g.CVEGEO)
    if faltan:
        raise SystemExit(f"No están en el marco: {faltan}")
    return g


def comercios(denue: Path, poligono, caja) -> pd.DataFrame:
    x0, y0, x1, y1 = caja
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT version, id, scian, per_ocu, tipo_cencom, nom_cencom, fecha_alta, lon, lat
        FROM read_parquet('{denue.as_posix()}/denue_*.parquet', union_by_name=true)
        WHERE lon BETWEEN {x0} AND {x1} AND lat BETWEEN {y0} AND {y1}
    """).df()
    df["grupo"] = asignar_grupo(df.scian)
    df = df[df.grupo.notna()].copy()
    pts = gpd.GeoSeries(gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326").to_crs(red.CRS_METRICO)
    df["x"], df["y"] = pts.x.values, pts.y.values
    shapely.prepare(poligono)
    dentro = shapely.contains_xy(poligono, df.x.values, df.y.values)
    return df[dentro].reset_index(drop=True)


def ubicar(df: pd.DataFrame, tramos: gpd.GeoDataFrame) -> pd.DataFrame:
    """Tramo más cercano y posición t (m desde u) de cada comercio."""
    pts = gpd.GeoDataFrame(df[["x", "y"]], geometry=gpd.points_from_xy(df.x, df.y), crs=red.CRS_METRICO)
    j = gpd.sjoin_nearest(pts, tramos[["tramo", "geometry"]], how="left",
                          max_distance=DIST_MAX_RED, distance_col="dist_red")
    j = j[~j.index.duplicated()]
    df = df.join(j[["tramo", "dist_red"]])
    df = df[df.tramo.notna()].copy()
    df["tramo"] = df.tramo.astype(int)
    geoms = tramos.geometry.values[df.tramo.values]
    df["t"] = shapely.line_locate_point(geoms, shapely.points(df.x.values, df.y.values))
    return df.reset_index(drop=True)


def poblacion(censo: Path, marco_estados: Path, cvegeo_loc: str, poligono, tramos) -> pd.DataFrame:
    """Población 2020 por manzana de la localidad, en el centroide de la manzana y
    ubicada sobre la red. POBTOT confidencial ('*') se toma como 1 (manzanas de 1–2
    habitantes); las manzanas sin dato de censo se descartan."""
    ent = cvegeo_loc[:2]
    zc = next(censo.glob(f"*_{ent}.zip"))
    with zipfile.ZipFile(zc) as z:
        n = next(x for x in z.namelist() if "conjunto_de_datos" in x and x.lower().endswith(".csv"))
        with z.open(n) as f:
            c = pd.read_csv(f, dtype=str, encoding="utf-8-sig", usecols=["ENTIDAD", "MUN", "LOC", "AGEB", "MZA", "POBTOT"])
    c = c[(c.MZA != "000") & (c.ENTIDAD + c.MUN + c.LOC == cvegeo_loc)]
    c["cvegeo"] = c.ENTIDAD + c.MUN + c.LOC + c.AGEB + c.MZA
    c["pob"] = pd.to_numeric(c.POBTOT.replace("*", "1"), errors="coerce").fillna(0)
    zm = next(marco_estados.glob(f"{ent}_*.zip"))
    m = gpd.read_file(f"zip://{zm.as_posix()}!conjunto_de_datos/{ent}m.shp", columns=["CVEGEO"])
    m = m[m.CVEGEO.str.startswith(cvegeo_loc)].to_crs(red.CRS_METRICO)
    m = m.merge(c[["cvegeo", "pob"]], left_on="CVEGEO", right_on="cvegeo")
    m = m[m.pob > 0]
    cen = m.geometry.representative_point()
    df = pd.DataFrame({"cvegeo": m.cvegeo.values, "pob": m.pob.values, "x": cen.x.values, "y": cen.y.values})
    return ubicar(df, tramos)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--denue", type=Path, required=True, help="carpeta con denue_<versión>.parquet")
    ap.add_argument("--marco", type=Path, required=True, help="Marco Geoestadístico, localidades (00l) en Parquet")
    ap.add_argument("--osm", type=Path, required=True, help="extracto PBF de OpenStreetMap")
    ap.add_argument("--censo", type=Path, help="carpeta con ageb_mza_NN.zip (Censo 2020, AGEB y manzana)")
    ap.add_argument("--marco-estados", type=Path, help="carpeta con los ZIP estatales del Marco (NN_*.zip, capa NNm)")
    ap.add_argument("--ciudad", nargs="*")
    ap.add_argument("--salida", type=Path, default=RAIZ / "datos" / "ciudades")
    ap.add_argument("--rehacer-red", action="store_true")
    a = ap.parse_args()

    cs = ciudades(a.ciudad)
    lim = limites(a.marco, cs).set_index("CVEGEO")
    cajas = {}
    for c in cs:
        geo = gpd.GeoSeries([lim.loc[c["cvegeo"], "geometry"].buffer(2000)], crs=red.CRS_METRICO).to_crs("EPSG:4326")
        cajas[c["id"]] = tuple(geo.total_bounds)

    pendientes = [c["id"] for c in cs if a.rehacer_red or not (a.salida / c["id"] / "tramos.parquet").exists()]
    vias = red.extraer(a.osm, {k: cajas[k] for k in pendientes}) if pendientes else {}

    for c in cs:
        d = a.salida / c["id"]
        d.mkdir(parents=True, exist_ok=True)
        poligono = lim.loc[c["cvegeo"], "geometry"]
        gpd.GeoDataFrame({"ciudad": [c["id"]]}, geometry=[poligono], crs=red.CRS_METRICO).to_parquet(d / "limite.parquet")
        if c["id"] in pendientes:
            t = red.recortar(red.tramos(vias.get(c["id"], [])), poligono)
            t.to_parquet(d / "tramos.parquet")
        t = gpd.read_parquet(d / "tramos.parquet")
        df = ubicar(comercios(a.denue, poligono, cajas[c["id"]]), t)
        df.to_parquet(d / "comercios.parquet")
        por_version = df.groupby("version").size().to_dict()
        print(f"{c['nombre']}: {len(t):,} tramos ({t.largo.sum() / 1000:,.0f} km); comercios por versión: {por_version}")
        if a.censo and a.marco_estados:
            p = poblacion(a.censo, a.marco_estados, c["cvegeo"], poligono, t)
            p.to_parquet(d / "poblacion.parquet")
            print(f"  población 2020 en {len(p):,} manzanas: {p.pob.sum():,.0f} habitantes")


if __name__ == "__main__":
    main()
