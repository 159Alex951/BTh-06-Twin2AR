# =============================================================================
# import_citygml.ps1
# =============================================================================
# Importiert CityGML-Dateien aus import/building in die 3DCityDB
# Verwendet citydb-tool (wird per docker run gestartet)
#
# Autor: GitHub Copilot
# Datum: 20.11.2025
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$InputFolder = "",

    [Parameter(Mandatory = $false)]
    [string]$DatabaseHost = "localhost",

    [Parameter(Mandatory = $false)]
    [int]$DatabasePort = 5432,

    [Parameter(Mandatory = $false)]
    [string]$DatabaseName = "postgres",

    [Parameter(Mandatory = $false)]
    [string]$DatabaseSchema = "citydb",

    [Parameter(Mandatory = $false)]
    [string]$DatabaseUser = "postgres",

    [Parameter(Mandatory = $false)]
    [string]$DatabasePassword = "admin"
)

# Farben für Konsolen-Ausgabe
function Write-Step { param($msg) Write-Host ">>> $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Error { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }
function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Yellow }

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
$CityDbServiceName = 'citydb_pg'

# Banner
Clear-Host
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host " CityGML Import (3DCityDB)" -ForegroundColor Magenta
Write-Host "=============================================" -ForegroundColor Magenta
Write-Host ""

# Standard Input-Ordner
$defaultInputFolder = "c:\_data\terrain_V5\import\building"

# Input-Ordner abfragen falls nicht angegeben
if ([string]::IsNullOrWhiteSpace($InputFolder)) {
    Write-Step "Input-Ordner für CityGML-Dateien:"
    Write-Host "  Standard: $defaultInputFolder" -ForegroundColor DarkGray
    $InputFolder = Read-Host "Pfad (Enter für Standard)"
    if ([string]::IsNullOrWhiteSpace($InputFolder)) {
        $InputFolder = $defaultInputFolder
    }
}

# Prüfen ob Input-Ordner existiert
if (-not (Test-Path -Path $InputFolder)) {
    Write-Error "Input-Ordner nicht gefunden: $InputFolder"
    exit 1
}

Write-Success "Input-Ordner: $InputFolder"
Write-Host ""

# CityGML-Dateien suchen
$gmlFiles = Get-ChildItem -Path $InputFolder -Filter "*.gml" -File
$xmlFiles = Get-ChildItem -Path $InputFolder -Filter "*.xml" -File
$allFiles = @($gmlFiles) + @($xmlFiles)

if ($allFiles.Count -eq 0) {
    Write-Error "Keine CityGML-Dateien (.gml, .xml) im Ordner gefunden!"
    exit 1
}

Write-Success "Gefunden: $($allFiles.Count) Datei(en)"
Write-Host ""

# Dateien anzeigen und auswählen lassen
Write-Step "Verfügbare CityGML-Dateien:"
for ($i = 0; $i -lt $allFiles.Count; $i++) {
    $file = $allFiles[$i]
    $sizeKB = [math]::Round($file.Length / 1KB, 2)
    Write-Host "  [$($i + 1)] $($file.Name) ($sizeKB KB)" -ForegroundColor White
}

Write-Host ""

# Auswahl
$selection = Read-Host "Datei auswählen (Nummer), 'all' für alle oder 'skip' zum Überspringen"

$selectedFiles = @()
if ($selection -eq "skip") {
    Write-Info "Import übersprungen - fahre mit Cleanup fort"
} elseif ($selection -eq "all") {
    $selectedFiles = $allFiles
    Write-Info "Importiere alle $($allFiles.Count) Dateien"
} else {
    try {
        $index = [int]$selection - 1
    } catch {
        Write-Error "Ungültige Auswahl!"
        exit 1
    }

    if ($index -lt 0 -or $index -ge $allFiles.Count) {
        Write-Error "Ungültige Auswahl!"
        exit 1
    }
    $selectedFiles = @($allFiles[$index])
    Write-Info "Importiere: $($selectedFiles[0].Name)"
}

Write-Host ""

# Prüfen ob Container läuft
Write-Step "Prüfe Docker Container..."

$citydbContainerId = (& docker-compose -f $ComposeFile ps -q $CityDbServiceName) 2>$null
if ([string]::IsNullOrWhiteSpace($citydbContainerId)) {
    Write-Error "Service '$CityDbServiceName' ist nicht gestartet oder nicht gefunden."
    Write-Info "Starte mit: docker-compose up -d $CityDbServiceName"
    exit 1
}

$isRunning = (docker inspect -f "{{.State.Running}}" $citydbContainerId 2>$null)
if ($isRunning -ne 'true') {
    Write-Error "Service '$CityDbServiceName' läuft nicht (ContainerId: $citydbContainerId)"
    Write-Info "Starte mit: docker-compose up -d $CityDbServiceName"
    exit 1
}

Write-Success "$CityDbServiceName läuft"

