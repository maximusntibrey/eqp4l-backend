$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Force -Path "backups" | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$out = "backups/eqp4l-$stamp.dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > $out
if ((Get-Item $out).Length -le 0) { throw "Backup is empty" }
Write-Host "Backup written: $out"
