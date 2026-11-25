<#
Host-agnostic staging check for Docker on the current machine.
Usage: .\scripts\staging.ps1 [up|smoke|backup|down]
#>
param([Parameter(Position = 0)][string]$Task = "up")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

switch ($Task) {
    "up" {
        docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build
        for ($i = 0; $i -lt 30; $i++) {
            try {
                $health = Invoke-RestMethod -Uri "http://localhost:8000/health/" -TimeoutSec 5
                if ($health.status -eq "ok" -and $health.database -eq "ok") {
                    Write-Host "Staging-equivalent environment healthy: http://localhost:8000"
                    return
                }
            } catch {}
            Start-Sleep -Seconds 2
        }
        throw "Staging-equivalent environment did not become healthy"
    }
    "smoke" {
        & (Join-Path $PSScriptRoot "staging-smoke.ps1")
    }
    "backup" {
        & (Join-Path $PSScriptRoot "backup.ps1")
    }
    "down" {
        docker compose -f docker-compose.yml -f docker-compose.staging.yml down
    }
    default {
        throw "Unknown task '$Task'. Use up|smoke|backup|down."
    }
}
