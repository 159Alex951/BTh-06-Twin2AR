# PowerShell-Skript zur Umwandlung von LV95 (CH1903+) nach WGS84 und Export nach output/

$input = "c:\_data\terrain_V5\import\point\2021_Fixpunkte_FHNW.csv"
$output = "c:\_data\terrain_V5\output\point\2021_Fixpunkte_FHNW_wgs84.csv"
$geojson = "c:\_data\terrain_V5\output\point\2021_Fixpunkte_FHNW_wgs84.geojson"

function Convert-LV95ToWGS84($E, $N) {
    $y = ($E - 2600000) / 1000000
    $x = ($N - 1200000) / 1000000
    $lat = 16.9023892 + 3.238272 * $x - 0.270978 * $y * $y - 0.002528 * $x * $x - 0.0447 * $y * $y * $x - 0.0140 * $x * $x * $x
    $lon = 2.6779094 + 4.728982 * $y + 0.791484 * $y * $x + 0.1306 * $y * $y * $y - 0.0436 * $y * $x * $x
    $lat = $lat * 100 / 36
    $lon = $lon * 100 / 36
    return @($lon, $lat)
}

# CSV einlesen, umrechnen und speichern

# Daten einlesen und umrechnen
$punkte = Import-Csv $input -Delimiter "," | ForEach-Object {
    if ($_.E -and $_.N) {
        $coords = Convert-LV95ToWGS84 $_.E $_.N
        $_ | Add-Member -NotePropertyName "Lon" -NotePropertyValue $coords[0]
        $_ | Add-Member -NotePropertyName "Lat" -NotePropertyValue $coords[1]
    }
    $_
}

# Als CSV speichern
$punkte | Export-Csv $output -NoTypeInformation -Delimiter ";"

# GeoJSON erzeugen
$features = @()
foreach ($p in $punkte) {
    if ($p.Lon -and $p.Lat) {
        $props = @{}
        foreach ($k in $p.PSObject.Properties.Name) {
            if ($k -ne "Lon" -and $k -ne "Lat") { $props[$k] = $p.$k }
        }
        $feature = [ordered]@{
            type = "Feature"
            geometry = @{ type = "Point"; coordinates = @([double]$p.Lon, [double]$p.Lat, [double]$p.H) }
            properties = $props
        }
        $features += $feature
    }
}
$geojsonObj = [ordered]@{
    type = "FeatureCollection"
    features = $features
}
$geojsonText = $geojsonObj | ConvertTo-Json -Depth 6
Set-Content -Path $geojson -Value $geojsonText -Encoding UTF8

Write-Host "Fertig! Neue Dateien: $output und $geojson"