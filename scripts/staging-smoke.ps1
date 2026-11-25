$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$health = Invoke-RestMethod -Uri "http://localhost:8000/health/" -TimeoutSec 10
if ($health.status -ne "ok" -or $health.database -ne "ok") {
    throw "Health smoke failed"
}

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$csrf = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/csrf/" -WebSession $session
$session.Headers["X-CSRFToken"] = $csrf.csrf_token

$password = $env:DEV_SA_0001_PASSWORD
if (-not $password) {
    $envFile = Get-Content ".env" -ErrorAction SilentlyContinue
    foreach ($line in $envFile) {
        if ($line -match '^DEV_SA_0001_PASSWORD=(.*)$') {
            $password = $Matches[1]
            break
        }
    }
}
if (-not $password) { throw "DEV_SA_0001_PASSWORD is not configured" }

$body = @{ login_id = "SA-0001"; password = $password } | ConvertTo-Json
$me = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/auth/login/" -WebSession $session -ContentType "application/json" -Body $body
$dashboard = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/dashboard/" -WebSession $session
$items = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/items/" -WebSession $session

Write-Host "Staging smoke passed: login=$($me.user.login_id), dashboard=$($dashboard.role), items=$($items.count)"
