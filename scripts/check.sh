#!/usr/bin/env bash
# The single check command for eqp4l-backend (TASKS T.15, rule 0.3).
#
#   bash scripts/check.sh
#
# Runs, in order: ruff lint, ruff format check, mypy, bandit, pip-audit, Django system
# check, missing-migration check, and pytest with coverage. Every step runs even if an
# earlier one fails; the script exits non-zero if any step failed.
#
# Works in Git Bash on Windows and in bash on Linux (CI). `make` is not used because it
# is not installed on the Windows development machine (SKILLS.md Appendix A.3).
#
# Needs: the dev requirements installed (requirements/base.txt + requirements/dev.txt),
# the environment variables from .env.example (a local .env file is read by the settings),
# and a reachable PostgreSQL for the tests and the migration check.
set -uo pipefail

cd "$(dirname "$0")/.."

# Pick the Python interpreter: an active venv, then ./.venv (Windows or Linux layout),
# then the python on PATH (CI installs the requirements into the runner's Python).
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PY="python"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif [[ -x ".venv/Scripts/python.exe" ]]; then
  PY=".venv/Scripts/python.exe"
else
  PY="python"
fi

failed=()

run_step() {
  local name="$1"
  shift
  echo
  echo "==> ${name}: $*"
  if "$@"; then
    echo "--- ${name}: OK"
  else
    echo "--- ${name}: FAILED"
    failed+=("${name}")
  fi
}

echo "check.sh: $("$PY" -V 2>&1) at ${PY}"

run_step "ruff lint" "$PY" -m ruff check .
run_step "ruff format" "$PY" -m ruff format --check .
run_step "mypy" "$PY" -m mypy .
run_step "bandit" "$PY" -m bandit -c pyproject.toml -r . -q
run_step "pip-audit" "$PY" -m pip_audit --strict --progress-spinner off --disable-pip \
  --require-hashes -r requirements/base.txt -r requirements/dev.txt
run_step "django check" "$PY" manage.py check --fail-level WARNING
run_step "missing migrations" "$PY" manage.py makemigrations --check --dry-run
run_step "pytest" "$PY" -m pytest --cov --cov-report=term-missing

echo
if (( ${#failed[@]} )); then
  echo "check.sh: FAILED steps: ${failed[*]}"
  exit 1
fi
echo "check.sh: all checks passed"
