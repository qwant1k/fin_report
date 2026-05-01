# Runs backend pytest suite.
$ErrorActionPreference = 'Stop'

$Root       = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root 'backend'
$Venv       = Join-Path $BackendDir '.venv\Scripts\python.exe'
$SysPython  = 'C:\Program Files\Python312\python.exe'

if (Test-Path $Venv) { $PyExe = $Venv } else { $PyExe = $SysPython }

Push-Location $BackendDir
try {
    & $PyExe -m pytest -v tests
}
finally { Pop-Location }
