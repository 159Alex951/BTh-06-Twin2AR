Param()
old scrpt
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "3D Tiles Export: Gebaeude mit BFS-Daten (400m Grid)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Config
$outputDir = "c:\_data\terrain_V5\output\buildings_bfs_400m"
$dbHost    = "citydb_pg"
$dbName    = "postgres"
$dbUser    = "postgres"
$dbPassword = "admin"

# Repo / docker-compose
$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $RepoRoot 'docker-compose.yml'

# Get container id (you already know this pattern)
$containerId = (docker-compose -f $ComposeFile ps -q $dbHost)
if ([string]::IsNullOrWhiteSpace($containerId)) {
    Write-Host "FEHLER: Service '$dbHost' läuft nicht. Starte mit: docker-compose up -d $dbHost" -ForegroundColor Red
    exit 1
}

# Network name (as in your other scripts)
function Get-ComposeProjectName {
    if (-not [string]::IsNullOrWhiteSpace($env:COMPOSE_PROJECT_NAME)) {
        return $env:COMPOSE_PROJECT_NAME
    }

    $envFile = Join-Path $RepoRoot ".env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile -ErrorAction SilentlyContinue) {
            if ($line -match "COMPOSE_PROJECT_NAME\s*=\s*(.+)") {
                return $Matches[1].Trim()
            }
        }
    }
    return "geobasiszwilling"
}
$ComposeProjectName = Get-ComposeProjectName
$NetworkName = "${ComposeProjectName}_default"

# 1) Prepare output directory
Write-Host ""
Write-Host "[1/4] Output-Verzeichnis vorbereiten..." -ForegroundColor Yellow
if (Test-Path $outputDir) {
    Write-Host "   Lösche altes Output-Verzeichnis..." -ForegroundColor Yellow
    Remove-Item -Path $outputDir -Recurse -Force
}
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
Write-Host "   Verzeichnis erstellt: $outputDir" -ForegroundColor Green

# 2) Count buildings in v_buildings_400m_tiles
Write-Host ""
Write-Host "[2/4] Prüfe Gebäude-Anzahl in 400m Tiles..." -ForegroundColor Yellow
$countQuery = "SELECT COUNT(*) FROM citydb.v_buildings_400m_tiles WHERE citydb_geometry IS NOT NULL"
$countResult = docker exec $containerId psql -U $dbUser -d $dbName -t -A -c "$countQuery"
if ($LASTEXITCODE -ne 0) {
    Write-Host "FEHLER: Konnte Anzahl nicht ermitteln!" -ForegroundColor Red
    exit 1
}
$buildingCount = [int]$countResult.Trim()
Write-Host "   $buildingCount Gebäude-Tile-Zuordnungen mit Geometrie gefunden" -ForegroundColor Green
if ($buildingCount -eq 0) {
    Write-Host "FEHLER: Keine Gebäude zum Exportieren!" -ForegroundColor Red
    exit 1
}

# 3) Run pg2b3dm (table-mode on v_buildings_400m_tiles)
Write-Host ""
Write-Host "[3/4] Exportiere 3D Tiles mit pg2b3dm..." -ForegroundColor Yellow
Write-Host "   Dies kann einige Minuten dauern..." -ForegroundColor Yellow

docker run --rm `
    --network $NetworkName `
    -v "${outputDir}:/output" `
    geodan/pg2b3dm `
    pg2b3dm `
        --connection "Host=$dbHost;Username=$dbUser;Password=$dbPassword;Database=$dbName;CommandTimeOut=0" `
        -t "citydb.v_buildings_400m_tiles" `
        -c "citydb_geometry" `
        -a "grid_id,egid,objektart,baujahr,strasse,hausnummer,plz,gemeinde,dach_max,gelaendepunkt,anzahl_wohnungen" `
        -q "citydb_geometry IS NOT NULL" `
        -g 500 `
        --use_implicit_tiling false `
        -o "/output"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "FEHLER beim Export!" -ForegroundColor Red
    exit 1
}

# 4) Check result
Write-Host ""
Write-Host "[4/4] Ergebnis prüfen..." -ForegroundColor Yellow
if (Test-Path (Join-Path $outputDir "tileset.json")) {
    Write-Host "tileset.json erfolgreich erstellt" -ForegroundColor Green

    $contentFiles = (Get-ChildItem -Path $outputDir -File -ErrorAction SilentlyContinue | Measure-Object).Count
    $totalSizeBytes = (Get-ChildItem -Path $outputDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $sizeMB = [Math]::Round($totalSizeBytes / 1MB, 2)

    Write-Host "   Content-Dateien: $contentFiles" -ForegroundColor Green
    Write-Host "   Gesamt-Größe: $sizeMB MB" -ForegroundColor Green
    Write-Host ""
    Write-Host "Ausgabe: $outputDir" -ForegroundColor Cyan
} else {
    Write-Host "WARNUNG: tileset.json nicht gefunden!" -ForegroundColor Red
    Write-Host "Prüfe Output-Verzeichnis: $outputDir" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Fertig! (400m Grid Export)" -ForegroundColor Cyan