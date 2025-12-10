param(
    [string]$InstallRoot = "C:\gh\MijnPythonScriptjes",
    [string]$ReleaseUrl  = "https://github.com/TWEagle/CyNiT-tools/releases/latest/download/cynit_bundle.zip"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $InstallRoot)) {
    New-Item -ItemType Directory -Path $InstallRoot | Out-Null
}

$tempZip = Join-Path $env:TEMP "cynit_bundle_latest.zip"
Write-Host "Download release van $ReleaseUrl..."
Invoke-WebRequest -Uri $ReleaseUrl -OutFile $tempZip

Write-Host "Run import-cynit.ps1..."
$importScript = Join-Path $InstallRoot "import-cynit.ps1"
if (!(Test-Path $importScript)) {
    throw "import-cynit.ps1 niet gevonden in $InstallRoot. Kopieer dit script mee in je repo of laat de installer het eerst ophalen."
}

& $importScript -ZipPath $tempZip -TargetRoot $InstallRoot

Write-Host "Installatie klaar."
