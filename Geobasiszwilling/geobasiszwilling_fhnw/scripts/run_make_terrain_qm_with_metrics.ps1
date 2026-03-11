param(
  [switch]$Force,
  [int]$SampleIntervalSeconds = 1
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot '..') | Select-Object -ExpandProperty Path
$TerrainDir = Join-Path $RepoRoot 'import\terrain'
$OutputDir = Join-Path $RepoRoot 'output\terrain_qm'
$MakeScript = Join-Path $RepoRoot 'scripts\make_terrain_qm_full.ps1'

$runId = Get-Date -Format 'yyyyMMdd_HHmmss'
$metricsDir = Join-Path $RepoRoot 'output\_metrics'
New-Item -ItemType Directory -Path $metricsDir -Force | Out-Null

$transcriptPath = Join-Path $metricsDir ("terrain_run_${runId}.transcript.txt")
$perfPath = Join-Path $metricsDir ("terrain_run_${runId}.perf.json")
$summaryPath = Join-Path $metricsDir ("terrain_run_${runId}.summary.json")

function Get-DirStats {
  param([Parameter(Mandatory)] [string]$Path)

  if (-not (Test-Path $Path)) {
    return [pscustomobject]@{ exists = $false; path = $Path; fileCount = 0; bytes = 0 }
  }

  $items = Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue
  $bytes = ($items | Measure-Object -Property Length -Sum).Sum
  [pscustomobject]@{
    exists = $true
    path = $Path
    fileCount = $items.Count
    bytes = [int64]$bytes
  }
}

function Get-FileStats {
  param([Parameter(Mandatory)] [string]$Path)

  if (-not (Test-Path $Path)) {
    return [pscustomobject]@{ exists = $false; path = $Path; bytes = 0 }
  }

  $fi = Get-Item -LiteralPath $Path -ErrorAction Stop
  [pscustomobject]@{ exists = $true; path = $Path; bytes = [int64]$fi.Length }
}

function BytesToGiB([int64]$bytes) {
  if ($bytes -le 0) { return 0 }
  return [math]::Round($bytes / 1GB, 3)
}

# --- Pre-run input metrics ---
$tifFiles = @(Get-ChildItem -LiteralPath $TerrainDir -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\.tif(f)?$' })
$inputTifBytes = 0
if ($tifFiles.Count -gt 0) {
  $inputTifBytes = [int64](($tifFiles | Measure-Object -Property Length -Sum).Sum)
}
$inputCsvFiles = @(Get-ChildItem -LiteralPath $TerrainDir -Filter '*.csv' -File -Force -ErrorAction SilentlyContinue)
$inputCsvLines = 0
foreach ($csv in $inputCsvFiles) {
  $lines = @(Get-Content -LiteralPath $csv.FullName -ErrorAction SilentlyContinue | Where-Object { $_ -and (-not $_.Trim().StartsWith('#')) })
  $inputCsvLines += $lines.Count
}

$logicalCores = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors

# Flag file to stop monitor job
$flagFile = Join-Path $metricsDir ("terrain_run_${runId}.monitoring.flag")
New-Item -ItemType File -Path $flagFile -Force | Out-Null

# Monitor system metrics using CIM/WMI (locale-independent)
$monitorJob = Start-Job -ArgumentList @($flagFile, $SampleIntervalSeconds, $perfPath, $logicalCores) -ScriptBlock {
  param($flag, $intervalSeconds, $outPath, $cores)
  $ErrorActionPreference = 'SilentlyContinue'

  $start = Get-Date
  $n = 0

  $maxCpuPct = 0
  $sumCpuPct = 0

  $maxMemPctCommitted = 0
  $sumMemPctCommitted = 0
  $maxCommittedBytes = 0
  $sumCommittedBytes = 0

  $maxDiskReadBps = 0
  $sumDiskReadBps = 0
  $maxDiskWriteBps = 0
  $sumDiskWriteBps = 0

  while (Test-Path $flag) {
    $n++

    $cpu = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'"
    $mem = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
    $disk = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'"

    $cpuPct = [double]$cpu.PercentProcessorTime
    $memPct = [double]$mem.PercentCommittedBytesInUse
    $committedBytes = [int64]$mem.CommittedBytes
    $readBps = [double]$disk.DiskReadBytesPersec
    $writeBps = [double]$disk.DiskWriteBytesPersec

    $sumCpuPct += $cpuPct
    if ($cpuPct -gt $maxCpuPct) { $maxCpuPct = $cpuPct }

    $sumMemPctCommitted += $memPct
    if ($memPct -gt $maxMemPctCommitted) { $maxMemPctCommitted = $memPct }

    $sumCommittedBytes += $committedBytes
    if ($committedBytes -gt $maxCommittedBytes) { $maxCommittedBytes = $committedBytes }

    $sumDiskReadBps += $readBps
    if ($readBps -gt $maxDiskReadBps) { $maxDiskReadBps = $readBps }

    $sumDiskWriteBps += $writeBps
    if ($writeBps -gt $maxDiskWriteBps) { $maxDiskWriteBps = $writeBps }

    Start-Sleep -Seconds $intervalSeconds
  }

  $end = Get-Date
  $result = [pscustomobject]@{
    startedAt = $start
    endedAt = $end
    durationSeconds = ($end - $start).TotalSeconds
    sampleIntervalSeconds = $intervalSeconds
    samples = $n
    logicalCores = $cores
    cpuPercent = [pscustomobject]@{
      max = [math]::Round($maxCpuPct, 1)
      avg = [math]::Round((($sumCpuPct / [math]::Max($n, 1))), 1)
    }
    ram = [pscustomobject]@{
      committedBytesMax = [int64]$maxCommittedBytes
      committedBytesAvg = [int64](($sumCommittedBytes / [math]::Max($n, 1)))
      committedPercentMax = [math]::Round($maxMemPctCommitted, 1)
      committedPercentAvg = [math]::Round((($sumMemPctCommitted / [math]::Max($n, 1))), 1)
    }
    disk = [pscustomobject]@{
      readBytesPerSecMax = [math]::Round($maxDiskReadBps, 0)
      readBytesPerSecAvg = [math]::Round((($sumDiskReadBps / [math]::Max($n, 1))), 0)
      writeBytesPerSecMax = [math]::Round($maxDiskWriteBps, 0)
      writeBytesPerSecAvg = [math]::Round((($sumDiskWriteBps / [math]::Max($n, 1))), 0)
    }
  }

  $result | ConvertTo-Json -Depth 6 | Out-File -FilePath $outPath -Encoding UTF8
  $result
}

# --- Run pipeline with transcript capture (Write-Host safe) ---
Start-Transcript -Path $transcriptPath -Force | Out-Null
try {
  Push-Location -Path $RepoRoot
  try {
    if ($Force) {
      & $MakeScript -Force
    } else {
      & $MakeScript
    }
  } finally {
    Pop-Location
  }
} finally {
  Stop-Transcript | Out-Null
  Remove-Item -LiteralPath $flagFile -Force -ErrorAction SilentlyContinue
}

# Ensure monitor job is done
Wait-Job $monitorJob | Out-Null
$perf = Receive-Job $monitorJob
Remove-Job $monitorJob | Out-Null

# --- Post-run stats ---
$outputStats = Get-DirStats -Path $OutputDir
$terrainDirStats = Get-DirStats -Path $TerrainDir

$terrainTileFiles = @()
if (Test-Path $OutputDir) {
  $terrainTileFiles = @(Get-ChildItem -LiteralPath $OutputDir -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Extension -ieq '.terrain' })
}

