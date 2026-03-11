# =============================================================================
# export_buildings_bfs.ps1
# Exportiert Gebaeude aus 3DCityDB (mit BFS-Daten) als 3D Tiles
# Ausgabe: output/buildings_bfs/
# =============================================================================

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "3D Tiles Export: Gebaeude mit BFS-Daten" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Konfiguration
$outputDir = "c:\_data\terrain_V5\output\buildings_bfs"
$dbHost = "citydb_pg"
$dbName = "postgres"
$dbUser = "postgres"
$dbPassword = "admin"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $RepoRoot 'docker-compose.yml'

function Get-ComposeProjectName {
    if (-not [string]::IsNullOrWhiteSpace($env:COMPOSE_PROJECT_NAME)) {
        return $env:COMPOSE_PROJECT_NAME
    }

    $envFile = Join-Path $RepoRoot '.env'
    if (Test-Path $envFile) {
        foreach ($line in (Get-Content $envFile -ErrorAction SilentlyContinue)) {
            if ($line -match '^\s*COMPOSE_PROJECT_NAME\s*=\s*(.+?)\s*$') {
                return $Matches[1].Trim('"').Trim("'")
            }
        }
    }

    return 'geobasiszwilling'
}

$ComposeProjectName = Get-ComposeProjectName
$NetworkName = "${ComposeProjectName}_default"

$citydbContainerId = (& docker-compose -f $ComposeFile ps -q $dbHost) 2>$null
if ([string]::IsNullOrWhiteSpace($citydbContainerId)) {
    Write-Host "      FEHLER: Service '$dbHost' läuft nicht. Starte mit: docker-compose up -d $dbHost" -ForegroundColor Red
    exit 1
}

# 1) Output-Verzeichnis vorbereiten
Write-Host "`n[1/4] Bereite Output-Verzeichnis vor..." -ForegroundColor Yellow

if (Test-Path $outputDir) {
    Write-Host "      Loesche altes Output-Verzeichnis..." -ForegroundColor Yellow
    Remove-Item -Path $outputDir -Recurse -Force
}

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
Write-Host "      Verzeichnis erstellt: $outputDir" -ForegroundColor Green

# 2) Anzahl Gebaeude pruefen
Write-Host "`n[2/4] Pruefe Gebaeude-Anzahl..." -ForegroundColor Yellow

$countQuery = "SELECT COUNT(*) FROM citydb.v_gebaeude_erweitert WHERE citydb_geometry IS NOT NULL;"
$countResult = docker exec $citydbContainerId psql -U postgres -d postgres -t -A -c $countQuery

if ($LASTEXITCODE -ne 0) {
    Write-Host "      FEHLER: Konnte Anzahl nicht ermitteln!" -ForegroundColor Red
    exit 1
}

$buildingCount = $countResult.Trim()
Write-Host "      $buildingCount Gebaeude mit Geometrie gefunden" -ForegroundColor Green

if ([int]$buildingCount -eq 0) {
    Write-Host "      FEHLER: Keine Gebaeude zum Exportieren!" -ForegroundColor Red
    exit 1
}

# 3) SQL-Query fuer pg2b3dm erstellen
Write-Host "`n[3/4] Erstelle Export-Query..." -ForegroundColor Yellow

$exportQuery = @"
SELECT 
    feature_id AS id,
    egid,
    objektart,
    baujahr,
    strasse,
    hausnummer,
    plz,
    gemeinde,
    dach_max,
    gelaendepunkt,
    anzahl_wohnungen,
    gebaeudekategorie,
    ST_Transform(citydb_geometry, 4326) AS geom
FROM citydb.v_gebaeude_erweitert
WHERE citydb_geometry IS NOT NULL
"@

Write-Host "      Query erstellt (transformiert nach WGS84)" -ForegroundColor Green

# 4) pg2b3dm ausfuehren
Write-Host "`n[4/4] Exportiere 3D Tiles mit pg2b3dm..." -ForegroundColor Yellow
Write-Host "      Dies kann einige Minuten dauern..." -ForegroundColor Yellow

# pg2b3dm Optionen:
# -h: Host
# -U: User
# -d: Database
# -t: Table/Query
# -c: Geometry column
# -a: Attribute columns (wird automatisch erkannt)
# -o: Output directory
# --use_implicit_tiling: Verwende implicit tiling (besser fuer grosse Datasets)
# --geometric_error: Geometric error (default: 2000, kleiner = mehr Detail)

# pg2b3dm erwartet Tabellenname über -t und Query über -q
$exportQueryOneLine = ($exportQuery -replace "\s+", " ").Trim()

# Umgebungsvariable fuer Passwort
$env:PGPASSWORD = $dbPassword

Write-Host "`n      Starte pg2b3dm Export..." -ForegroundColor Cyan

# Ausfuehren (direkter Befehl, kein multi-line)
docker run --rm `
    --network $NetworkName `
  -v "${outputDir}:/output" `
  -e PGPASSWORD=$dbPassword `
  geodan/pg2b3dm `
  pg2b3dm `
    -h $dbHost `
    -U $dbUser `
    -d $dbName `
        -t citydb.v_gebaeude_erweitert `
        -q "$exportQueryOneLine" `
    -c geom `
    -a "id,egid,objektart,baujahr,strasse,hausnummer,plz,gemeinde,dach_max,gelaendepunkt,anzahl_wohnungen" `
        -g 500 `
        --use_implicit_tiling false `
    -o /output

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n      FEHLER beim Export!" -ForegroundColor Red
    exit 1
}

# 5) Ergebnis pruefen
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Export abgeschlossen!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if (Test-Path "$outputDir\tileset.json") {
    Write-Host "tileset.json erfolgreich erstellt" -ForegroundColor Green
    
    # Dateien zaehlen
    $contentFiles = Get-ChildItem -Path "$outputDir\content" -File -ErrorAction SilentlyContinue | Measure-Object
    $subtreeFiles = Get-ChildItem -Path "$outputDir\subtrees" -File -ErrorAction SilentlyContinue | Measure-Object
    
    Write-Host "Content-Dateien: $($contentFiles.Count)" -ForegroundColor Green
    Write-Host "Subtree-Dateien: $($subtreeFiles.Count)" -ForegroundColor Green
    
    # Groesse
    $totalSize = (Get-ChildItem -Path $outputDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $sizeMB = [Math]::Round($totalSize / 1MB, 2)
    Write-Host "Gesamt-Groesse: $sizeMB MB" -ForegroundColor Green
    
    Write-Host "`nAusgabe: $outputDir" -ForegroundColor Cyan
    Write-Host "`nFuege in Cesium hinzu:" -ForegroundColor Yellow
    Write-Host "const buildingsTileset = viewer.scene.primitives.add(" -ForegroundColor Gray
    Write-Host "  new Cesium.Cesium3DTileset({" -ForegroundColor Gray
    Write-Host "    url: 'http://localhost:8083/buildings_bfs/tileset.json'" -ForegroundColor Gray
    Write-Host "  })" -ForegroundColor Gray
    Write-Host ");" -ForegroundColor Gray
} else {
    Write-Host "WARNUNG: tileset.json nicht gefunden!" -ForegroundColor Red
    Write-Host "Pruefe Output-Verzeichnis: $outputDir" -ForegroundColor Yellow
}

Write-Host "`nFertig!" -ForegroundColor Cyan
