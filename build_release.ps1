param(
    [Parameter(Mandatory=$true)]
    [string]$Version,              # bv. 1.0.0
    [string]$BundleName = "cynit_bundle"
)

$ErrorActionPreference = "Stop"

Write-Host "=== CyNiT Build & Release $Version ==="

# 1. Controleren op on-gecommitte wijzigingen
$gitStatus = git status --porcelain
if ($gitStatus) {
    Write-Warning "Er zijn on-gecommitte wijzigingen:"
    $gitStatus
    Write-Warning "Maak eerst een commit voor je een release bouwt."
    throw "Working tree is niet clean."
}

# 2. Export script draaien
Write-Host "== Export bundle =="
$exportScript = Join-Path $PSScriptRoot "export-cynit.ps1"
if (!(Test-Path $exportScript)) {
    throw "export-cynit.ps1 niet gevonden in $PSScriptRoot"
}

& $exportScript -BundleName $BundleName
# Zoek de meest recente zip in .\dist
$distDir = Join-Path $PSScriptRoot "dist"
$zip = Get-ChildItem $distDir -Filter "*.zip" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $zip) { throw "Geen zip gevonden in $distDir" }

Write-Host "Bundle: $($zip.FullName)"

# 3. Git tag aanmaken
$tagName = "v$Version"
Write-Host "== Nieuwe tag: $tagName =="
git tag $tagName
git push origin $tagName

# 4. GitHub Release via gh CLI
Write-Host "== GitHub Release aanmaken =="
$releaseTitle = "CyNiT Tools $Version"
$releaseNotes = "Automatisch gebouwde release voor versie $Version."

gh release create $tagName `
  "$($zip.FullName)" `
  --title "$releaseTitle" `
  --notes "$releaseNotes"

Write-Host "== Klaar! Release $tagName gepubliceerd. =="
