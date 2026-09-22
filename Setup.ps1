param(
    [string]$Python = 'py',
    [switch]$SkipModels,
    [switch]$SkipServiceWrapper
)
$ErrorActionPreference = 'Stop'
$appRoot = $PSScriptRoot
if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Stop the existing app/service before running setup. Setup initializes the job database.'
}
$pythonArgs = if ([IO.Path]::GetFileNameWithoutExtension($Python) -eq 'py') { @('-3.12') } else { @() }
& $Python @pythonArgs -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P')==8, 'Python 3.12 x64 is required'"
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64 or pass -Python with its full executable path.' }
$venvPython = Join-Path $appRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python @pythonArgs -m venv (Join-Path $appRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
}
& $venvPython -m pip install -r (Join-Path $appRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Push-Location $appRoot
try {
    & $venvPython -c 'import store; store.initialize()'
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize app data.' }
    if (-not $SkipModels) {
        & $venvPython -c "from faster_whisper.utils import download_model; import store; download_model('base', output_dir=str(store.DATA / 'models' / 'base'))"
        if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Retry setup before loading the model.' }
    }
} finally { Pop-Location }
if (-not $SkipServiceWrapper) {
    $wrapper = Join-Path $appRoot 'TranscriptDeskService.exe'
    $expected = '05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA'
    if (-not (Test-Path -LiteralPath $wrapper)) {
        Invoke-WebRequest 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe' -OutFile $wrapper
    }
    if ((Get-FileHash -LiteralPath $wrapper -Algorithm SHA256).Hash -ne $expected) {
        throw 'The service wrapper checksum does not match WinSW 2.12.0. Do not run it.'
    }
    $config = Join-Path $appRoot 'TranscriptDeskService.xml'
    if (-not (Test-Path -LiteralPath $config)) {
        Copy-Item -LiteralPath (Join-Path $appRoot 'service\TranscriptDeskService.xml') -Destination $config
    }
}
Write-Output 'Setup complete. Credentials are in data\ACCESS.txt; keep that file private.'
Write-Output 'Start locally: powershell -ExecutionPolicy Bypass -File .\Start-Local.ps1'
Write-Output 'Setup does not install a service, change sleep settings, or expose a network port.'
