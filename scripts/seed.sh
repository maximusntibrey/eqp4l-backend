#!/usr/bin/env bash
# Idempotent dev seed hook. No-op until models exist (B1.2 approval).
# Later: call `python manage.py seed_dev` (SA-0001, one dev user per role, 3 branches, sample items/prices/stock).
echo "seed: no models yet, nothing to seed"
