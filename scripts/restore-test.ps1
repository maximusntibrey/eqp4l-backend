<#
Scripted restore test for Windows / PowerShell.
Restores a pg_dump custom-format backup into a throwaway scratch database and checks tables.
Never touches the real database; drops scratch database in finally block.
Usage: .\scripts\restore-test.ps1 [backups/<file>.dump]
#>
param(
    [Parameter(Position = 0)]
    [string]$DumpFile
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $DumpFile) {
    # Default to the most recent .dump file in backups/
    $latest = Get-ChildItem -Path "backups\*.dump" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw "No .dump files found in backups/ directory." }
    $DumpFile = $latest.FullName
} else {
    if (-not (Test-Path $DumpFile)) { throw "Dump file not found: $DumpFile" }
    $DumpFile = (Resolve-Path $DumpFile).Path
}

if ((Get-Item $DumpFile).Length -le 0) { throw "Dump file is empty: $DumpFile" }

$pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "eqp4l" }
$scratch = "restore_test_$([System.Diagnostics.Process]::GetCurrentProcess().Id)"
Write-Host "Starting restore test using: $DumpFile"
Write-Host "Creating temporary scratch database: $scratch"

function Invoke-PsqlPostgres($sql) {
    docker compose exec -T db psql -U $pgUser -d postgres -tA -c "$sql"
}

function Invoke-PsqlScratch($sql) {
    docker compose exec -T db psql -U $pgUser -d $scratch -tA -c "$sql"
}

try {
    # Create scratch DB
    Invoke-PsqlPostgres "CREATE DATABASE $scratch" | Out-Null

    # Restore dump into scratch DB using binary redirection
    $restoreCmd = "docker compose exec -T db pg_restore -U $pgUser -d $scratch --no-owner < `"$DumpFile`""
    cmd.exe /c $restoreCmd
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1) {
        # pg_restore exit code 1 indicates non-fatal warnings (e.g. role/ownership differences)
        throw "pg_restore failed with exit code $LASTEXITCODE"
    }

    # Query public tables
    $tableCount = (Invoke-PsqlScratch "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").Trim()
    if ([int]$tableCount -le 0) {
        throw "Restore verification failed: 0 public tables found in $scratch"
    }

    Write-Host "Restore test PASSED: $tableCount public tables successfully restored in $scratch"
}
finally {
    Write-Host "Cleaning up: dropping temporary scratch database $scratch"
    Invoke-PsqlPostgres "DROP DATABASE IF EXISTS $scratch" | Out-Null
}
