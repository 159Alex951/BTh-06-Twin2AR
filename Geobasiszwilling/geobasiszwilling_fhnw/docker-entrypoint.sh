#!/bin/bash
set -e

# Erzeuge VRT aus TIF-Dateien im /data-Ordner, falls noch nicht vorhanden
VRT_FILE="/data/input.vrt"
if [ ! -f "$VRT_FILE" ]; then
  shopt -s nullglob
  tif_files=(/data/*.tif /data/*.tiff)
  if [ ${#tif_files[@]} -gt 0 ]; then
    echo "Erzeuge VRT: $VRT_FILE aus ${#tif_files[@]} Dateien"
    gdalbuildvrt "$VRT_FILE" /data/*.tif /data/*.tiff || true
  else
    echo "Keine TIF-Dateien in /data gefunden; überspringe VRT-Erzeugung"
  fi
fi

# Führe gocesiumtiler mit den Argumenten aus
exec gocesiumtiler "$@"
