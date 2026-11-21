"""Red de calles por ciudad desde un extracto PBF de OpenStreetMap.

Una sola pasada sobre el PBF para todas las ciudades: se guardan las vías con
`highway` que tocan el rectángulo de cada ciudad, se parten en intersecciones y
se recortan al polígono de la ciudad con un margen. Sale, por ciudad, un
GeoParquet de tramos (EPSG:6372) con u, v, longitud, tipo de vía y nombre.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path

import geopandas as gpd
import osmium
from shapely.geometry import LineString

CRS_METRICO = "EPSG:6372"

# Vías donde puede haber frentes de comercio. Se excluyen autopistas, caminos
# rurales, veredas y estacionamientos.
VIAS = {
    "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential", "living_street",
    "pedestrian", "road",
}


def _haversine(lon1, lat1, lon2, lat2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def extraer(pbf: Path, cajas: dict[str, tuple[float, float, float, float]]) -> dict[str, list]:
    """Vías por ciudad: {ciudad: [(osm_id, highway, name, [(nodo, lon, lat), ...]), ...]}.
    `cajas` en grados: (lon_min, lat_min, lon_max, lat_max)."""
    vias: dict[str, list] = defaultdict(list)
    fp = (osmium.FileProcessor(str(pbf))
          .with_locations()
          .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
          .with_filter(osmium.filter.KeyFilter("highway")))
    for w in fp:
        hw = w.tags.get("highway")
        if hw not in VIAS:
            continue
        try:
            nodos = [(n.ref, n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            continue
        for c, (x0, y0, x1, y1) in cajas.items():
            if any(x0 <= x <= x1 and y0 <= y <= y1 for _, x, y in nodos):
                vias[c].append((w.id, hw, w.tags.get("name"), nodos))
    return vias


def tramos(vias: list) -> gpd.GeoDataFrame:
    """Parte las vías en intersecciones: un tramo por par de nodos de grado != 2."""
    uso = Counter()
    for _, _, _, nodos in vias:
        for i, (ref, _, _) in enumerate(nodos):
            uso[ref] += 2 if i in (0, len(nodos) - 1) else 1
    filas = []
    for osm_id, hw, nombre, nodos in vias:
        inicio = 0
        for i in range(1, len(nodos)):
            if uso[nodos[i][0]] > 1 or i == len(nodos) - 1:
                seg = nodos[inicio:i + 1]
                if len(seg) >= 2 and seg[0][0] != seg[-1][0]:
                    largo = sum(_haversine(a[1], a[2], b[1], b[2]) for a, b in zip(seg, seg[1:]))
                    filas.append({"u": seg[0][0], "v": seg[-1][0], "largo": largo, "highway": hw,
                                  "nombre": nombre, "osm_id": osm_id,
                                  "geometry": LineString([(x, y) for _, x, y in seg])})
                inicio = i
    g = gpd.GeoDataFrame(filas, geometry="geometry", crs="EPSG:4326").to_crs(CRS_METRICO)
    g["largo"] = g.geometry.length  # en metros, en la proyección
    return g


def recortar(g: gpd.GeoDataFrame, poligono, margen: float = 1000.0) -> gpd.GeoDataFrame:
    """Tramos que tocan el polígono de la ciudad con un margen (m), y solo la
    componente conexa más grande."""
    import networkx as nx

    g = g[g.intersects(poligono.buffer(margen))].copy()
    G = nx.Graph()
    G.add_edges_from(zip(g.u, g.v))
    mayor = max(nx.connected_components(G), key=len)
    g = g[g.u.isin(mayor)].reset_index(drop=True)
    g["tramo"] = range(len(g))
    return g
