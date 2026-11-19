# One-command local start (FIX-1), Windows PowerShell 5.1+:
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# Checks Docker, creates .env from .env.example if missing, starts the stack, waits for
# /health/, prints the URLs. Safe to re-run.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker is not running. Start Docker Desktop, wait for 'Engine running', then retry."
    exit 1
}

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host 'Created .env from .env.example (local-only dummy values).'
}

function Get-EnvValue($name, $default) {
    $line = Select-String -Path .env -Pattern "^$name=(.*)$" | Select-Object -Last 1
    if ($line) { return $line.Matches[0].Groups[1].Value.Trim() }
    return $default
}
$appPort = Get-EnvValue 'APP_PORT' '8000'
$dbPort = Get-EnvValue 'POSTGRES_PORT' '5433'

docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Error 'docker compose up failed. Common cause: a port is in use (netstat -ano | findstr :5433). Change APP_PORT or POSTGRES_PORT in .env.'
    exit 1
}

$url = "http://127.0.0.1:$appPort/health/"
Write-Host "Waiting for $url ..."
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) {
            Write-Host 'App is up.'
            Write-Host "  Health:     $url"
            Write-Host "  PostgreSQL: 127.0.0.1:$dbPort (user/db/password in .env)"
            Write-Host '  Logs:       docker compose logs -f app'
            Write-Host '  Stop:       docker compose down      (add -v to wipe the local database)'
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 2
}
Write-Error "/health/ did not return 200 within 2 minutes. See: docker compose logs app"
exit 1
