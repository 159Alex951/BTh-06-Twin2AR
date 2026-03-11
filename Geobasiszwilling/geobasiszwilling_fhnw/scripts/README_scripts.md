# scripts/

PowerShell-Automation für Datenimport, Verarbeitung und Exporte. Alle Skripte sind für Windows (PowerShell 5.1+) geschrieben und nutzen Docker/Docker Compose für die eigentliche Verarbeitung.

## Namespace / Naming

- Compose Projektname: `geobasiszwilling` (Container heißen z.B. `geobasiszwilling-citydb_pg-1`)
- Service-Namen sind stabil (z.B. `webserver`, `geoserver`, `citydb_pg`)
- Skripte sollten bevorzugt `docker-compose run/exec <service>` verwenden statt fixe Container-Namen

## Inhalt

- `make_terrain_qm_full.ps1` – Terrain-Pipeline: CSV → Download → VRT → Quantized Mesh Tiles (CTB)
- `make_ortho_vrt.ps1` – Orthophoto-Pipeline: CSV → Download → VRT für GeoServer
- `make_pointcloud_tiles.ps1` – Punktwolken → 3D Tiles (low/high) (gocesiumtiler)
- `import_citygml.ps1` – CityGML Import in 3DCityDB/PostGIS + Cleanup
- `fetch_bfs_data.ps1` – BFS-Daten via GeoAdmin API holen + DB-View erstellen
- `export_buildings_bfs.ps1` – Export Buildings + BFS als 3D Tiles (tileset.json)
- `convert_fixpunkte_lv95_to_wgs84.ps1` – Fixpunkte CSV: LV95 → WGS84

## Gemeinsame Voraussetzungen

- Docker Desktop läuft
- `docker-compose.yml` ist für das Repo-Root ausgelegt (Standard: `.env` setzt `DATA_ROOT=.`)
- Eingabedaten liegen unter [import/](../import/)
- Outputs werden unter [output/](../output/) geschrieben und über NGINX bereitgestellt

## Terrain: Quantized Mesh (CTB)

### Empfohlen (End-to-End)

```powershell
.\scripts\make_terrain_qm_full.ps1
```

Optionaler Parameter:

- `-Force`: lädt Dateien erneut herunter (überschreibt vorhandene Dateien)

Was passiert:

1. CSVs unter `import/terrain/` werden gelesen (eine URL pro Zeile)
2. GeoTIFFs werden heruntergeladen
3. VRT wird erstellt (`import/terrain/input.vrt`)
4. CTB erzeugt Quantized Mesh Tiles nach `output/terrain_qm/`

### Manuell (wenn VRT schon existiert)

```powershell
docker-compose run --rm ctb_job
```

## Orthophotos: VRT für GeoServer (GDAL)

```powershell
.\scripts\make_ortho_vrt.ps1
```

- Interaktiv: fragt Zielordner unter `geoserver_data/_data/` ab
- Mit `-DataDir <name>`: wählt/erstellt Zielordner
- Mit `-Force`: überschreibt vorhandene Downloads

## Buildings/BFS: DB-Workflow (3DCityDB/PostGIS)

### DB starten

```powershell
docker-compose up -d citydb_pg
```

### CityGML importieren

```powershell
.\scripts\import_citygml.ps1 -InputFolder ".\import\building"
```

### BFS-Daten holen

```powershell
.\scripts\fetch_bfs_data.ps1
```

Optional (API schonen / Verhalten steuern): `-BatchSize`, `-DelayMs`, `-SkipExisting`.

### 3D Tiles Export (Buildings + BFS)

```powershell
.\scripts\export_buildings_bfs.ps1
```

Ergebnis: `output/buildings_bfs/tileset.json`.

## Troubleshooting (kurz)

- Compose/Netzwerk-Probleme: einmal `docker-compose up -d` im Repo-Root ausführen, damit das Compose-Netzwerk existiert
- Pfad-/Mount-Probleme unter Windows: in Compose/Volumes nur absolute Host-Pfade verwenden
