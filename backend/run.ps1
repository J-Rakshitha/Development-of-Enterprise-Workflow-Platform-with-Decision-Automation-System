# Start the FastAPI backend
$VenvPython = "C:\Users\akula\venv\coord-engine\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $VenvPython) {
        Write-Host "Python not found. Install Python 3.11+ and retry."
        exit 1
    }
    Write-Host "Using system Python: $VenvPython"
}

# Kill any stale/hung server still holding port 8000
Write-Host "Clearing port 8000 ..."
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { if ($_ -gt 0) { taskkill /PID $_ /F 2>$null } }
Start-Sleep -Seconds 2

Set-Location $PSScriptRoot
Write-Host "Starting backend on http://127.0.0.1:8000 ..."
Write-Host "Press Ctrl+C to stop."
& $VenvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
