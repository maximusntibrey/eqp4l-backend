#!/usr/bin/env bash
# Regenerate pinned lock files (run inside the container: docker compose run --rm web scripts/compile-requirements.sh)
set -euo pipefail
pip-compile --quiet --allow-unsafe --generate-hashes --strip-extras -o requirements.txt requirements.in
pip-compile --quiet --allow-unsafe --generate-hashes --strip-extras -o requirements-dev.txt requirements-dev.in
