# MVP Admin Notes

## Local startup

From `eqp4l-backend`:

```powershell
.\scripts\dev.ps1 up
```

Verify `http://localhost:8000/health/` returns `{"status":"ok","database":"ok"}`.

## Local users

The development seed creates `SA-0001`, `USR-0001`, `USR-0002` and `USR-0003`. Local passwords come from `.env.example` and are not production credentials. Never copy those passwords into production.

## Daily administration

- Super Admin manages users, branches, item access and permissions.
- Warehouse Admin receives stock and creates dispatches, in their own warehouse. Several warehouses may exist: with more than one, the receipt and dispatch forms must send `warehouse_id`. A Warehouse Admin cannot act in another warehouse.
- Rollback note: migration `branches/0002` can only be reversed while one warehouse exists.
- Branch Admin receives deliveries and records sales where permitted.
- Front Staff records sales and can receive stock only through an explicit grant.
- User suspensions and deactivations take effect server-side.

## Backup and restore

Create a database dump:

```powershell
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > backups/mvp.dump
```

Test it only in a throwaway database using `scripts/restore-test.sh` from an environment with Bash. The restore script never changes the running application database.

## Checks

Run:

```powershell
docker compose run --rm web bash scripts/check.sh
```

Do not deploy or load real users until staging, backup, rollback and hosting gates are complete.
