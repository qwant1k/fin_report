# Installs backend Python deps + frontend npm deps.
# Uses absolute paths to Python 3.12 and Node, since PATH is not configured.
$ErrorActionPreference = 'Stop'

$Root      = Split-Path -Parent $PSScriptRoot
$Python    = 'C:\Program Files\Python312\python.exe'
$Npm       = 'C:\Program Files\nodejs\npm.cmd'
$BackendDir = Join-Path $Root 'backend'
$FrontDir   = Join-Path $Root 'frontend'
$VenvDir    = Join-Path $BackendDir '.venv'

Write-Host '── Backend: creating venv ──' -ForegroundColor Cyan
if (-not (Test-Path $VenvDir)) {
    & $Python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}

$VenvPip    = Join-Path $VenvDir 'Scripts\pip.exe'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

Write-Host '── Backend: pip install ──' -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
& $VenvPip install -r (Join-Path $BackendDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host '── Frontend: npm install ──' -ForegroundColor Cyan
Push-Location $FrontDir
try {
    & $Npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
}
finally { Pop-Location }

Write-Host '✔ All dependencies installed' -ForegroundColor Green
