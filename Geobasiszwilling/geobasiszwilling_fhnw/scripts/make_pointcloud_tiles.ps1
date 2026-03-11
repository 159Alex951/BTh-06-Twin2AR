# =============================================================================
# make_pointcloud_tiles.ps1
# =============================================================================
# Erstellt 3D Tiles (PNTS) aus LAS/LAZ Punktwolken-Dateien
# Verwendet gocesiumtiler für die Konvertierung
#
# Autor: GitHub Copilot
# Datum: 19.11.2025
# =============================================================================

param(
    [Parameter(Mandatory=$false)]
    [string]$InputFolder = "",
    
    [Parameter(Mandatory=$false)]
    [string]$OutputFolder = "c:\_data\terrain_V5\output\pointcloud\swisstopo_low",
    
    [Parameter(Mandatory=$false)]
    [int]$MaxNumPointsPerTile = 50000
)

# Farben für Konsolen-Ausgabe
function Write-Step { param($msg) Write-Host ">>> $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Yellow }

# Banner
Clear-Host
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host " Pointcloud 3D Tiles Generator" -ForegroundColor Magenta
Write-Host " (gocesiumtiler)" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""

# Input-Ordner abfragen falls nicht angegeben
if ([string]::IsNullOrWhiteSpace($InputFolder)) {
    Write-Step "Input-Ordner eingeben (LAS/LAZ Dateien):"
    $InputFolder = Read-Host "Pfad"
    
    if ([string]::IsNullOrWhiteSpace($InputFolder)) {
        Write-Error "Kein Input-Ordner angegeben!"
        exit 1
    }
}

# Pfad normalisieren
$InputFolder = $InputFolder.Trim('"').Trim("'")

# Prüfen ob Input-Ordner existiert
if (-not (Test-Path $InputFolder)) {
    Write-Error "Input-Ordner existiert nicht: $InputFolder"
    exit 1
}

# LAS/LAZ Dateien suchen
$lasFiles = Get-ChildItem -Path $InputFolder -Filter "*.las" -File
$lazFiles = Get-ChildItem -Path $InputFolder -Filter "*.laz" -File
$allFiles = $lasFiles + $lazFiles

if ($allFiles.Count -eq 0) {
    Write-Error "Keine LAS/LAZ Dateien gefunden in: $InputFolder"
    exit 1
}

Write-Success "Gefunden: $($allFiles.Count) Punktwolken-Dateien"
Write-Host ""

# Output-Ordner Auswahl
if ([string]::IsNullOrWhiteSpace($OutputFolder)) {
    $pointcloudBase = "c:\_data\terrain_V5\output\pointcloud"
    
    Write-Step "Verfügbare Output-Ordner:"
    
    # Bestehende Ordner auflisten
    $existingFolders = @()
    if (Test-Path $pointcloudBase) {
        $existingFolders = Get-ChildItem -Path $pointcloudBase -Directory | Select-Object -ExpandProperty Name
    }
    
    if ($existingFolders.Count -gt 0) {
        for ($i = 0; $i -lt $existingFolders.Count; $i++) {
            Write-Host "  [$($i + 1)] $($existingFolders[$i])" -ForegroundColor White
        }
        Write-Host "  [N] Neuen Ordner erstellen" -ForegroundColor Yellow
        Write-Host ""
        
        $choice = Read-Host "Auswahl (1-$($existingFolders.Count) oder N)"
        
        if ($choice -match '^\d+$') {
            $index = [int]$choice - 1
            if ($index -ge 0 -and $index -lt $existingFolders.Count) {
                $OutputFolder = Join-Path $pointcloudBase $existingFolders[$index]
            } else {
                Write-Error "Ungültige Auswahl!"
                exit 1
            }
        } elseif ($choice -eq "N" -or $choice -eq "n") {
            Write-Host ""
            $newName = Read-Host "Neuer Ordner-Name"
            if ([string]::IsNullOrWhiteSpace($newName)) {
                Write-Error "Kein Name angegeben!"
                exit 1
            }
            $OutputFolder = Join-Path $pointcloudBase $newName
        } else {
            Write-Error "Ungültige Eingabe!"
            exit 1
        }
    } else {
        Write-Info "Keine bestehenden Ordner gefunden."
        Write-Host ""
        $newName = Read-Host "Output-Ordner Name"
        if ([string]::IsNullOrWhiteSpace($newName)) {
            Write-Error "Kein Name angegeben!"
            exit 1
        }
        $OutputFolder = Join-Path $pointcloudBase $newName
    }
}

Write-Host ""
Write-Info "Output-Ordner: $OutputFolder"
Write-Host ""

# Bestätigung
$confirm = Read-Host "Fortfahren? (j/n)"
if ($confirm -ne "j" -and $confirm -ne "J" -and $confirm -ne "y" -and $confirm -ne "Y") {
    Write-Info "Abgebrochen durch Benutzer"
    exit 0
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""

# Output-Ordner erstellen
Write-Step "Erstelle Output-Ordner..."
New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null
Write-Success "Output-Ordner erstellt"
Write-Host ""

# Prüfen ob Docker verfügbar ist
Write-Step "Prüfe Docker Verfügbarkeit..."
try {
    $dockerVersion = docker --version 2>&1
    Write-Success "Docker gefunden: $dockerVersion"
} catch {
    Write-Error "Docker nicht gefunden! Bitte Docker Desktop installieren."
    exit 1
}

# Prüfen ob gocesiumtiler Docker Image existiert
Write-Step "Prüfe gocesiumtiler Docker Image..."
$imageName = "gocesiumtiler:latest"
$imageExists = docker images -q $imageName 2>$null

if (-not $imageExists) {
    Write-Info "Docker Image nicht gefunden. Baue Image..."
    
    $dockerfilePath = "c:\_data\terrain_V5\Dockerfile.gocesiumtiler"
    $buildContext = "c:\_data\terrain_V5"
    
    if (-not (Test-Path $dockerfilePath)) {
        Write-Error "Dockerfile nicht gefunden: $dockerfilePath"
        exit 1
    }
    
    # Build Image mit Build-Argument
    $zipUrl = "https://github.com/mfbonfigli/gocesiumtiler/releases/download/v2.3.1/gocesiumtiler-2.3.1-combined.zip"
    
    Write-Host "  Befehl: docker build -f `"$dockerfilePath`" --build-arg GOCESIUMTILER_ZIP_URL=`"$zipUrl`" -t $imageName `"$buildContext`"" -ForegroundColor DarkGray
    
    docker build -f "$dockerfilePath" --build-arg GOCESIUMTILER_ZIP_URL="$zipUrl" -t $imageName "$buildContext"
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker Build fehlgeschlagen!"
        exit 1
    }
    
    Write-Success "Docker Image erfolgreich gebaut"
} else {
    Write-Success "Docker Image gefunden: $imageName"
}
Write-Host ""

# =============================================================================
# POINTCLOUD TILING
# =============================================================================
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host " PUNKTWOLKEN VERARBEITUNG" -ForegroundColor Magenta
Write-Host " MaxNumPointsPerTile: $MaxNumPointsPerTile" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""

$counter = 0
foreach ($file in $allFiles) {
    $counter++
    $fileName = $file.Name
    $progress = "[$counter/$($allFiles.Count)]"
    
    Write-Step "$progress Verarbeite: $fileName"
    
    $inputPath = $file.FullName
    
    # Docker Pfade vorbereiten (Windows -> Linux Container)
    # Input-Datei einzeln mounten
    $containerInputFile = "/input/$fileName"
    $containerOutput = "/output"
    
    # gocesiumtiler via Docker ausführen
    try {
        $cmd = "docker run --rm " +
               "-v `"$($inputPath):/input/$fileName`" " +
               "-v `"$OutputFolder`:$containerOutput`" " +
               "$imageName " +
               "-input `"$containerInputFile`" " +
               "-output `"$containerOutput`" " +
               "-maxNumPointsPerTile $MaxNumPointsPerTile"
        
        Write-Host "  Befehl: $cmd" -ForegroundColor DarkGray
        
        Invoke-Expression $cmd
        
        if ($LASTEXITCODE -eq 0) {
            Write-Success "$progress $fileName -> erfolgreich"
        } else {
            Write-Error "$progress $fileName -> fehlgeschlagen (Exit: $LASTEXITCODE)"
        }
    } catch {
        Write-Error "$progress $fileName -> Fehler: $_"
    }
    
    Write-Host ""
}

# =============================================================================
# ZUSAMMENFASSUNG
# =============================================================================
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host " FERTIG" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""

Write-Success "Alle Punktwolken verarbeitet!"
Write-Host ""
Write-Info "Output-Ordner: $OutputFolder"
Write-Host ""

# Prüfe ob tileset.json erstellt wurde
$tilesetJson = Join-Path $OutputFolder "tileset.json"

if (Test-Path $tilesetJson) {
    Write-Success "tileset.json erstellt: $tilesetJson"
} else {
    Write-Error "tileset.json fehlt: $tilesetJson"
}

Write-Host ""
Write-Info "Nächste Schritte:"
Write-Host "  1. Prüfe tileset.json im Output-Ordner" -ForegroundColor White
Write-Host "  2. Füge Tileset zu app.js hinzu" -ForegroundColor White
Write-Host "  3. Teste im Browser" -ForegroundColor White
Write-Host ""