# Parse stage timings from transcript
$transcriptText = Get-Content -LiteralPath $transcriptPath -Raw -ErrorAction SilentlyContinue
$stage = [ordered]@{}

function TryParseSeconds([string]$pattern) {
  if ($transcriptText -match $pattern) {
    return [double]$Matches[1]
  }
  return $null
}

$stage.DownloadSeconds = TryParseSeconds 'Download abgeschlossen \(Dauer: ([0-9\.]+)s\)'
$stage.VrtSeconds = TryParseSeconds 'VRT erfolgreich erstellt \(Dauer: ([0-9\.]+)s\)'
$stage.QmTilingSeconds = TryParseSeconds 'QM-Tiling:\s+([0-9\.]+)s'
$stage.TotalSeconds = TryParseSeconds 'Gesamt:\s+([0-9\.]+)s'

$summary = [pscustomobject]@{
  runId = $runId
  transcriptPath = $transcriptPath
  perfPath = $perfPath
  stageSeconds = $stage
  system = [pscustomobject]@{
    logicalCores = $logicalCores
    cpuPercent = $perf.cpuPercent
    ram = [pscustomobject]@{
      committedMaxGiB = BytesToGiB ([int64]$perf.ram.committedBytesMax)
      committedPercentMax = $perf.ram.committedPercentMax
    }
    disk = [pscustomobject]@{
      readMaxMiBps = [math]::Round(([double]$perf.disk.readBytesPerSecMax) / 1MB, 2)
      writeMaxMiBps = [math]::Round(([double]$perf.disk.writeBytesPerSecMax) / 1MB, 2)
    }
  }
  input = [pscustomobject]@{
    terrainDir = $TerrainDir
    tifCount = $tifFiles.Count
    tifGiB = BytesToGiB ([int64]$inputTifBytes)
    csvCount = $inputCsvFiles.Count
    csvNonCommentLines = $inputCsvLines
    terrainDirTotalGiB = BytesToGiB $terrainDirStats.bytes
  }
  output = [pscustomobject]@{
    outputDir = $OutputDir
    totalGiB = BytesToGiB $outputStats.bytes
    fileCount = $outputStats.fileCount
    terrainTileCount = $terrainTileFiles.Count
  }
}

$summary | ConvertTo-Json -Depth 7 | Out-File -FilePath $summaryPath -Encoding UTF8

# Print concise human summary
"Stage times (s): Download=$($stage.DownloadSeconds) VRT=$($stage.VrtSeconds) QM=$($stage.QmTilingSeconds) Total=$($stage.TotalSeconds)" | Write-Host
"CPU %: avg=$($summary.system.cpuPercent.avg) max=$($summary.system.cpuPercent.max) (cores=$logicalCores)" | Write-Host
"RAM: committed max=$($summary.system.ram.committedMaxGiB) GiB (max %=$($summary.system.ram.committedPercentMax))" | Write-Host
"Disk peak MiB/s: read=$($summary.system.disk.readMaxMiBps) write=$($summary.system.disk.writeMaxMiBps)" | Write-Host
"Output: $($summary.output.totalGiB) GiB, files=$($summary.output.fileCount)" | Write-Host
"Input: TIFs=$($summary.input.tifCount) ($($summary.input.tifGiB) GiB), CSV lines=$($summary.input.csvNonCommentLines)" | Write-Host
"Saved summary: $summaryPath" | Write-Host
