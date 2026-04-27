# output/

Generierte Daten (Terrain/3D Tiles/Pointclouds/Exports). Dieser Ordner wird vom NGINX-Service `webserver` als statischer Content bereitgestellt.

## Namespace / Naming

- Alle Dateien in diesem Ordner werden relativ zu `${DATA_ROOT}` gemountet (Default: `.`, siehe `.env`)
- Auslieferung erfolgt über den Compose-Service `webserver`

## Struktur (typisch)

- `terrain_qm/` – Cesium Quantized Mesh Terrain (`layer.json` + `z/x/y.terrain`)
- `buildings/` – 3D Tiles (Gebäude)
- `buildings_bfs/` – 3D Tiles (Gebäude inkl. BFS-Attribute)
- `roofs/` – 3D Tiles (Dächer)
- `pointcloud/` – 3D Tiles (Punktwolken; low/high)
- Unterstrich-Ordner wie `_terrain_qm/`, `_buildings/` – Zwischenstände/Backups (optional)

## Wichtige URLs (bei laufendem NGINX)

- Tiles Root: http://localhost/
- Terrain: http://localhost/terrain_qm/layer.json
- Buildings BFS: http://localhost/buildings_bfs/tileset.json
- Pointcloud low: http://localhost/pointcloud/swisstopo_low/tileset.json
- Pointcloud high: http://localhost/pointcloud/swisstopo_high/tileset.json

## Wie wird das erzeugt?

- Terrain: `scripts/make_terrain_qm_full.ps1` oder `docker-compose run --rm ctb_job`
- Buildings/BFS: `scripts/import_citygml.ps1` → `scripts/fetch_bfs_data.ps1` → `scripts/export_buildings_bfs.ps1`
- Pointcloud: `scripts/make_pointcloud_tiles.ps1`

## Troubleshooting

- 404 auf `layer.json`: CTB-Job lief nicht durch oder Output-Pfad/Mount stimmt nicht
- CORS: NGINX setzt `Access-Control-Allow-Origin: *` (siehe [nginx/README_nginx.md](../nginx/README_nginx.md))
