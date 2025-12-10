param(
    [Parameter(Mandatory=$true)]
    [string]$ZipPath,
    [string]$TargetRoot = "C:\gh\MijnPythonScriptjes"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $ZipPath)) {
    throw "Zipbestand niet gevonden: $ZipPath"
}

if (!(Test-Path $TargetRoot)) {
    New-Item -ItemType Directory -Path $TargetRoot | Out-Null
}

Write-Host "Uitpakken naar $TargetRoot..."
Expand-Archive -Path $ZipPath -DestinationPath $TargetRoot -Force

# Zoek de uitgepakte map (cynit_bundle_xxx)
$bundleDir = Get-ChildItem $TargetRoot -Directory |
    Where-Object { $_.Name -like "cynit_bundle_*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $bundleDir) { throw "Geen cynit_bundle_* map gevonden in $TargetRoot" }

$cyNitDir = Join-Path $bundleDir.FullName "CyNiT-tools"
$spytDir  = Join-Path $bundleDir.FullName "SP-YT"

if (!(Test-Path $cyNitDir)) { throw "CyNiT-tools map niet gevonden in bundle." }
if (!(Test-Path $spytDir))  { throw "SP-YT map niet gevonden in bundle." }

Write-Host "Installeren naar vaste paden onder $TargetRoot..."
$finalCyNit = Join-Path $TargetRoot "CyNiT-tools"
$finalSpyt  = Join-Path $TargetRoot "SP-YT"

if (Test-Path $finalCyNit) { Remove-Item -Recurse -Force $finalCyNit }
if (Test-Path $finalSpyt)  { Remove-Item -Recurse -Force $finalSpyt }

Move-Item $cyNitDir $finalCyNit
Move-Item $spytDir  $finalSpyt

# venv voor CyNiT-tools
Write-Host "Venv voor CyNiT-tools..."
Push-Location $finalCyNit
python -m venv venv
.\venv\Scripts\activate
if (Test-Path (Join-Path $bundleDir.FullName "requirements_cynit.txt")) {
    pip install -r (Join-Path $bundleDir.FullName "requirements_cynit.txt")
}
deactivate
Pop-Location

# venv voor SP-YT (optioneel)
Write-Host "Venv voor SP-YT..."
Push-Location $finalSpyt
python -m venv venv
.\venv\Scripts\activate
if (Test-Path (Join-Path $bundleDir.FullName "requirements_spyt.txt")) {
    pip install -r (Join-Path $bundleDir.FullName "requirements_spyt.txt")
}
deactivate
Pop-Location

Write-Host "Installatie klaar. CyNiT-tools: $finalCyNit  SP-YT: $finalSpyt"
