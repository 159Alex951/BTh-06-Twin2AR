# =============================================================================
# fetch_bfs_data.ps1
# Holt BFS Gebaeude-Register Daten fuer alle EGIDs aus der 3DCityDB
# Quelle: api3.geo.admin.ch (GeoAdmin API - BFS Register)
# =============================================================================

param(
    [int]$BatchSize = 50,        # Anzahl paralleler API-Requests
    [int]$DelayMs = 100,         # Delay zwischen Batches (API Rate Limiting)
    [bool]$SkipExisting = $true  # Ueberspringe bereits vorhandene EGIDs
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "BFS Gebaeude-Register Import" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ComposeFile = Join-Path $RepoRoot 'docker-compose.yml'

$serviceName = 'citydb_pg'
$containerId = (& docker-compose -f $ComposeFile ps -q $serviceName) 2>$null
if ([string]::IsNullOrWhiteSpace($containerId)) {
    Write-Host "      FEHLER: Service '$serviceName' läuft nicht. Starte mit: docker-compose up -d $serviceName" -ForegroundColor Red
    exit 1
}

 # 1) Tabelle erstellen (falls noch nicht vorhanden)
Write-Host "`n[1/4] Erstelle BFS-Tabelle..." -ForegroundColor Yellow

$createTableScript = "c:\_data\terrain_V5\import\building\01_create_bfs_table.sql"
if (Test-Path $createTableScript) {
    docker cp $createTableScript "${containerId}:/tmp/create_bfs_table.sql"
    docker exec $containerId psql -U postgres -d postgres -f /tmp/create_bfs_table.sql
    Write-Host "      Tabelle erstellt/geprueft" -ForegroundColor Green
} else {
    Write-Host "      FEHLER: $createTableScript nicht gefunden!" -ForegroundColor Red
    exit 1
}

# 2) Alle EGIDs aus 3DCityDB holen
Write-Host "`n[2/4] Lade EGIDs aus 3DCityDB..." -ForegroundColor Yellow

$egidQuery = @"
SELECT DISTINCT p.val_int::text AS egid
FROM citydb.property p
WHERE p.name = 'EGID'
  AND p.val_int IS NOT NULL
ORDER BY egid;
"@

$egidResult = docker exec $containerId psql -U postgres -d postgres -t -A -c $egidQuery

if ($LASTEXITCODE -ne 0) {
    Write-Host "      FEHLER: Konnte EGIDs nicht laden!" -ForegroundColor Red
    exit 1
}

$allEgids = $egidResult -split "`n" | Where-Object { $_ -match '^\d+$' }

if ($allEgids.Count -eq 0) {
    Write-Host "      Keine EGIDs in der Datenbank gefunden!" -ForegroundColor Red
    exit 1
}

Write-Host "      $($allEgids.Count) EGIDs gefunden" -ForegroundColor Green

# 3) Bereits vorhandene EGIDs ueberspringen (optional)
if ($SkipExisting) {
    Write-Host "`n[3/4] Pruefe bereits vorhandene EGIDs..." -ForegroundColor Yellow
    
    $existingQuery = "SELECT egid FROM citydb.bfs_gebaeude_register;"
    $existingResult = docker exec $containerId psql -U postgres -d postgres -t -A -c $existingQuery
    
    $existingEgids = $existingResult -split "`n" | Where-Object { $_ -match '^\d+$' }
    
    Write-Host "      $($existingEgids.Count) EGIDs bereits vorhanden, werden uebersprungen" -ForegroundColor Yellow
    
    $egidsToFetch = $allEgids | Where-Object { $_ -notin $existingEgids }
} else {
    $egidsToFetch = $allEgids
}

if ($egidsToFetch.Count -eq 0) {
    Write-Host "`n      Alle EGIDs bereits vorhanden - nichts zu tun!" -ForegroundColor Green
    exit 0
}

Write-Host "      $($egidsToFetch.Count) EGIDs muessen abgerufen werden" -ForegroundColor Cyan

# 4) API-Daten holen und in DB speichern
Write-Host "`n[4/4] Hole BFS-Daten von GeoAdmin API..." -ForegroundColor Yellow

$baseUrl = "https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register"
$successCount = 0
$errorCount = 0
$totalCount = $egidsToFetch.Count

for ($i = 0; $i -lt $egidsToFetch.Count; $i += $BatchSize) {
    $batch = $egidsToFetch[$i..[Math]::Min($i + $BatchSize - 1, $egidsToFetch.Count - 1)]
    
    $batchNum = [Math]::Floor($i / $BatchSize) + 1
    $totalBatches = [Math]::Ceiling($egidsToFetch.Count / $BatchSize)
    
    Write-Host "`n      Batch $batchNum/$totalBatches (EGID $($i+1)-$($i+$batch.Count)/$totalCount)" -ForegroundColor Cyan
    
    # Parallele API-Requests
    $jobs = $batch | ForEach-Object {
        $egid = $_
        $url = "$baseUrl/${egid}_0?f=json&lang=de"
        
        Start-Job -ScriptBlock {
            param($url, $egid)
            try {
                $response = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 10
                return @{
                    egid = $egid
                    success = $true
                    data = $response
                }
            } catch {
                return @{
                    egid = $egid
                    success = $false
                    error = $_.Exception.Message
                }
            }
        } -ArgumentList $url, $egid
    }
    
    # Warte auf alle Jobs
    $results = $jobs | Wait-Job | Receive-Job
    $jobs | Remove-Job
    
    # Verarbeite Ergebnisse
    foreach ($result in $results) {
        if ($result.success) {
            $attrs = $result.data.attributes
            if (-not $attrs) {
                $attrs = $result.data.properties
            }
            if (-not $attrs -and $result.data.feature) {
                $attrs = $result.data.feature.attributes
            }
            
            if ($attrs) {
                # Extrahiere Felder (mit Fallbacks)
                $gbauj = if ($attrs.gbauj) { $attrs.gbauj } elseif ($attrs.GBAUJ) { $attrs.GBAUJ } else { "NULL" }
                $gbaup = if ($attrs.gbaup) { $attrs.gbaup } elseif ($attrs.GBAUP) { $attrs.GBAUP } else { "NULL" }
                $gkat = if ($attrs.gkat) { $attrs.gkat } elseif ($attrs.GKAT) { $attrs.GKAT } else { "NULL" }
                $ganzwhg = if ($attrs.ganzwhg) { $attrs.ganzwhg } elseif ($attrs.GANZWHG) { $attrs.GANZWHG } else { "NULL" }
                
                $strname = if ($attrs.strname) { $attrs.strname } else { $null }
                $deinr = if ($attrs.deinr) { $attrs.deinr } else { $null }
                $plz4 = if ($attrs.plz4) { $attrs.plz4 } else { $null }
                $gdename = if ($attrs.gdename) { $attrs.gdename } else { $null }
                
                $gkode = if ($attrs.gkode) { $attrs.gkode } else { "NULL" }
                $gkodn = if ($attrs.gkodn) { $attrs.gkodn } else { "NULL" }
                
                # Base64-encode JSON to avoid escaping issues
                $jsonRaw = $result.data | ConvertTo-Json -Depth 10 -Compress
                $jsonBytes = [System.Text.Encoding]::UTF8.GetBytes($jsonRaw)
                $jsonBase64 = [Convert]::ToBase64String($jsonBytes)
                
                # SQL mit Base64-decodiertem JSON
                $insertSql = @"
INSERT INTO citydb.bfs_gebaeude_register 
    (egid, gbauj, gbaup, gkat, ganzwhg, strname, deinr, plz4, gdename, gkode, gkodn, api_raw_json)
VALUES 
    ('$($result.egid)', $gbauj, $gbaup, $gkat, $ganzwhg, $(if ($strname) { "`$`$$($strname)`$`$" } else { "NULL" }), $(if ($deinr) { "`$`$$($deinr)`$`$" } else { "NULL" }), $(if ($plz4) { "`$`$$($plz4)`$`$" } else { "NULL" }), $(if ($gdename) { "`$`$$($gdename)`$`$" } else { "NULL" }), $gkode, $gkodn, convert_from(decode('$jsonBase64', 'base64'), 'UTF8')::jsonb)
ON CONFLICT (egid) DO UPDATE SET
    gbauj = EXCLUDED.gbauj,
    gbaup = EXCLUDED.gbaup,
    gkat = EXCLUDED.gkat,
    ganzwhg = EXCLUDED.ganzwhg,
    strname = EXCLUDED.strname,
    deinr = EXCLUDED.deinr,
    plz4 = EXCLUDED.plz4,
    gdename = EXCLUDED.gdename,
    gkode = EXCLUDED.gkode,
    gkodn = EXCLUDED.gkodn,
    api_raw_json = EXCLUDED.api_raw_json,
    fetched_at = NOW();
"@
                
                $insertResult = docker exec $containerName psql -U postgres -d postgres -c $insertSql 2>&1
                
                if ($LASTEXITCODE -eq 0) {
                    $successCount++
                    Write-Host "         EGID $($result.egid): OK (Baujahr: $gbauj)" -ForegroundColor Green
                } else {
                    $errorCount++
                    Write-Host "         EGID $($result.egid): SQL-Fehler - $insertResult" -ForegroundColor Red
                }
            } else {
                $errorCount++
                Write-Host "         EGID $($result.egid): Keine Attribute in API-Antwort" -ForegroundColor Yellow
            }
        } else {
            $errorCount++
            Write-Host "         EGID $($result.egid): API-Fehler - $($result.error)" -ForegroundColor Red
        }
    }
    
    # Rate Limiting
    if ($i + $BatchSize -lt $egidsToFetch.Count) {
        Start-Sleep -Milliseconds $DelayMs
    }
}

# 5) View erstellen
Write-Host "`n[5/5] Erstelle View..." -ForegroundColor Yellow

$viewScript = "c:\_data\terrain_V5\import\building\02_create_view_gebaeude_erweitert.sql"
if (Test-Path $viewScript) {
    docker cp $viewScript "${containerName}:/tmp/create_view.sql"
    docker exec $containerName psql -U postgres -d postgres -f /tmp/create_view.sql
    Write-Host "      View citydb.v_gebaeude_erweitert erstellt" -ForegroundColor Green
} else {
    Write-Host "      WARNUNG: $viewScript nicht gefunden!" -ForegroundColor Yellow
}

# Zusammenfassung
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Import abgeschlossen!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Erfolgreich: $successCount / $totalCount" -ForegroundColor Green
Write-Host "Fehler:      $errorCount / $totalCount" -ForegroundColor $(if ($errorCount -gt 0) { "Red" } else { "Green" })

# Finale Statistik
Write-Host "`nDatenbank-Statistik:" -ForegroundColor Yellow
$statsQuery = @"
SELECT 
    COUNT(*) AS total_gebaeude,
    COUNT(bfs.egid) AS mit_bfs_daten,
    COUNT(*) - COUNT(bfs.egid) AS ohne_bfs_daten
FROM citydb.v_gebaeude_erweitert bfs;
"@

docker exec $containerName psql -U postgres -d postgres -c $statsQuery

Write-Host "`nFertig! Nutze View: SELECT * FROM citydb.v_gebaeude_erweitert LIMIT 10;" -ForegroundColor Cyan
