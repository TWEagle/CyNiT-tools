# Start CyNiT Tools volledig verborgen
try {
    Start-Process "python.exe" "C:\gh\CyNiT-tools\CyNiT-tools\CyNiT-tools\ctools.py" -WindowStyle Hidden
}
catch {
    # Als er een fout is → toon foutmelding
    $msg = "CyNiT Tools kon niet starten:`n`n$($_.Exception.Message)"
    [System.Windows.Forms.MessageBox]::Show($msg, "Fout", 0, 16)
}
