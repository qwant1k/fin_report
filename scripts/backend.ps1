# Starts FastAPI backend on http://localhost:8000.
# Falls back to system Python if venv is missing.
$ErrorActionPreference = 'Stop'

$Root       = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root 'backend'
$Venv       = Join-Path $BackendDir '.venv\Scripts\python.exe'
$SysPython  = 'C:\Program Files\Python312\python.exe'

if (Test-Path $Venv) {
    $PyExe = $Venv
} else {
    Write-Warning "venv not found, run scripts\install.ps1 first; using system Python"
    $PyExe = $SysPython
}

Push-Location $BackendDir
try {
    & $PyExe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
}
finally { Pop-Location }
