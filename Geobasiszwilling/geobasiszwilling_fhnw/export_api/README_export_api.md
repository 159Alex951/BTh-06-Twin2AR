# export_api/ (Buildings + Terrain → OBJ)

Dieser Ordner enthält den minimalen HTTP-Service, der aus der im Cesium-Viewer gezeichneten Export-Box ein **einziges OBJ** erzeugt.

## Namespace / Naming

- Service-Name: `export_api`
- Zugriff im Browser geht über NGINX (`webserver`) unter `http://localhost/export/`
- Container-Name ist Compose-generiert (Beispiel): `geobasiszwilling-export_api-1`

- **Buildings**: Auswahl passender 3D-Tiles-GLBs aus `output/buildings_bfs/content/` (BBox-Schnitt), Konvertierung via `assimp`, danach Merge zu einem OBJ.
- **Terrain**: Auswahl passender Quantized-Mesh Tiles aus `output/terrain_qm/` (EPSG:4326, `schema=tms`), Decoding der `.terrain`-Files und Anhängen als Mesh-Gruppen in dasselbe OBJ.

## Verfahren (kurz)

Das Export-Verfahren ist bewusst **serverseitig** umgesetzt und läuft (vereinfacht) so ab:

1. **User zeichnet Export-Box** im Cesium Viewer (WGS84 Polygon/Footprint).
2. **Backend selektiert Building-Tiles**:
  - Es werden die GLB-Tiles aus `output/buildings_bfs/content/` gewählt, deren Tile-Region die Export-BBox schneidet.
3. **Konvertierung GLB → OBJ**:
  - Jedes selektierte GLB wird per `assimp` nach OBJ konvertiert.
4. **OBJ Merge**:
  - Alle Tile-OBJs werden zu einem OBJ zusammengeführt (Vertex-/Face-Indizes werden korrekt nachgeführt).
5. **Terrain-Decoding & Append**:
  - Passende Quantized-Mesh Tiles werden für die Export-BBox bestimmt.
  - `.terrain` wird dekodiert (inkl. optional gzip) und als Dreiecksmesh als Gruppen `terrain_*` ans OBJ angehängt.
6. **Finale Platzierung für DCC**:
  - Default: reine Translation (`normalize=raw`), damit das Modell bei (0,0,0) startet.
  - Optional: ENU-Normalisierung (`normalize=enu`).

## Endpoints

### `GET /export/buildings.obj`

Erzeugt und liefert ein OBJ als Download (Gebäude + Terrain im selben File).

**Query-Parameter**

- `poly` (required)
  - JSON-Array aus `[lon, lat]` Punkten in WGS84 (Grad). Beispiel: `[[lon,lat],[lon,lat],...]`
  - Es wird ein Rechteck erwartet; intern werden die ersten 4 Punkte genutzt.
- `filename` (optional)
  - Gewünschter Download-Dateiname (wird serverseitig abgesichert/gesäubert).
- `normalize` (optional)
  - Steuerung, wie das finale OBJ für DCC-Tools (z.B. Blender) platziert wird.

## Betrieb (Docker)

Der Container wird über `docker-compose.yml` als Service `export_api` gestartet und über NGINX unter `/export/` bereitgestellt.

- Health-Check: `GET /export/health`
