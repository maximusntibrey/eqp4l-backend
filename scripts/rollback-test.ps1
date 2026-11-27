<#
Local rollback rehearsal (Windows / PowerShell). Run against the running compose stack:
  .\scripts\rollback-test.ps1

Steps, with the recovery time recorded in seconds:
  1. Take a pre-rollback database backup (scripts/backup.ps1).
  2. Reverse the latest audit migration (an index only, safe to reverse and re-apply).
  3. Check /health/ reports the database ok.
  4. Re-apply migrations forward.
  5. Check /health/ again and that the audit table still has its rows.
Hosted rollback is a Railway redeploy of the previous deployment (docs/RUNBOOK.md); this script rehearses the database side locally.
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Test-Health {
    $h = Invoke-RestMethod -Uri "http://localhost:8000/health/" -TimeoutSec 10
    if ($h.status -ne "ok" -or $h.database -ne "ok") { throw "Health check failed: $($h | ConvertTo-Json -Compress)" }
}
function Invoke-Manage($arguments) {
    docker compose exec -T web python manage.py @arguments
    if ($LASTEXITCODE -ne 0) { throw "manage.py $($arguments -join ' ') failed" }
}
function Get-AuditCount {
    $n = docker compose exec -T db psql -U eqp4l -d eqp4l -tA -c "SELECT count(*) FROM audit_auditevent"
    return [int]($n | Select-Object -First 1).Trim()
}

Write-Host "1. Pre-rollback backup"
& "$PSScriptRoot\backup.ps1"
Test-Health
$before = Get-AuditCount

$applied = docker compose exec -T web python manage.py showmigrations audit --plan
$names = @($applied | ForEach-Object { if ($_ -match "audit\.(\d{4}_\w+)") { $Matches[1] } })
if ($names.Count -lt 2) { throw "Need at least two audit migrations to rehearse a reverse" }
$latest = $names[-1]; $previous = $names[-2]
Write-Host "2. Reversing audit.$latest back to $previous"
$timer = [System.Diagnostics.Stopwatch]::StartNew()
Invoke-Manage @("migrate", "audit", $previous, "--noinput")

Write-Host "3. Health after reverse"
Test-Health

Write-Host "4. Re-applying migrations forward"
Invoke-Manage @("migrate", "--noinput")

Write-Host "5. Health and data after roll-forward"
Test-Health
$after = Get-AuditCount
$timer.Stop()
if ($after -lt $before) { throw "Audit rows lost: $before before, $after after" }
Write-Host ("Rollback rehearsal PASSED: audit rows {0} -> {1}, recovery {2} s" -f $before, $after, [math]::Round($timer.Elapsed.TotalSeconds, 1))
