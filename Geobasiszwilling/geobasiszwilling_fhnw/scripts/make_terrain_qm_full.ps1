<#
.SYNOPSIS
  Vollständige Pipeline: CSV-Download -> VRT-Erstellung -> Quantized-Mesh-Tiles

.DESCRIPTION
  Dieses Skript führt automatisch alle Schritte aus:
  1. Download aller URLs aus CSV-Dateien im terrain-Ordner
  2. VRT-Erstellung aus allen heruntergeladenen TIF-Dateien (via GDAL-Container)
  3. Quantized-Mesh-Erzeugung (via CTB-Job im docker-compose)

.PARAMETER Force
  Erzwingt erneuten Download bereits vorhandener Dateien.

.EXAMPLE
  .\make_terrain_qm_full.ps1
  
  Führt die komplette Pipeline aus.

.EXAMPLE
  .\make_terrain_qm_full.ps1 -Force
  
  Lädt alle Dateien neu herunter, auch wenn sie bereits existieren.
#>

param(
  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Pfade relativ zum Skript-Verzeichnis
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot '..') | Select-Object -ExpandProperty Path
$TerrainDir = Join-Path $RepoRoot 'import\terrain'
$VrtFile = Join-Path $TerrainDir 'input.vrt'
$OutputDir = Join-Path $RepoRoot 'output\terrain_qm'

# Zeiterfassung initialisieren
$TimerStart = Get-Date
$StepTimes = @{}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Quantized Mesh Pipeline" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Repo:    $RepoRoot"
Write-Host "Terrain: $TerrainDir"
Write-Host "Output:  $OutputDir"
Write-Host ""

