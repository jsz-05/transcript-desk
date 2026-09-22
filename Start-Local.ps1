$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run Setup.ps1 first.' }
Push-Location $PSScriptRoot
try { & $python (Join-Path $PSScriptRoot 'app.py') } finally { Pop-Location }
