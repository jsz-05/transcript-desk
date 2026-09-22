$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
$admin = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this script as administrator to install automatic startup.' }
New-Item -ItemType Directory -Force -Path (Join-Path $appRoot 'data') | Out-Null
$wrapper = Join-Path $appRoot 'TranscriptDeskService.exe'
if (-not (Test-Path -LiteralPath $wrapper)) { throw 'Run Setup.ps1 first to download the service wrapper.' }
if (-not (Test-Path -LiteralPath (Join-Path $appRoot '.venv\pyvenv.cfg'))) { throw 'Run Setup.ps1 first to create the Python environment.' }
Start-Transcript -LiteralPath (Join-Path $appRoot 'data\install.log') -Force
try {
    $existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if ($existing -and -not (Get-Service TranscriptDesk -ErrorAction SilentlyContinue)) {
        $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($existing.OwningProcess)"
        if ($existingProcess.ExecutablePath -like '*python*' -and $existingProcess.CommandLine -match [regex]::Escape((Join-Path $appRoot 'app.py'))) {
            Stop-Process -Id $existing.OwningProcess
        } else { throw 'Port 8765 is occupied by another application.' }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $appRoot 'data\logs') | Out-Null
    # Read access only to application code and the bundled runtime; write access only to app data.
    & icacls.exe $appRoot /grant '*S-1-5-19:(OI)(CI)RX' /T /Q | Out-Null
    & icacls.exe (Join-Path $appRoot 'data') /grant '*S-1-5-19:(OI)(CI)M' /T /Q | Out-Null
    $venvConfig = Get-Content -LiteralPath (Join-Path $appRoot '.venv\pyvenv.cfg')
    $runtimePath = (($venvConfig | Where-Object { $_ -like 'home = *' }) -replace '^home = ', '').Trim()
    if (-not (Test-Path -LiteralPath (Join-Path $runtimePath 'python.exe'))) { throw 'Python runtime not found.' }
    & icacls.exe $runtimePath /grant '*S-1-5-19:(OI)(CI)RX' /T /Q | Out-Null
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $nodeExe = if ($env:TRANSCRIPT_NODE_PATH) { $env:TRANSCRIPT_NODE_PATH } elseif ($nodeCommand) { $nodeCommand.Source } else { Join-Path (Split-Path $runtimePath -Parent) 'node\bin\node.exe' }
    if (Test-Path -LiteralPath $nodeExe) {
        & icacls.exe (Split-Path $nodeExe -Parent) /grant '*S-1-5-19:(OI)(CI)RX' /T /Q | Out-Null
        [xml]$serviceXml = Get-Content -LiteralPath (Join-Path $appRoot 'TranscriptDeskService.xml')
        $nodeSetting = $serviceXml.service.env | Where-Object { $_.name -eq 'TRANSCRIPT_NODE_PATH' }
        if (-not $nodeSetting) {
            $nodeSetting = $serviceXml.CreateElement('env')
            $nodeSetting.SetAttribute('name', 'TRANSCRIPT_NODE_PATH')
            [void]$serviceXml.service.AppendChild($nodeSetting)
        }
        $nodeSetting.SetAttribute('value', $nodeExe)
        $serviceXml.Save((Join-Path $appRoot 'TranscriptDeskService.xml'))
    }
    if (-not (Get-Service TranscriptDesk -ErrorAction SilentlyContinue)) {
        & $wrapper install
        if ($LASTEXITCODE -ne 0) { throw 'Service installation failed.' }
    }
    Start-Service TranscriptDesk
    # Keep the server awake on AC power; preserve the original timeout for reversal.
    if (-not (Test-Path -LiteralPath (Join-Path $appRoot 'data\power-before.txt'))) {
        & powercfg.exe /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE | Set-Content -LiteralPath (Join-Path $appRoot 'data\power-before.txt')
    }
    & powercfg.exe /change standby-timeout-ac 0
    'Automatic startup installed.' | Set-Content -LiteralPath (Join-Path $appRoot 'data\startup-ready.txt')
} finally { Stop-Transcript }
