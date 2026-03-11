# Geobasiszwilling - Cesium Terrain Pipeline

Dieses Projekt automatisiert die Erstellung von Cesium-kompatiblen Terrain-Tiles (Quantized Mesh) aus Höhendaten.
Zusätzlich enthält es eine Cesium-Web-App mit interaktiven 3D-Features (Layer, Timeline, Export-Box, etc.).

## Namespace / Naming

- Docker Compose Projektname: `geobasiszwilling` (kommt aus `.env` via `COMPOSE_PROJECT_NAME`)
- Service-Namen sind die “Namespace”-Basis (z.B. `webserver`, `geoserver`, `citydb_pg`)
- Container-Namen werden von Compose automatisch erzeugt: `geobasiszwilling-<service>-1`
- Alle Bind-Mounts laufen über `${DATA_ROOT}` (Default: `.`, ebenfalls in `.env`)

## 🚀 Quick Start

```powershell
# 1. Alle Terrain-Daten herunterladen und Tiles erzeugen
.\scripts\make_terrain_qm_full.ps1

# 2. Web-Server starten
docker-compose up -d webserver

# 3. Browser öffnen
start http://localhost/site/
```

## 📝 Projekt-Struktur

```
geobasiszwilling_fhnw/
├── docker-compose.yml        # Container-Orchestrierung
├── Dockerfile.gocesiumtiler  # Custom gocesiumtiler Image
├── docker-entrypoint.sh      # Entrypoint für VRT-Auto-Erstellung
├── README.md                 # Diese Datei
├── scripts/README_scripts.md # Skript-Doku (Pipelines/DB/Exporte)
├── import/README_import.md   # Input-Doku (CSV/GeoTIFF/LiDAR/CityGML)
├── output/README_output.md   # Output-Doku (Tiles/URLs)
├── www/README_www.md         # Frontend-Doku (Module/Bedienung)
├── nginx/README_nginx.md     # NGINX-Doku (Serving/Ports)
├── import/
│   └── terrain/              # Input: Höhendaten (TIF) + CSV-Listen
├── output/
│   └── terrain_qm/           # Output: Quantized Mesh Tiles
├── scripts/
│   ├── make_terrain_qm_full.ps1   # Komplette Pipeline (Download → VRT → QM-Tiles)
│   ├── make_ortho_vrt.ps1         # Orthophoto-Pipeline für GeoServer
│   └── ...                        # Weitere Automationsskripte
├── www/
│   ├── index.html            # Cesium Web-App mit Floating Buttons, Panels, Legende
│   ├── app.js                # Cesium-Konfiguration und UI-Logik
│   ├── styles.css            # Glassmorphism-UI, Responsive Design
│   └── tools/                # Cesium-Module (Tiles, Layers, Timeline, Infofenster)
├── geoserver_data/           # GeoServer-Konfiguration
├── nginx/
│   └── default.conf          # NGINX-Konfiguration
```

## Features der Web-App

### Interaktive Cesium-Viewer-Funktionen
- Floating Action Buttons (rechts unten):
  - Licht & Schatten
  - Gebäude nach Baujahr färben (BFS-Legende)
  - Fullscreen
  - Export Box (BBox zeichnen)
  - Timeline Controls
  - Punktwolken-Klassifikation (Filter)
- Layer-Auswahl inkl. Swisstopo 3D Tiles API
- Timeline-Steuerung mit lokaler Zeit, Datum-/Zeit-Picker
- Responsive Panels und Glassmorphism-Design
- UTF-8 (Umlaute/Icons) für alle Labels
- Automatische Tooltips und Labels mit Ausblend-Logik
- Infofenster mit Koordinatenanzeige

## Services

| Service | Beschreibung | Port | Status |
|---------|-------------|------|--------|
| **webserver** | NGINX - Tiles + Web-App + Proxies | 80 | Produktiv |
| **geoserver** | GeoServer | 8081 | Produktiv |
| **gdal** | GDAL (VRT-Erstellung) | - | On-Demand |
| **ctb_job** | CTB Quantized Mesh | - | On-Demand |
| **gocesiumtiler** | 3D Tiles / Pointclouds | - | On-Demand |

## Workflow

### 1) Daten vorbereiten
Lege CSV-Dateien mit Download-URLs in `import/terrain/`:
```csv
https://example.com/terrain/file1.tif
https://example.com/terrain/file2.tif
```

