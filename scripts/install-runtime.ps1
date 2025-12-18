\
$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".\venv\Scripts\Activate.ps1")) {
  throw "venv not found. Run scripts\bootstrap.ps1 first."
}

.\venv\Scripts\Activate.ps1

if (-not (Test-Path "requirements\lock\windows-runtime.txt")) {
  throw "Lockfile missing: requirements\lock\windows-runtime.txt. Run scripts\compile-locks.ps1 first (or commit lockfiles)."
}

python -m pip install -r requirements\lock\windows-runtime.txt
Write-Host "✅ Runtime deps installed." -ForegroundColor Green
