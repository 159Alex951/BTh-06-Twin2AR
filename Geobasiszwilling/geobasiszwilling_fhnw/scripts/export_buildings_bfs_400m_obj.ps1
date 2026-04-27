Param()

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "OBJ Export: Gebaeude mit BFS-Daten (400m Grid -> OBJ + Anchor)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Config
$outputDir = "c:\_data\terrain_V5\output\buildings_bfs_400m_obj"
$dbHost    = "localhost"
$dbPort    = "5432"
$dbName    = "postgres"
$dbUser    = "postgres"
$dbPassword = "admin"

# Repo / docker-compose
$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# Prepare output directory
Write-Host ""
Write-Host "[1/4] Output-Verzeichnis vorbereiten..." -ForegroundColor Yellow
if (Test-Path $outputDir) {
    Write-Host "   Lösche altes Output-Verzeichnis..." -ForegroundColor Yellow
    Remove-Item -Path $outputDir -Recurse -Force
}
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
Write-Host "   Verzeichnis erstellt: $outputDir" -ForegroundColor Green

$ComposeFile = Join-Path $RepoRoot 'docker-compose.yml'
$containerId = (docker-compose -f $ComposeFile ps -q citydb_pg)
if ([string]::IsNullOrWhiteSpace($containerId)) {
    Write-Host "FEHLER: Service 'citydb_pg' läuft nicht. Starte mit: docker-compose up -d citydb_pg" -ForegroundColor Red
    exit 1
}

# Locate Python environment
$PythonPath = Join-Path $RepoRoot "..\..\ar_env\Scripts\python.exe"

# If Python environment doesn't exist, try resolving from current execution context
if (-not (Test-Path $PythonPath)) {
    # Alternative path based on standard layout (two levels up, then Twin2AR)
    $AltPythonPath = (Resolve-Path (Join-Path $RepoRoot "..\..\Twin2AR\ar_env\Scripts\python.exe") -ErrorAction SilentlyContinue).Path
    if ($AltPythonPath) {
        $PythonPath = $AltPythonPath
    } else {
        Write-Host "FEHLER: Python-Umgebung nicht gefunden in $PythonPath oder $AltPythonPath" -ForegroundColor Red
        Write-Host "Bitte stelle sicher, dass 'ar_env' existiert." -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "[2/4] Führe Python Export-Skript aus..." -ForegroundColor Yellow
$PythonScript = Join-Path $PSScriptRoot "export_400m_obj.py"

# Use container exec instead of direct port connection
& $PythonPath $PythonScript --db-user $dbUser --db-pass $dbPassword --db-name $dbName --container $containerId --out-dir $outputDir

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "FEHLER beim Export!" -ForegroundColor Red
    exit 1
}

# Check result
Write-Host ""
Write-Host "[3/4] Ergebnis prüfen..." -ForegroundColor Yellow
if (Test-Path (Join-Path $outputDir "anchor.json")) {
    Write-Host "anchor.json erfolgreich erstellt" -ForegroundColor Green

    $contentFiles = (Get-ChildItem -Path $outputDir -File -Filter "*.obj" -ErrorAction SilentlyContinue | Measure-Object).Count
    $totalSizeBytes = (Get-ChildItem -Path $outputDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $sizeMB = [Math]::Round($totalSizeBytes / 1MB, 2)

    Write-Host "   OBJ-Dateien: $contentFiles" -ForegroundColor Green
    Write-Host "   Gesamt-Größe: $sizeMB MB" -ForegroundColor Green
    Write-Host ""
    Write-Host "Ausgabe: $outputDir" -ForegroundColor Cyan
} else {
    Write-Host "WARNUNG: anchor.json nicht gefunden!" -ForegroundColor Red
    Write-Host "Prüfe Output-Verzeichnis: $outputDir" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Fertig! (400m Grid OBJ Export)" -ForegroundColor Cyan
