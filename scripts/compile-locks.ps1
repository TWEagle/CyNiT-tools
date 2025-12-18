\
$ErrorActionPreference = "Stop"

Set-Location -Path (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
  Write-Host "🧪 Creating venv..." -ForegroundColor Cyan
  python -m venv venv
}

.\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install pip-tools

New-Item -ItemType Directory -Force -Path "requirements\lock" | Out-Null

Write-Host "🔒 Compiling Windows lockfiles..." -ForegroundColor Cyan

# DEV (everything)
pip-compile --resolver=backtracking --upgrade `
  --output-file requirements\lock\windows-dev.txt `
  --constraint requirements\constraints.in `
  requirements\dev.in requirements\windows.in

# RUNTIME (what you need to run tools)
pip-compile --resolver=backtracking --upgrade `
  --output-file requirements\lock\windows-runtime.txt `
  --constraint requirements\constraints.in `
  requirements\base.in requirements\web.in requirements\desktop.in requirements\sharepoint.in requirements\windows.in

# BUILD (packaging only)
pip-compile --resolver=backtracking --upgrade `
  --output-file requirements\lock\windows-build.txt `
  --constraint requirements\constraints.in `
  requirements\build.in requirements\windows.in

Write-Host "✅ Done. Lockfiles written to requirements\lock\" -ForegroundColor Green
