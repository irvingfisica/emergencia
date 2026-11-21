#!/usr/bin/env bash
# Descarga las versiones nacionales del DENUE (CSV) listadas en urls_denue.txt.
# Uso: DESTINO=/ruta/denue ./scripts/descargar_denue.sh
# Deja cada versión en $DESTINO/<versión>/ y se puede reanudar: salta los ZIP completos.
set -u
BASE=${DESTINO:-datos/denue/raw}
URLS="$(dirname "$0")/urls_denue.txt"
mkdir -p "$BASE"
while read -r url; do
  [ -z "$url" ] && continue
  ver=$(echo "$url" | sed -E 's#.*/masiva/denue/([^/]+)/.*#\1#')
  f=$(basename "$url")
  mkdir -p "$BASE/$ver"
  if [ -s "$BASE/$ver/$f" ] && unzip -tq "$BASE/$ver/$f" >/dev/null 2>&1; then continue; fi
  for i in 1 2 3 4; do
    curl -sSfL --retry 3 -o "$BASE/$ver/$f.part" "$url" && mv "$BASE/$ver/$f.part" "$BASE/$ver/$f" && break
    sleep $((i * 20))
  done
  echo "$(date +%T) $ver $f $(stat -c %s "$BASE/$ver/$f" 2>/dev/null || echo FALLO)"
done < "$URLS"
echo FIN > "$BASE/FIN"
