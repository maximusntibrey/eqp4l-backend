<#
 Windows helper. Usage: .\scripts\dev.ps1 <up|down|logs|check|test|shell|migrate|reset-db>
 Needs Docker Desktop. Creates .env from .env.example on first use.
#>
param([Parameter(Position = 0)][string]$Task = "up")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example (local-only values)." }
switch ($Task) {
    "up"       { docker compose up -d --build; Write-Host "API: http://localhost:8000/health/" }
    "down"     { docker compose down }
    "logs"     { docker compose logs -f web }
    "check"    { docker compose run --rm web bash scripts/check.sh }
    "test"     { docker compose run --rm web pytest }
    "shell"    { docker compose run --rm web python manage.py shell }
    "migrate"  { docker compose run --rm web python manage.py migrate }
    "reset-db" {
        $answer = Read-Host "This DELETES the local database volume. Type YES to continue"
        if ($answer -ne "YES") { Write-Host "Cancelled."; return }
        docker compose down --volumes
        docker compose up -d --build
    }
    default    { Write-Error "Unknown task '$Task'. Use up|down|logs|check|test|shell|migrate|reset-db." }
}
