\
$ErrorActionPreference = "Stop"

Set-Location -Path (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
  Write-Host "🧪 Creating venv..." -ForegroundColor Cyan
  python -m venv venv
}

Write-Host "✅ Activating venv..." -ForegroundColor Green
.\venv\Scripts\Activate.ps1

Write-Host "⬆ Upgrading pip + installing pip-tools..." -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install pip-tools

Write-Host ""
Write-Host "✅ Bootstrap done." -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  scripts\compile-locks.ps1   (if lockfiles are missing/outdated)"
Write-Host "  scripts\install-dev.ps1     (full workstation)"
Write-Host "  scripts\RUN_CYNiT.ps1       (start hub)"
