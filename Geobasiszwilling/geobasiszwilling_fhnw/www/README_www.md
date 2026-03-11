# www/

Cesium Web-App (Frontend) für Terrain/3D Tiles/Pointclouds inkl. Panels und Tools (Layer, Timeline, Export-Box, Infofenster, Koordinatenanzeige).

## Namespace / Naming

- Webserver-Service: `webserver` (NGINX)
- Projektname/Präfix der Container: `geobasiszwilling-*` (z.B. `geobasiszwilling-webserver-1`)

## Start

```powershell
docker-compose up -d webserver
start http://localhost/site/
```

## Datenquellen (lokal)

- Terrain (Quantized Mesh): http://localhost/terrain_qm/
- 3D Tiles / Pointclouds: http://localhost/
- Optional GeoServer (direkt): http://localhost:8081/geoserver
- Optional GeoServer (über NGINX): http://localhost/geoserver/

## Bedienung (kurz)

- Navigation: Linksklick ziehen = Orbit, Rechtsklick ziehen = Pan, Mausrad = Zoom
- Layer-Panel (links unten): Home, Zeitachse, Layer-Checkboxen, Basiskarten
- Floating Buttons (rechts unten): Licht/Schatten, Gebäude-Färbung (BFS), Fullscreen, Export-Box, Timeline, Pointcloud-Filter (kontextabhängig)

## Tools/Module (tools/)

- `bbox-tool.js` – Export-Box zeichnen (3 Punkte), Höhe setzen, Export auslösen
- `coords.js` – Live-Koordinatenanzeige (LV95/WGS84 + Höhe)
- `infofenster.js` – Infofenster bei Klick (Koordinaten/Attribute)
- `layers.js` – Basiskarten/WMS/Layer-Management
- `tiles.js` – 3D Tiles Loader (Buildings/Roofs/Pointcloud/Swisstopo)
- `timeline.js` – Timeline Controls (Datum/Zeit, lokale Zeitdarstellung)

## Export-Box (Objekt-Export)

Die Export-Box ruft serverseitig den Export-Service auf (siehe [export_api/README_export_api.md](../export_api/README_export_api.md)).

Typische Voraussetzungen:

- Buildings Tileset: `output/buildings_bfs/` vorhanden
- Terrain Tiles: `output/terrain_qm/` vorhanden (sonst Export ohne Terrain)
