# =====================================================================
# Download portable Java JDK 21 (Windows x64) zonder admin / zonder MSI
# =====================================================================

$root = "C:\gh\MijnPythonScriptjes\CyNiT-tools"
$dest = Join-Path $root "jre21.zip"

$apiUrl  = "https://api.github.com/repos/adoptium/temurin21-binaries/releases/latest"
Write-Host "Ophalen release info van $apiUrl ..."
$release = Invoke-RestMethod -Uri $apiUrl

# Alleen Windows x64 JDK ZIP kiezen (NIET ARM / aarch64)
$asset = $release.assets | Where-Object {
    $_.name -like "OpenJDK21U-jdk_x64_windows_hotspot_*.zip"
} | Select-Object -First 1

if (-not $asset) {
    throw "Geen Windows x64 hotspot JDK 21 ZIP asset gevonden in de release."
}

Write-Host "Gevonden ZIP asset: $($asset.name)"
Write-Host "Download URL: $($asset.browser_download_url)"
Write-Host "Downloaden naar $dest ..."

Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dest

Write-Host "Klaar. ZIP staat op: $dest"
