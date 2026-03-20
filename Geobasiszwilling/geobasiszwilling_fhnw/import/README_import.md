# import/

Eingangsdaten für alle Pipelines (Terrain, Pointcloud, Buildings/DB, GeoServer). Die Skripte unter [scripts/](../scripts/) erwarten ihre Inputs standardmäßig hier.

## Namespace / Naming

- Standard-Setup: `.env` setzt `DATA_ROOT=.` und `COMPOSE_PROJECT_NAME=geobasiszwilling`
- Dadurch sind alle Pfade in der Doku relativ zum Repo-Root gedacht (z.B. `.\import\building`)

## Struktur

- `terrain/` – Höhendaten: GeoTIFFs + CSV-Downloadlisten + `input.vrt`
- `pointcloud/` – Punktwolken `.las/.laz`
- `building/` – Buildings/DB-Workflow (CityGML + SQL)
- `geoserver/` – Listen/Inputs für Orthophoto-Downloads (VRT/WMS)
- `mesh/`, `point/`, `pointcloud/`, `terrain/` – weitere, optionale Inputs je Workflow

## Terrain (Höhendaten)

### CSV-Downloadlisten

Lege eine oder mehrere CSV-Dateien in `import/terrain/` ab. Minimal: eine URL pro Zeile.

Beispiel:

```csv
https://data.geo.admin.ch/.../tile_01.tif
https://data.geo.admin.ch/.../tile_02.tif
```

### Pipeline starten

```powershell
.\scripts\make_terrain_qm_full.ps1
```

Ergebnis:

- `import/terrain/input.vrt` (VRT, automatisch erstellt)
- `output/terrain_qm/` (Quantized Mesh Tiles + `layer.json`)

## Pointcloud (LiDAR)

- Lege `.las`/`.laz` Dateien nach `import/pointcloud/`
- Erzeuge Tilesets über `scripts/make_pointcloud_tiles.ps1`
- Erwartete Outputs (für Viewer/NGINX):
  - `output/pointcloud/swisstopo_low/tileset.json`
  - `output/pointcloud/swisstopo_high/tileset.json`

## Buildings + BFS (DB-Workflow)

Dieser Workflow basiert auf 3DCityDB/PostGIS (`citydb_pg`) und verbindet CityGML-Gebäude über EGID mit BFS-Daten.

### Relevante Inputs (building/)

- CityGML: `import/building/*.gml` (oder `.xml`, je nach Datenstand)
- SQL:
  - `01_create_bfs_table.sql`
  - `02_create_view_gebaeude_erweitert.sql`
  - `Löschen_ausserhalb_bereich.sql` (Cleanup per Bounding Box)

### Typischer Ablauf

1. DB starten:

```powershell
docker-compose up -d citydb_pg
```

2. CityGML importieren + Cleanup:

```powershell
.\scripts\import_citygml.ps1 -InputFolder ".\import\building"
```

3. BFS-Daten holen + View erstellen:

```powershell
.\scripts\fetch_bfs_data.ps1
```

4. Export als 3D Tiles (Buildings + BFS-Attribute):

```powershell
.\scripts\export_buildings_bfs.ps1
```

Output: `output/buildings_bfs/tileset.json` (über NGINX erreichbar, siehe [output/README_output.md](../output/README_output.md)).

## GeoServer (Orthophotos)

- CSVs/Inputs für Orthophoto-Downloads liegen typischerweise unter `import/geoserver/`
- VRT-Erstellung erfolgt über `scripts/make_ortho_vrt.ps1`

## Quick Checks

- Terrain leer: `import/terrain/input.vrt` und `output/terrain_qm/layer.json` prüfen
- Viewer lädt nichts: NGINX muss laufen (siehe [nginx/README_nginx.md](../nginx/README_nginx.md))