### 2) Pipeline ausführen
```powershell
# Automatisch: Download → VRT → Quantized Mesh
.\scripts\make_terrain_qm_full.ps1

# Mit Force-Download (überschreibt vorhandene Dateien)
.\scripts\make_terrain_qm_full.ps1 -Force
```

### 3) Manuell (einzelne Schritte per Docker)
```powershell
# VRT erstellen (wenn TIF-Dateien bereits in import/terrain/ liegen)
docker-compose run --rm gdal bash -c "gdalbuildvrt /mnt/input.vrt /mnt/*.tif /mnt/*.tiff"

# Quantized Mesh erzeugen
docker-compose run --rm ctb_job
```

### 4) Server starten
```powershell
# Alle Services
docker-compose up -d

# Nur Web-Server
docker-compose up -d webserver

# Nur GeoServer
docker-compose up -d geoserver
```

## URLs

- **Cesium Viewer:** http://localhost/site/
- **Terrain Tiles:** http://localhost/terrain_qm/
- **GeoServer (direkt):** http://localhost:8081/geoserver
- **GeoServer (über NGINX):** http://localhost/geoserver/
- **Export API (über NGINX):** http://localhost/export/
  - User: `admin`
  - Pass: `geoserver`

## 📚 Dokumentation

- **[scripts/README_scripts.md](scripts/README_scripts.md)** - PowerShell-Skripte (Pipelines, DB-Workflow, Exporte)
- **[import/README_import.md](import/README_import.md)** - Eingangsdaten (CSV/GeoTIFF/LiDAR/CityGML)
- **[output/README_output.md](output/README_output.md)** - Generierte Tiles/Outputs + URLs
- **[www/README_www.md](www/README_www.md)** - Cesium Web-App (Bedienung + Module)
- **[nginx/README_nginx.md](nginx/README_nginx.md)** - NGINX-Serving (App + Tiles)
- **[export_api/README_export_api.md](export_api/README_export_api.md)** - OBJ-Export (Buildings + Terrain)
- **[geoserver_data/README_geoserver_data.md](geoserver_data/README_geoserver_data.md)** - GeoServer DataDir (Konfiguration + Rasterdaten)
- **[pgdata/README_pgdata.md](pgdata/README_pgdata.md)** - Postgres/PostGIS Persistenz (DB-Volume)

## 🔧 Anforderungen

- **Docker Desktop** (Windows)
- **PowerShell 5.1+**
- **Git** (optional, für Versionskontrolle)

## ⚡ Performance-Tipps

### Schnellere Testläufe
Für kleine Test-Datensätze kannst du die Max-Zoom-Level begrenzen (im `docker-compose.yml`):
```yaml
# ctb_job command anpassen:
ctb-tile ... --max-zoom 14 ...  # statt Standard (meist 18-19)
```

### Verarbeitungszeit
**Hochauflösend (0.5m - swissALTI3D):**
- ~1 GB Daten: 1-2 Stunden
- ~10 GB Daten: 10-20 Stunden  
- ~50 GB Daten: 50-100 Stunden

**Niedrigere Auflösung (1m+):**
- ~1 GB Daten: 5-10 Minuten
- ~10 GB Daten: 50-90 Minuten

CPU-Kerne und SSD vs. HDD machen großen Unterschied!

## Troubleshooting

### Container startet nicht
```powershell
# Logs prüfen
docker-compose logs webserver

# Neustart erzwingen
docker-compose down
docker-compose up -d --build
```

### VRT-Fehler
```powershell
# Manuell VRT erstellen (mit korrekten Pfaden)
docker-compose run --rm gdal sh -c "gdalbuildvrt /mnt/input.vrt /mnt/*.tif"
```

### Tiles werden nicht angezeigt
1. Prüfe `output/terrain_qm/layer.json` existiert
2. Prüfe NGINX läuft: `docker ps | findstr webserver`
3. Öffne http://localhost/terrain_qm/layer.json im Browser

## 📝 Lizenz

Projekt-spezifisch - siehe verwendete Tools:
- **CTB:** MIT License
- **gocesiumtiler:** Apache 2.0
- **GDAL:** X/MIT License
- **CesiumJS:** Apache 2.0

---

**Erstellt:** 2025-11-19  
**Version:** 5.0  
**Maintainer:** Adrian Furrer
