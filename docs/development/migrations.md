# Database migrations and roles

[Approved ownership model](../architecture/data-model.md) · [Setup](local.md) · [Tests](testing.md)

Alembic revision `0001` creates the Phase 1 relational foundation. The local PostgreSQL bootstrap creates `rv_migrator` (DDL), `rv_app` (API), `rv_worker` (procedure execution only) and `rv_executor` (NOLOGIN internal procedure owner). No runtime login is a table owner, superuser or BYPASSRLS. Startup checks enforce role and migration revision. Only the local bootstrap administrator has superuser access. Migration credentials are absent from API/worker containers.

Tenant tables use UUIDs, explicit owner IDs, composite owner-parent FKs, indexed owner/state queries, ENABLE and FORCE ROW LEVEL SECURITY. API queries set `repovox.owner_id` with transaction-local `set_config(...,true)` exclusively after session validation; missing context returns no tenant rows and rejects writes. Pool transactions roll back/reset automatically on exit. The database credential is a trusted service boundary: PostgreSQL custom context is not an identity provider; exposing `rv_app` SQL access to end users would allow context forgery and is forbidden.

Internal NOLOGIN executor has an explicit internal RLS policy. Narrow SECURITY DEFINER procedures are pinned to `pg_catalog,public,rv` search path, owned by that role, revoked from PUBLIC and individually granted. The worker has no direct tenant table reads/writes or executor role membership. Claims resolve tenant from a DB stage ID and validate job/lease/cancellation/deadline/reservation/concurrency; completion validates fence/expiry and a server-scoped fixture object path. API can read its own tenant rows and mutate project/session rows; admission/cancel/deletion use restricted procedures. Direct snapshot INSERT exists for ownership/FK enforcement tests and future acquisition foundations; HTTP never exposes it and synthetic admissions construct their own snapshot.

Implemented tables: users, sessions, projects, snapshots, jobs, stages, attempts, state history, outbox, quota accounts/reservations, append-only usage ledger and deletion requests. Future knowledge-artifact/model-operation/chunk/storyboard/video/grant tables reserve owner-safe relations but their production payload/rights/publication/delivery interfaces are unavailable. Research datasets/runs and model release registries belong to later isolated workloads and are not created here. No customer data becomes training data.

```powershell
docker compose run --rm migrate
docker compose run --rm migrate alembic -c apps/api/alembic.ini current
```

Migration upgrade is transactional. On failure no partial schema is accepted. The disposable test setup applies it to an empty database; tests inspect revision, RLS, grants and FK enforcement. Destructive downgrade is explicitly disabled: this initial foundation would destroy durable job/history data. Local reset is separately documented. Before later schema releases, add expand/contract compatibility, backup/restore rehearsal and reviewed reversible migrations. No PITR, backup or production rollback guarantee is claimed now.
