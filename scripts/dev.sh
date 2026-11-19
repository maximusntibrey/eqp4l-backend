#!/usr/bin/env bash
# One-command local start (FIX-1): bash scripts/dev.sh   (Git Bash, WSL or Linux).
# Checks Docker, creates .env from .env.example if missing, starts the stack, waits for
# /health/, prints the URLs. Safe to re-run. Windows PowerShell users: scripts/dev.ps1.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! docker info >/dev/null 2>&1; then
  echo "error: Docker is not running. Start Docker Desktop, wait for 'Engine running', retry." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example (local-only dummy values)."
fi

# Ports come from .env (defaults match compose.yaml).
get() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | tr -d '\r' || true; }
app_port="$(get APP_PORT)"; app_port="${app_port:-8000}"
db_port="$(get POSTGRES_PORT)"; db_port="${db_port:-5433}"

docker compose up -d --build

url="http://127.0.0.1:${app_port}/health/"
echo "Waiting for ${url} ..."
for _ in $(seq 1 60); do
  if [[ "$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)" == "200" ]]; then
    echo "App is up."
    echo "  Health:     ${url}"
    echo "  PostgreSQL: 127.0.0.1:${db_port} (user/db/password in .env)"
    echo "  Logs:       docker compose logs -f app"
    echo "  Stop:       docker compose down      (add -v to wipe the local database)"
    exit 0
  fi
  sleep 2
done
echo "error: /health/ did not return 200 within 2 minutes. See: docker compose logs app" >&2
exit 1
