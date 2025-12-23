
# Start-ctools.ps1
# - Genereer/renew self-signed cert (SAN: localhost + 127.0.0.1, EKU: ServerAuth)
# - Trust in CurrentUser\Root (zonder admin, met duplicate-check)
# - Start watcher (pythonw.exe) en open browser op https://localhost:5000
# - Voeg PowerShell alias 'ctools' toe (opent https://localhost:5000)

$ErrorActionPreference = "Stop"
try { chcp 65001 | Out-Null } catch {}

# ====== PAD-INSTELLINGEN ======
$BaseDir         = "C:\gh\CyNiT-tools"
$RepoDir         = "C:\gh\CyNiT-tools\CyNiT-tools"
$PythonExe       = Join-Path $RepoDir "venv\Scripts\python.exe"
$PythonwExe      = Join-Path $RepoDir "venv\Scripts\pythonw.exe"
$PipExe          = Join-Path $RepoDir "venv\Scripts\pip.exe"
$WatcherScript   = Join-Path $BaseDir "ctools_tray_run.py"

$CertPem         = Join-Path $BaseDir "cert.pem"        # alleen CERT (PEM)
$KeyPem          = Join-Path $BaseDir "key.pem"         # private key (PEM)
$CertCrt         = Join-Path $BaseDir "localhost.crt"   # convenience voor certutil

$MaxDays         = 30
$RenewBeforeDays = 20
$FlaskPort       = 5000

# ====== HELPERS ======
function Ensure-Cryptography {
    # Installeer cryptography in venv indien ontbreekt
    & $PythonExe -c "import cryptography" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "📦 Installing 'cryptography' in venv..." -ForegroundColor Cyan
        & $PipExe install cryptography | Out-Host
    }
}

function Get-CertExpiry {
    param([string]$certFile)
    if (-not (Test-Path $certFile)) { return $null }
    try {
        # PowerShell (Core/.NET 6+) kan PEM direct laden; zo niet, val terug op certutil
        $cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certFile)
        return $cert.NotAfter
    } catch {
        try {
            $dump = certutil -dump $certFile 2>$null
            $line = ($dump -split "`n" | Where-Object { $_ -match "NotAfter" })[0]
            if ($line) {
                $dateText = $line -replace ".*NotAfter: ",""
                return [DateTime]::Parse($dateText)
            }
        } catch { }
        return $null
    }
}

function Get-CertThumbprint {
    param([string]$certFile)
    try {
        $c = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certFile)
        return $c.Thumbprint
    } catch {
        return $null
    }
}

function New-PythonSelfSignedCert {
    param([string]$certPath, [string]$keyPath, [int]$days)

    $py = @"
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Private key
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

# Subject/Issuer
subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u'localhost')])

# SAN: localhost + 127.0.0.1
san = x509.SubjectAlternativeName([
    x509.DNSName(u'localhost'),
    x509.IPAddress(IPv4Address('127.0.0.1')),
])

# EKU: TLS Web Server Authentication
eku = x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH])

# Cert bouwen
cert = (x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.utcnow())
    .not_valid_after(datetime.utcnow() + timedelta(days=@DAYS@))
    .add_extension(san, critical=False)
    .add_extension(eku, critical=False)
    .sign(key, hashes.SHA256())
)

# Schrijf key (PEM, zonder pass)
with open(r'@KEY@', 'wb') as f:
    f.write(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()
    ))

# Schrijf cert (PEM)
with open(r'@CERT@', 'wb') as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
"@
    $py = $py.Replace("@CERT@", $certPath).Replace("@KEY@", $keyPath).Replace("@DAYS@", $days.ToString())
    & $PythonExe -c $py
    if ($LASTEXITCODE -ne 0) { throw "Python cert generation failed." }
}

