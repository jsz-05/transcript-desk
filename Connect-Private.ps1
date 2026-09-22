$ErrorActionPreference='Stop'
$tailscale='C:\Program Files\Tailscale\tailscale.exe'
$state = (& $tailscale status --json | ConvertFrom-Json)
if ($state.BackendState -ne 'Running') { throw 'Sign in to Tailscale first, then run this script again.' }
$dns = $state.Self.DNSName.TrimEnd('.')
if (-not $dns) { throw 'Enable MagicDNS in Tailscale, then try again.' }
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'data') | Out-Null
@{hosts=@($dns)+@($state.TailscaleIPs)} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'data\network.json') -Encoding utf8
& $tailscale set --unattended=true
if ($LASTEXITCODE -ne 0) { throw 'Could not enable unattended Tailscale. Try running PowerShell as administrator.' }
& $tailscale serve --bg --https=443 http://127.0.0.1:8765
if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve is not enabled yet. Follow the setup link it printed.' }
"https://$dns/" | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'data\private-url.txt')
Write-Output "App: https://$dns/"
Write-Output "MCP: https://$dns/mcp/"
