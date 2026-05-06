Param()

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "GLB Export: Gebaeude mit BFS-Daten (400m Grid -> GLB + Anchor)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Config
$outputDir = "c:\_data\terrain_V5\output\buildings_bfs_400m_glb"
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

if (-not (Test-Path $PythonPath)) {
    $AltPythonPath = (Resolve-Path (Join-Path $RepoRoot "..\..\Twin2AR\ar_env\Scripts\python.exe") -ErrorAction SilentlyContinue).Path
    if ($AltPythonPath) {
        $PythonPath = $AltPythonPath
    } else {
        Write-Host "FEHLER: Python-Umgebung nicht gefunden in $PythonPath" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "[2/4] Führe Python Export-Skript aus..." -ForegroundColor Yellow
$PythonScript = Join-Path $PSScriptRoot "export_400m_glb.py"

& $PythonPath $PythonScript --db-user $dbUser --db-pass $dbPassword --db-name $dbName --container $containerId --out-dir $outputDir

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "FEHLER beim Export!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[3/4] Ergebnis prüfen..." -ForegroundColor Yellow
if (Test-Path (Join-Path $outputDir "anchor.json")) {
    Write-Host "anchor.json erfolgreich erstellt" -ForegroundColor Green

    $contentFiles = (Get-ChildItem -Path $outputDir -File -Filter "*.glb" -ErrorAction SilentlyContinue | Measure-Object).Count
    $totalSizeBytes = (Get-ChildItem -Path $outputDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $sizeMB = [Math]::Round($totalSizeBytes / 1MB, 2)

    Write-Host "   GLB-Dateien: $contentFiles" -ForegroundColor Green
    Write-Host "   Gesamt-Größe: $sizeMB MB" -ForegroundColor Green
    Write-Host ""
    Write-Host "Ausgabe: $outputDir" -ForegroundColor Cyan
} else {
    Write-Host "WARNUNG: anchor.json nicht gefunden!" -ForegroundColor Red
}

Write-Host ""
Write-Host "Fertig! (400m Grid GLB Export)" -ForegroundColor Cyan