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
# The bundle carries .env (API keys): upload it into a directory only we can read, and delete it
# afterwards whether or not setup succeeded.
# mktemp makes a fresh 0700 directory nobody else can have planted; the rm clears bundles older deploys left behind.
$remote = (ssh @opts "${User}@${Server}" "rm -rf /tmp/chadedao /tmp/chadedao.tar.gz; mktemp -d /tmp/chadedao.XXXXXXXX" | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0 -or -not $remote) { Remove-Item $tar -Force; Write-Host "Could not reach the server"; exit 1 }
$remote = $remote.Trim()
scp @opts $tar "${User}@${Server}:$remote/app.tar.gz"
$scpExit = $LASTEXITCODE
Remove-Item $tar -Force
if ($scpExit -ne 0) { Write-Host "Upload failed"; exit 1 }
ssh @opts "${User}@${Server}" "cd $remote && tar -xzf app.tar.gz && sudo SERVER_NAME='$ServerName' bash deploy/aliyun/setup.sh; code=`$?; cd / && rm -rf $remote; exit `$code"
if ($LASTEXITCODE -ne 0) { Write-Host "Deploy failed (see above)"; exit 1 }
Write-Host "Open http://$(if ($ServerName) { $ServerName } else { $Server })"