# Stelle sicher, dass Output-Verzeichnis existiert
if (-not (Test-Path $OutputDir)) {
  Write-Host "Erstelle Output-Verzeichnis: $OutputDir" -ForegroundColor Yellow
  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

# ========================================
# SCHRITT 1: Download
# ========================================
$Step1Start = Get-Date
Write-Host "[1/3] Download der Terrain-Daten aus CSV..." -ForegroundColor Green

# Download-Funktion
function Write-DownloadLog {
  param([string]$Msg)
  $time = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  $line = "[$time] $Msg"
  Write-Host $line
  Add-Content -Path (Join-Path $TerrainDir 'download_terrain.log') -Value $line
}

# CSV-Dateien finden
$csvFiles = @(Get-ChildItem -Path $TerrainDir -Filter '*.csv' -File -ErrorAction SilentlyContinue)
if ($csvFiles.Count -eq 0) {
  Write-Warning "Keine CSV-Dateien in $TerrainDir gefunden - überspringe Download"
} else {
  Write-Host "CSV-Dateien: $($csvFiles | ForEach-Object { $_.FullName } | Out-String)"
  Write-Host "Ziel: $TerrainDir"
  
  # Log-Datei vorbereiten
  if (-not (Test-Path (Join-Path $TerrainDir 'download_terrain.log'))) { 
    New-Item -Path (Join-Path $TerrainDir 'download_terrain.log') -ItemType File -Force | Out-Null 
  }
  
  # URLs aus allen CSVs sammeln
  $urls = @()
  foreach ($csv in $csvFiles) {
    $urls += Get-Content -Path $csv.FullName | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') }
  }
  $urls = $urls | Select-Object -Unique
  
  $success = @()
  $failed = @()
  $retries = 3
  
  foreach ($url in $urls) {
    try {
      $uri = [System.Uri]::new($url)
    } catch {
      Write-DownloadLog "Ungültige URL: $url -> übersprungen"
      $failed += $url; continue
    }
    
    $fileName = [System.IO.Path]::GetFileName($uri.LocalPath)
    if (-not $fileName) { $fileName = [System.Guid]::NewGuid().ToString() }
    $dest = Join-Path $TerrainDir $fileName
    
    if ((Test-Path $dest) -and (-not $Force)) {
      Write-DownloadLog "Existiert: $fileName -> übersprungen"
      $success += $url; continue
    }
    
    $attempt = 0
    $ok = $false
    while (-not $ok -and $attempt -lt $retries) {
      $attempt++
      Write-DownloadLog ("Download Versuch {0}/{1}: {2} -> {3}" -f $attempt, $retries, $url, $fileName)
      try {
        if (Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue) {
          Start-BitsTransfer -Source $url -Destination $dest -ErrorAction Stop
        } else {
          Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -ErrorAction Stop
        }
        Write-DownloadLog "Erfolgreich: $fileName"
        $success += $url
        $ok = $true
      } catch {
        Write-DownloadLog "Fehler beim Herunterladen ($attempt): $($_.Exception.Message)"
        Start-Sleep -Seconds (2 * $attempt)
      }
    }
    
    if (-not $ok) {
      Write-DownloadLog "FEHLER: konnte $url nicht herunterladen nach $retries Versuchen"
      $failed += $url
    }
  }
  
  Write-DownloadLog "Fertig. Erfolgreich: $($success.Count), Fehler: $($failed.Count)"
  if ($failed.Count -gt 0) {
    Write-DownloadLog "Fehlgeschlagene Downloads:"
    $failed | ForEach-Object { Write-DownloadLog " - $_" }
  }
  Write-Host "Log: $(Join-Path $TerrainDir 'download_terrain.log')"
}

# Prüfe, ob TIF-Dateien vorhanden sind
$tifCheck = @(Get-ChildItem -Path $TerrainDir -Filter "*.tif*" -File -ErrorAction SilentlyContinue)
if ($tifCheck.Count -eq 0) {
  Write-Error "Keine TIF-Dateien nach Download gefunden. Abbruch."
  exit 1
}

$Step1End = Get-Date
$StepTimes['Download'] = ($Step1End - $Step1Start).TotalSeconds
Write-Host "Download abgeschlossen (Dauer: $([math]::Round($StepTimes['Download'], 2))s)" -ForegroundColor Green
Write-Host ""

# ========================================
# SCHRITT 2: VRT-Erstellung
# ========================================
$Step2Start = Get-Date
Write-Host "[2/3] Erzeuge VRT aus allen TIF-Dateien..." -ForegroundColor Green

# Prüfe, ob TIF-Dateien vorhanden sind
$tifFiles = @(Get-ChildItem -Path $TerrainDir -Filter "*.tif" -File -ErrorAction SilentlyContinue)
$tiffFiles = @(Get-ChildItem -Path $TerrainDir -Filter "*.tiff" -File -ErrorAction SilentlyContinue)
$allTifs = $tifFiles + $tiffFiles

if ($allTifs.Count -eq 0) {
  Write-Error "Keine TIF-Dateien in $TerrainDir gefunden. Abbruch."
  exit 1
}

Write-Host "Gefunden: $($allTifs.Count) TIF-Datei(en)"

# Wechsle ins Repo-Root für docker-compose
Push-Location -Path $RepoRoot
try {
  Write-Host "Führe GDAL-Container aus (docker-compose run gdal)..."
  
  # Nutze bash -c um Wildcards korrekt aufzulösen
  & docker-compose run --rm --entrypoint bash gdal -c "gdalbuildvrt /mnt/input.vrt /mnt/*.tif /mnt/*.tiff"
  
  if ($LASTEXITCODE -ne 0) {
    Write-Error "VRT-Erstellung fehlgeschlagen (ExitCode: $LASTEXITCODE)"
    exit $LASTEXITCODE
  }
} finally {
  Pop-Location
}

if (-not (Test-Path $VrtFile)) {
  Write-Error "VRT-Datei wurde nicht erstellt: $VrtFile"
  exit 1
}

$Step2End = Get-Date
$StepTimes['VRT'] = ($Step2End - $Step2Start).TotalSeconds
Write-Host "VRT erfolgreich erstellt (Dauer: $([math]::Round($StepTimes['VRT'], 2))s): $VrtFile" -ForegroundColor Green
Write-Host ""

# ========================================
# SCHRITT 3: Quantized Mesh
# ========================================
$Step3Start = Get-Date
Write-Host "[3/3] Erzeuge Quantized-Mesh-Tiles (CTB-Job)..." -ForegroundColor Green

# Lösche altes Output für sauberen Neustart
if (Test-Path $OutputDir) {
  Write-Host "Lösche altes Output-Verzeichnis..." -ForegroundColor Yellow
  Remove-Item -Path $OutputDir -Recurse -Force
  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Push-Location -Path $RepoRoot
try {
  Write-Host "Führe CTB-Tiling aus (Zoom 0-16 mit Error 0.2)..."
  docker-compose run --rm ctb_job
  
  if ($LASTEXITCODE -ne 0) {
    Write-Error "CTB-Tiling fehlgeschlagen (ExitCode: $LASTEXITCODE)"
    exit $LASTEXITCODE
  }
} finally {
  Pop-Location
}

$Step3End = Get-Date
$StepTimes['QM-Tiling'] = ($Step3End - $Step3Start).TotalSeconds
$TotalTime = ($Step3End - $TimerStart).TotalSeconds

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Pipeline erfolgreich abgeschlossen!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Output: $OutputDir"
Write-Host ""
Write-Host "Zeitstatistik:" -ForegroundColor Yellow
Write-Host "  Download:     $([math]::Round($StepTimes['Download'], 2))s"
Write-Host "  VRT-Erstellung: $([math]::Round($StepTimes['VRT'], 2))s"
Write-Host "  QM-Tiling:    $([math]::Round($StepTimes['QM-Tiling'], 2))s ($([math]::Round($StepTimes['QM-Tiling'] / 60, 2)) min)"
Write-Host "  ---------------------"
Write-Host "  Gesamt:       $([math]::Round($TotalTime, 2))s ($([math]::Round($TotalTime / 60, 2)) min)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Nächste Schritte:"
Write-Host "- Starte NGINX-Server: docker-compose up -d webserver"
Write-Host "- Öffne Browser: http://localhost:8080"
Write-Host ""