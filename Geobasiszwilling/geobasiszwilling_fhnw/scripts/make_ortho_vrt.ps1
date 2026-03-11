<#
.SYNOPSIS
  Komplette Pipeline für Orthophotos: CSV-Download ? VRT-Erstellung

.DESCRIPTION
  Dieses Skript führt automatisch alle Schritte aus:
  1. Zeigt vorhandene Ordner in geoserver_data/_data an
  2. Fragt nach Ziel-Ordner (oder erstellt neuen)
  3. Download aller URLs aus CSV-Dateien
  4. VRT-Erstellung aus allen heruntergeladenen TIF-Dateien (via GDAL-Container)

.PARAMETER Force
  Erzwingt erneuten Download bereits vorhandener Dateien.

.PARAMETER DataDir
  Optionaler Ziel-Ordner (z.B. "ortho_LV95"). Falls nicht angegeben, wird interaktiv gefragt.

.EXAMPLE
  .\make_ortho_vrt.ps1
  
  Fragt interaktiv nach Ziel-Ordner, führt Download und VRT-Erstellung aus.

.EXAMPLE
  .\make_ortho_vrt.ps1 -DataDir ortho_LV95 -Force
  
  Lädt alle Dateien in geoserver_data/_data/ortho_LV95, überschreibt vorhandene Dateien.
#>