# citydb-tool wird on-demand per docker run gestartet (kein permanenter Container nötig)
Write-Info "Verwende citydb-tool für Import"
Write-Host ""

$successCount = 0
$errorCount = 0

if ($selectedFiles.Count -gt 0) {
    # Prüfe ob schon Features importiert sind
    Write-Step "Prüfe bereits importierte Features..."
    $existingCount = docker exec $citydbContainerId psql -U postgres -d postgres -t -c "SELECT COUNT(*) FROM citydb.feature;" 2>$null

    if ($existingCount -is [array]) {
        $existingCount = $existingCount[0]
    }
    $existingCount = $existingCount.Trim()

    if ($existingCount -and $existingCount -match '^\d+$' -and [int]$existingCount -gt 0) {
        Write-Info "Datenbank enthält bereits $existingCount Features"
        $continue = Read-Host "Trotzdem fortfahren? (j/n)"
        if ($continue -ne "j" -and $continue -ne "J") {
            Write-Info "Import abgebrochen"
            exit 0
        }
    }

    Write-Host ""
    Write-Step "Importiere CityGML-Dateien..."
    Write-Host ""

    foreach ($file in $selectedFiles) {
        Write-Info "Importiere: $($file.Name)"

        # Docker Volume Mount für citydb-tool
        $dockerInputFolder = $InputFolder.Replace('\\', '/')
        $containerPath = "/data/$($file.Name)"

        Write-Host "  Starte CityGML Import mit citydb-tool..." -ForegroundColor DarkGray

        $dockerArgs = @(
            'run', '--rm',
            '--network', $NetworkName,
            '-v', "${dockerInputFolder}:/data",
            '3dcitydb/citydb-tool',
            'import', 'citygml',
            '-H', $CityDbServiceName,
            '-d', $DatabaseName,
            '-u', $DatabaseUser,
            '-p', $DatabasePassword,
            $containerPath
        )

        Write-Host "  Befehl: docker $($dockerArgs -join ' ')" -ForegroundColor DarkGray

        try {
            & docker @dockerArgs

            if ($LASTEXITCODE -eq 0) {
                Write-Success "Import erfolgreich: $($file.Name)"
                $successCount++
            } else {
                Write-Error "Import fehlgeschlagen: $($file.Name) (Exit Code: $LASTEXITCODE)"
                $errorCount++
            }
        } catch {
            Write-Error "Fehler beim Import: $($file.Name)"
            Write-Error $_.Exception.Message
            $errorCount++
        }

        Write-Host ""
    }

    Write-Host "=============================================" -ForegroundColor Magenta
    Write-Host " Import abgeschlossen" -ForegroundColor Magenta
    Write-Host "=============================================" -ForegroundColor Magenta
    Write-Success "Erfolgreich: $successCount"
    if ($errorCount -gt 0) {
        Write-Error "Fehlgeschlagen: $errorCount"
    }
} else {
    Write-Info "Kein Import durchgeführt - überspringe zu Cleanup"
}

# Cleanup: Lösche Features außerhalb des Bereichs
Write-Host ""
Write-Step "Cleanup: Lösche Features außerhalb des Bereichs..."

$cleanupSql = "c:\_data\terrain_V5\import\building\Löschen_ausserhalb_bereich.sql"
if (Test-Path $cleanupSql) {
    Write-Info "Führe Cleanup-Script aus: $cleanupSql"

    try {
        docker cp "$cleanupSql" "${citydbContainerId}:/tmp/cleanup.sql"

        $cleanupArgs = @('exec', $citydbContainerId, 'psql', '-U', 'postgres', '-d', 'postgres', '-f', '/tmp/cleanup.sql')
        Write-Host "  Befehl: docker $($cleanupArgs -join ' ')" -ForegroundColor DarkGray
        & docker @cleanupArgs

        if ($LASTEXITCODE -eq 0) {
            Write-Success "Cleanup erfolgreich"
        } else {
            Write-Error "Cleanup fehlgeschlagen"
        }

        docker exec $citydbContainerId rm /tmp/cleanup.sql 2>$null
    } catch {
        Write-Error "Fehler beim Cleanup: $($_.Exception.Message)"
    }
} else {
    Write-Info "Cleanup-Script nicht gefunden, überspringe..."
}

# Gebäude-Anzahl prüfen
Write-Host ""
Write-Step "Prüfe Anzahl importierter Features..."

$countCmd = "docker exec $citydbContainerId psql -U postgres -d postgres -c `"SELECT COUNT(*) FROM citydb.feature;`""
Write-Host "  Befehl: $countCmd" -ForegroundColor DarkGray

try {
    & docker exec $citydbContainerId psql -U postgres -d postgres -c "SELECT COUNT(*) FROM citydb.feature;"
} catch {
    Write-Info "Konnte Feature-Anzahl nicht abrufen"
}

Write-Host ""
Write-Success "Script abgeschlossen!"
