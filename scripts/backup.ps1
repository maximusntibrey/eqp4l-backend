$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Force -Path "backups" | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dbOut = "backups/eqp4l-$stamp.dump"
$mediaOut = "backups/eqp4l-media-$stamp.zip"

$pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "eqp4l" }
$pgDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "eqp4l" }

# Use cmd.exe /c redirection to preserve exact binary bytes (PowerShell 5.1 '>' re-encodes binary output to UTF-16)
cmd.exe /c "docker compose exec -T db pg_dump -U $pgUser -Fc $pgDb > `"$dbOut`""
if ((Get-Item $dbOut).Length -le 0) { throw "Database backup is empty" }
Write-Host "Database backup written: $dbOut"

# Media and image volume backup (O2.2)
if (-not (Test-Path "media")) {
    New-Item -ItemType Directory -Force -Path "media" | Out-Null
}
if ((Get-ChildItem -Path "media" -Force | Measure-Object).Count -eq 0) {
    Set-Content -Path "media/.gitkeep" -Value ""
}
Compress-Archive -Path "media" -DestinationPath $mediaOut -Force
if ((Get-Item $mediaOut).Length -le 0) { throw "Media backup is empty" }
Write-Host "Media volume backup written: $mediaOut"