param(
  [string]$DataDir = '',
  [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Pfade relativ zum Skript-Verzeichnis
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot '..') | Select-Object -ExpandProperty Path
$ImportRoot = Join-Path $RepoRoot 'import\geoserver'
$GeoDataRoot = Join-Path $RepoRoot 'www\ortho'

# Stelle sicher, dass import/geoserver existiert
if (-not (Test-Path $ImportRoot)) {
  Write-Host "Erstelle import/geoserver-Verzeichnis: $ImportRoot" -ForegroundColor Yellow
  New-Item -ItemType Directory -Path $ImportRoot -Force | Out-Null
}

# Stelle sicher, dass _data existiert
if (-not (Test-Path $GeoDataRoot)) {
  Write-Host "Erstelle _data-Verzeichnis: $GeoDataRoot" -ForegroundColor Yellow
  New-Item -ItemType Directory -Path $GeoDataRoot -Force | Out-Null
}

# ========================================
# 1. Wähle Import-Ordner
# ========================================
$ImportDir = ''
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Verfügbare Import-Ordner in import/geoserver:" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$importDirs = @(Get-ChildItem -Path $ImportRoot -Directory -ErrorAction SilentlyContinue)
if ($importDirs.Count -gt 0) {
  for ($i = 0; $i -lt $importDirs.Count; $i++) {
    Write-Host "  [$($i+1)] $($importDirs[$i].Name)"
  }
  Write-Host ""
  
  $choice = Read-Host "Wähle Import-Ordner (Nummer)"
  
  if ($choice -match '^\d+$') {
    $idx = [int]$choice - 1
    if ($idx -ge 0 -and $idx -lt $importDirs.Count) {
      $ImportDir = $importDirs[$idx].FullName
      $ImportDirName = $importDirs[$idx].Name
    } else {
      Write-Error "Ungültige Auswahl"; exit 1
    }
  } else {
    Write-Error "Ungültige Eingabe"; exit 1
  }
} else {
  Write-Error "Keine Import-Ordner in $ImportRoot gefunden. Erstelle z.B. import/geoserver/ortho mit CSV-Dateien."
  exit 1
}

# ========================================
# 2. Wähle Ziel-Ordner in geoserver_data/_data
# ========================================
if (-not $DataDir) {
  Write-Host ""
  Write-Host "========================================" -ForegroundColor Cyan
  Write-Host "Verfügbare Ziel-Ordner in geoserver_data/_data:" -ForegroundColor Cyan
  Write-Host "========================================" -ForegroundColor Cyan
  
  $existingDirs = @(Get-ChildItem -Path $GeoDataRoot -Directory -ErrorAction SilentlyContinue)
  if ($existingDirs.Count -gt 0) {
    for ($i = 0; $i -lt $existingDirs.Count; $i++) {
      Write-Host "  [$($i+1)] $($existingDirs[$i].Name)"
    }
    Write-Host "  [N] Neuen Ordner erstellen"
    Write-Host ""
    
    $choice = Read-Host "Wähle einen Ordner (Nummer) oder N für neu"
    
    if ($choice -match '^\d+$') {
      $idx = [int]$choice - 1
      if ($idx -ge 0 -and $idx -lt $existingDirs.Count) {
        $DataDir = $existingDirs[$idx].Name
      } else {
        Write-Error "Ungültige Auswahl"; exit 1
      }
    } elseif ($choice -eq 'N' -or $choice -eq 'n') {
      $DataDir = Read-Host "Neuer Ordnername (z.B. ortho_2024)"
    } else {
      Write-Error "Ungültige Eingabe"; exit 1
    }
  } else {
    Write-Host "  (Keine Ordner vorhanden)"
    Write-Host ""
    $DataDir = Read-Host "Neuer Ordnername (Standard: $ImportDirName)"
    if (-not $DataDir) { $DataDir = $ImportDirName }
  }
}

# Setze finale Pfade
$OrthoDir = Join-Path $GeoDataRoot $DataDir
$VrtFile = Join-Path $OrthoDir "$DataDir.vrt"

# Zeiterfassung initialisieren
$TimerStart = Get-Date
$StepTimes = @{}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Orthophoto VRT Pipeline" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Repo:          $RepoRoot"
Write-Host "Import-Ordner: $ImportDir"
Write-Host "Ziel-Ordner:   $OrthoDir"
Write-Host "VRT:           $VrtFile"
Write-Host ""

# Setze finale Pfade
$OrthoDir = Join-Path $GeoDataRoot $DataDir
$VrtFile = Join-Path $OrthoDir "$DataDir.vrt"

# Zeiterfassung initialisieren
$TimerStart = Get-Date
$StepTimes = @{}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Orthophoto VRT Pipeline" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Repo:        $RepoRoot"
Write-Host "Ziel-Ordner: $OrthoDir"
Write-Host "VRT:         $VrtFile"
Write-Host ""

# Stelle sicher, dass Ziel-Verzeichnis existiert
if (-not (Test-Path $OrthoDir)) {
  Write-Host "Erstelle Ziel-Verzeichnis: $OrthoDir" -ForegroundColor Yellow
  New-Item -ItemType Directory -Path $OrthoDir -Force | Out-Null
} else {
  # Lösche vorhandene TIF und VRT Dateien
  Write-Host "Lösche vorhandene Daten in: $OrthoDir" -ForegroundColor Yellow
  Get-ChildItem -Path $OrthoDir -Include "*.tif", "*.tiff", "*.vrt" -File -ErrorAction SilentlyContinue | Remove-Item -Force
}

# ========================================
# SCHRITT 1: Download
# ========================================
$Step1Start = Get-Date
Write-Host "[1/2] Download der Orthophoto-Daten aus CSV..." -ForegroundColor Green

# Download-Funktion
function Write-DownloadLog {
  param([string]$Msg)
  $time = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  $line = "[$time] $Msg"
  Write-Host $line
  Add-Content -Path (Join-Path $OrthoDir 'download_ortho.log') -Value $line
}

# CSV-Dateien finden
$csvFiles = @(Get-ChildItem -Path $ImportDir -Filter '*.csv' -File -ErrorAction SilentlyContinue)
if ($csvFiles.Count -eq 0) {
  Write-Warning "Keine CSV-Dateien in $ImportDir gefunden - überspringe Download"
} else {
  Write-Host "CSV-Dateien: $($csvFiles | ForEach-Object { $_.Name })"
  Write-Host "Ziel: $OrthoDir"
  
  # Log-Datei vorbereiten
  if (-not (Test-Path (Join-Path $OrthoDir 'download_ortho.log'))) { 
    New-Item -Path (Join-Path $OrthoDir 'download_ortho.log') -ItemType File -Force | Out-Null 
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
      Write-DownloadLog "Ungültige URL: $url — übersprungen"
      $failed += $url; continue
    }
    
    $fileName = [System.IO.Path]::GetFileName($uri.LocalPath)
    if (-not $fileName) { $fileName = [System.Guid]::NewGuid().ToString() + ".tif" }
    $dest = Join-Path $OrthoDir $fileName
    
    if ((Test-Path $dest) -and (-not $Force)) {
      Write-DownloadLog "Existiert: $fileName — übersprungen"
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
  Write-Host "Log: $(Join-Path $OrthoDir 'download_ortho.log')"
}

# Prüfe, ob TIF-Dateien vorhanden sind
$tifCheck = @(Get-ChildItem -Path $OrthoDir -Filter "*.tif*" -File -ErrorAction SilentlyContinue)
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
Write-Host "[2/2] Erzeuge VRT aus allen TIF-Dateien..." -ForegroundColor Green

# Prüfe, ob TIF-Dateien vorhanden sind
$tifFiles = @(Get-ChildItem -Path $OrthoDir -Filter "*.tif" -File -ErrorAction SilentlyContinue)
$tiffFiles = @(Get-ChildItem -Path $OrthoDir -Filter "*.tiff" -File -ErrorAction SilentlyContinue)
$allTifs = $tifFiles + $tiffFiles

if ($allTifs.Count -eq 0) {
  Write-Error "Keine TIF-Dateien in $OrthoDir gefunden. Abbruch."
  exit 1
}

Write-Host "Gefunden: $($allTifs.Count) TIF-Datei(en)"

# Aktualisiere docker-compose.yml temporär für ortho-Verzeichnis
Push-Location -Path $RepoRoot
try {
  Write-Host "Führe GDAL-Container aus (docker-compose run gdal mit Ortho-Mount)..."
  
  # Nutze bash -c um Wildcards korrekt aufzulösen
  docker-compose run --rm `
    -v "${OrthoDir}:/mnt" `
    --entrypoint bash `
    gdal `
    -c "gdalbuildvrt /mnt/$DataDir.vrt /mnt/*.tif /mnt/*.tiff"
  
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

$TotalTime = ($Step2End - $TimerStart).TotalSeconds

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Pipeline erfolgreich abgeschlossen!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "VRT: $VrtFile"
Write-Host ""
Write-Host "Zeitstatistik:" -ForegroundColor Yellow
Write-Host "  Download:       $([math]::Round($StepTimes['Download'], 2))s"
Write-Host "  VRT-Erstellung: $([math]::Round($StepTimes['VRT'], 2))s"
Write-Host "  ---------------------"
Write-Host "  Gesamt:         $([math]::Round($TotalTime, 2))s ($([math]::Round($TotalTime / 60, 2)) min)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Nächste Schritte:"
Write-Host "- VRT in GeoServer einbinden"
Write-Host "- Oder als Cesium ImageryProvider verwenden"
Write-Host ""