function Ensure-TrustedCurrentUserRoot {
    param([string]$certPemPath, [string]$crtPath)

    # Kopieer PEM naar .crt (zelfde Base64 X.509, handige extensie voor certutil)
    Copy-Item $certPemPath $crtPath -Force

    # Duplicate-check op thumbprint (als mogelijk)
    $thumb = Get-CertThumbprint -certFile $certPemPath
    $exists = $false
    try {
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root","CurrentUser")
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
        if ($thumb) {
            $exists = $store.Certificates | Where-Object { $_.Thumbprint -eq $thumb } | ForEach-Object { $true } | Select-Object -First 1
            if (-not $exists) { $exists = $false }
        }
        $store.Close()
    } catch { $exists = $false }

    if ($exists) {
        Write-Host "🔏 Cert al aanwezig in CurrentUser\Root (thumbprint match)." -ForegroundColor Green
    } else {
        Write-Host "🔏 Import into CurrentUser\Root..." -ForegroundColor Cyan
        certutil -user -addstore Root $crtPath | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Host "⚠️  Trusten gaf een fout (mogelijk al aanwezig onder andere thumbprint)." -ForegroundColor Yellow
        } else {
            Write-Host "✅ Cert toegevoegd aan CurrentUser\Root." -ForegroundColor Green
        }
    }
}

function Ensure-CtoolsAlias {
    # Zorg dat je 'ctools' kunt typen in elke PowerShell om browser te openen
    $profilePath = $PROFILE
    if (-not (Test-Path $profilePath)) {
        New-Item -ItemType File -Path $profilePath -Force | Out-Null
    }

    $aliasLine = 'function ctools { Start-Process "https://localhost:5000/"; }'
    $profileText = Get-Content $profilePath -Raw
    if ($profileText -notmatch 'function\s+ctools') {
        Add-Content $profilePath "`n$aliasLine`n"
        Write-Host "✅ Alias 'ctools' toegevoegd aan $profilePath (herstart PowerShell om te gebruiken)." -ForegroundColor Green
    } else {
        Write-Host "ℹ️  Alias 'ctools' bestaat al in je profiel." -ForegroundColor Yellow
    }
}

# ====== CERTIFICATE FLOW ======
Ensure-Cryptography

$renewCert = $false
if (-not (Test-Path $CertPem) -or -not (Test-Path $KeyPem)) {
    $renewCert = $true
} else {
    $expiry = Get-CertExpiry -certFile $CertPem
    if ($expiry -eq $null) {
        $renewCert = $true
    } else {
        $daysLeft = [math]::Floor(($expiry - (Get-Date)).TotalDays)
        Write-Host "📅 Cert vervalt over $daysLeft dagen."
        if ($daysLeft -lt $RenewBeforeDays -or $daysLeft -gt $MaxDays) {
            $renewCert = $true
        }
    }
}

if ($renewCert) {
    Write-Host "🔒 (Re)generating self-signed cert (SAN localhost + 127.0.0.1, EKU serverAuth, max $MaxDays d)..." -ForegroundColor Cyan
    if (Test-Path $CertPem) { Remove-Item $CertPem -Force }
    if (Test-Path $KeyPem)  { Remove-Item $KeyPem -Force }
    New-PythonSelfSignedCert -certPath $CertPem -keyPath $KeyPem -days $MaxDays
    Write-Host "✅ Cert aangemaakt." -ForegroundColor Green
} else {
    Write-Host "🔒 Bestaand cert nog voldoende geldig, geen renew nodig." -ForegroundColor Green
}

Ensure-TrustedCurrentUserRoot -certPemPath $CertPem -crtPath $CertCrt

# ====== WATCHER STARTEN ======
Write-Host "🚀 Start watcher (tray)..." -ForegroundColor Green
Start-Process -FilePath $PythonwExe -ArgumentList "`"$WatcherScript`"" -WorkingDirectory $BaseDir -WindowStyle Hidden

# ====== BROWSER OPENEN NAAR HTTPS ======
Start-Sleep -Seconds 2
Start-Process "https://localhost:$FlaskPort/"

# ====== ALIAS 'ctools' ======
Ensure-CtoolsAlias

Write-Host "✅ Klaar. Gebruik 'ctools' in PowerShell om de hub te openen, of via Startmenu." -ForegroundColor Green
