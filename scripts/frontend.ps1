# Starts Vite dev server on http://localhost:5173.
$ErrorActionPreference = 'Stop'

$Root     = Split-Path -Parent $PSScriptRoot
$FrontDir = Join-Path $Root 'frontend'
$Npm      = 'C:\Program Files\nodejs\npm.cmd'

Push-Location $FrontDir
try {
    & $Npm run dev
}
finally { Pop-Location }
