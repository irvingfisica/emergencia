# Datos

Los datos no van en git. El código los busca en `datos/` (o en la ruta que se le
pase). Todos son públicos y se pueden reconstruir con los scripts de este repo.

| Conjunto | Fuente | Cómo se obtiene | Qué sale |
|---|---|---|---|
| DENUE, versiones nacionales 2015–2026 | [INEGI, descarga masiva](https://www.inegi.org.mx/app/descarga/?ti=6) | `DESTINO=datos/denue/raw ./scripts/descargar_denue.sh` | ZIP por sector y versión |
| DENUE preparado | Lo anterior | `uv run python -m emergencia.denue --entrada datos/denue/raw --salida datos/denue` | `denue_<versión>.parquet`: un archivo por versión, columnas normalizadas, UTF-8 |
| Red de calles | OpenStreetMap, extracto de México ([Geofabrik](https://download.geofabrik.de/north-america/mexico.html)) | Descarga del `.osm.pbf` | Grafo de calles por ciudad (fase 0) |
| Población por manzana | INEGI, Censo 2020, resultados por AGEB y manzana urbana | Descarga por entidad | Demanda asignada a la red (fase 0) |
| Marco Geoestadístico | INEGI | Descarga | Límites de localidades y manzanas |

## Ciudades

`uv run python -m emergencia.ciudad --denue datos/denue --marco <localidades 00l.parquet> --osm <mexico.osm.pbf>`
prepara cada ciudad de [config/ciudades.toml](config/ciudades.toml) en `datos/ciudades/<ciudad>/`:
polígono de la localidad urbana, red de calles (`tramos.parquet`, EPSG:6372) y comercios de
todas las versiones del DENUE con su grupo de giro ([config/giros.csv](config/giros.csv)) y su
posición sobre la red. El Marco Geoestadístico se usa convertido a Parquet (capa `00l`).

## DENUE preparado

Una fila por unidad económica y versión. Columnas:

| Columna | Qué es |
|---|---|
| `version` | Versión del DENUE (`2015`, `2016_01`, … `2025_05`, `2026_05`) |
| `id` | Identificador del INEGI. Permite seguir una unidad entre versiones (por verificar en la fase 0) |
| `clee` | Clave estadística empresarial |
| `nom_estab` | Nombre del establecimiento |
| `scian` | Clase de actividad SCIAN (6 dígitos) |
| `per_ocu` | Rango de personal ocupado |
| `cve_ent`, `cve_mun`, `cve_loc`, `ageb`, `manzana` | Claves geoestadísticas (sin concatenar, como vienen) |
| `tipo_vial`, `nom_vial` | Vialidad donde está |
| `tipo_cencom`, `nom_cencom` | Centro comercial, mercado o plaza donde está, si aplica |
| `tipo_uni` | Fijo, semifijo, etc. |
| `lat`, `lon` | Coordenadas (WGS84) |
| `fecha_alta` | Mes de alta en el directorio (`AAAA-MM`) |

Notas:

- Los CSV del INEGI vienen en distintas codificaciones según la versión; se pasan
  a UTF-8 al preparar.
- No todas las versiones tienen todas las columnas; las que faltan quedan nulas.
- La versión vigente se descarga sin carpeta de fecha (`.../masiva/denue/denue_00_*_csv.zip`).
  Su fecha está en `metadatos/metadatos_denue.txt` dentro de cada ZIP.
