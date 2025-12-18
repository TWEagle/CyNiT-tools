\
$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".\venv\Scripts\Activate.ps1")) {
  Write-Host "venv not found -> running bootstrap..." -ForegroundColor Yellow
  & .\scripts\bootstrap.ps1
}

.\venv\Scripts\Activate.ps1

# Optional: install runtime deps if lockfile exists but packages missing.
# We keep this lightweight; you can run install-dev.ps1 when needed.
if (Test-Path "requirements\lock\windows-runtime.txt") {
  # quick check for Flask
  $hasFlask = python -c "import importlib.util; import sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing runtime deps (lockfile)..." -ForegroundColor Cyan
    python -m pip install -r requirements\lock\windows-runtime.txt
  }
}

# Start server in a separate process so we can open browser
Write-Host "🚀 Starting CyNiT Tools..." -ForegroundColor Green
$proc = Start-Process -FilePath ".\venv\Scripts\python.exe" -ArgumentList ".\ctools.py" -WorkingDirectory (Get-Location) -PassThru

# Give Flask a moment, then open browser
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:5000/"

Write-Host "✅ CyNiT Tools started. PID=$($proc.Id)" -ForegroundColor Green
Write-Host "Tip: stop it with Ctrl+C in the console where it's running, or kill PID $($proc.Id)."
