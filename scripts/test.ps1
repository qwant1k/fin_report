$ErrorActionPreference = 'Stop'

$Root       = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root 'backend'
$Venv       = Join-Path $BackendDir '.venv\Scripts\python.exe'
$SysPython  = 'C:\Program Files\Python312\python.exe'

if (Test-Path $Venv) {
    $PyExe = $Venv
}
elseif (Test-Path $SysPython) {
    $PyExe = $SysPython
}
else {
    $PyExe = 'python'
}

Write-Host "[test] Project root: $Root"
Write-Host "[test] Backend dir : $BackendDir"
Write-Host "[test] Python      : $PyExe"
Write-Host "[test] Starting pytest. This may take 10-30 seconds..."

Push-Location $BackendDir
try {
    & $PyExe -m pytest tests -q -ra --tb=short --durations=20
    if ($LASTEXITCODE -ne 0) {
        throw "pytest failed with exit code $LASTEXITCODE"
    }
    Write-Host "[test] OK"
}
finally { Pop-Location }
