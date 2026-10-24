# Upload the app from this Windows PC to a Linux server and (re)install it.
# Usage: powershell -File deploy\aliyun\deploy.ps1 -Server 1.2.3.4 [-User root] [-Key path\to\key]
param(
  [Parameter(Mandatory = $true)][string]$Server,
  [string]$User = "root",
  [string]$Key = "",
  # Set when nginx already serves other sites on port 80: the public IP or domain this app answers to
  [string]$ServerName = ""
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

if (-not (Test-Path "frontend\dist\index.html")) {
  Push-Location frontend; npm install --no-audit --no-fund; npm run build; Pop-Location
}

$tar = Join-Path $env:TEMP "chadedao.tar.gz"
tar -czf $tar --exclude=__pycache__ backend frontend/dist requirements.txt deploy .env
$opts = @("-o", "StrictHostKeyChecking=accept-new")
if ($Key) { $opts += @("-i", $Key) }
scp @opts $tar "${User}@${Server}:/tmp/chadedao.tar.gz"
ssh @opts "${User}@${Server}" "rm -rf /tmp/chadedao && mkdir -p /tmp/chadedao && tar -xzf /tmp/chadedao.tar.gz -C /tmp/chadedao && cd /tmp/chadedao && sudo SERVER_NAME='$ServerName' bash deploy/aliyun/setup.sh"
if ($LASTEXITCODE -ne 0) { Write-Host "Deploy failed (see above)"; exit 1 }
Write-Host "Open http://$(if ($ServerName) { $ServerName } else { $Server })"
