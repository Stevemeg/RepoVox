# Self-hosted deployment guide

Status: readiness runbook, 2026-11-18, on branch `feat/js-ts-frameworks-and-deploy-readiness`.
Not independently reviewed or accepted. **Nothing was deployed or provisioned while writing
it**, and no cloud account, paid service or real customer data was used. It does not
authorize a deployment, lift any phase gate or change `Stage 3: BLOCKED`, `CR-04: PENDING`
or `EVAL-ENTRY: UNFROZEN`. Related: [production deployment design](deployment.md),
[media database](media-database.md), [reliability](reliability.md),
[parser process isolation](../adr/0011-parser-process-isolation.md),
[local object storage](../adr/0009-local-object-storage.md),
[Node/Next remediation](../security/node-next-remediation.md),
[sole-contributor policy and phase authority](../../AGENTS.md).

The guide covers one Linux host running the repository's `docker-compose.yml`. It names every
service, the order they start in, how each is checked, which identity each runs as, and every
setting and secret they read. Steps that only become possible once the production boot gate
below is lifted are marked **(after gate)**.

## Production boot gate: read first

`apps/api/repovox/core/config.py` (`Settings.fail_closed`) refuses to start the API, the
workers, the dispatcher and the media worker with a production configuration. This is a
deliberate fail-closed control, not a defect, and this guide does not change it.

| Setting | Target production value | What the code accepts today | Message on refusal |
| --- | --- | --- | --- |
| `REPOVOX_ENVIRONMENT` | `production` | `development` or `test` only | `Phase 1 has no production identity adapter; production boot is disabled` |
| `REPOVOX_DEV_AUTH` | `false` | `true` only | `An explicitly enabled development identity adapter is required` |
| `REPOVOX_ORIGIN` | the TLS origin, for example `https://repovox.example.com` | `http://localhost:3000` or `http://127.0.0.1:3000` only | `Phase 1 requires an authorized local browser origin` |
| `REPOVOX_FIXTURES` | `false` | `false` or `true`; `REPOVOX_SYNTHETIC_SOURCE_DIR` requires `true` | `Synthetic source requires the development fixture mode` |
| `REPOVOX_VIDEO` | `true` | `true` or `false` | (accepted) |

Consequence: today the stack boots only as a private single-host stack that uses the
development identity adapter and is reached from the same machine at
`http://localhost:3000`. Serving other users needs, at minimum, a production identity
adapter, an origin allowlist that accepts the TLS origin, and an independent security review
of both. Each needs its own owner authorization; none is part of this branch.

## 1. Host prerequisites

| Requirement | Why | How to check |
| --- | --- | --- |
| Linux on `x86_64` or `aarch64` | Parser containment refuses any other platform or machine type (`parser_isolation_unavailable`) | `uname -sm` |
| Landlock ABI 1 or later enabled | Parser subprocesses restrict file access with Landlock before parsing untrusted source; see [ADR-0011](../adr/0011-parser-process-isolation.md) | `grep -o landlock /sys/kernel/security/lsm` prints `landlock`, and the probe below prints `1` or higher |
| seccomp | Parser and media sandboxes deny network, `exec` and `fork` (`libseccomp2` is in the API image) | `grep Seccomp: /proc/self/status` |
| Containers not running as root | Containment refuses UID 0; the API image runs as UID 10001 | `docker compose exec api id -u` prints `10001` |
| Docker Engine with Compose v2 | `depends_on` conditions `service_healthy` and `service_completed_successfully` | `docker compose version` |
| Outbound DNS and HTTPS 443 to `api.github.com` and `codeload.github.com` | Repository acquisition; nothing else is contacted at run time | see below |
| Build-time egress to Docker Hub, the Debian archive, PyPI and `registry.npmjs.org` | Image builds only | `docker compose build` |
| CPU and memory: at least 4 vCPU and 12 GiB (estimate, not a benchmark) | `api`, `worker`, `dispatcher` and `media-worker` are each limited to 1 CPU and 2 GiB; PostgreSQL, Redis, storage and web have no limit | `nproc`, `free -g` |

Landlock ABI probe (system call 444 is `landlock_create_ruleset` on both supported
architectures; flag 1 asks for the ABI version):

```sh
python3 -c 'import ctypes; libc = ctypes.CDLL(None, use_errno=True); print(libc.syscall(444, None, 0, 1))'
```

A result of `-1` means Landlock is absent or disabled (check the kernel's `lsm=` boot
parameter). The same probe can be run inside the API container with
`docker compose exec api python -c ...` to confirm the container runtime's seccomp profile
lets the call through.

**GitHub egress.** `apps/api/repovox/analysis/transport.py` resolves each host once, then
connects to the numeric address with TLS for the original host name. It never uses an HTTP
proxy and never follows redirects. Every resolved address must be globally routable: private,
loopback, link-local and special ranges are refused, and so are NAT64 (`64:ff9b::/96`,
`64:ff9b:1::/48`), IPv4-mapped, 6to4 and Teredo IPv6 addresses (`github_address_blocked`).
Use a resolver that returns GitHub's public addresses and a route that reaches them directly:
public IPv4, or native global IPv6. A split-horizon resolver, a DNS64/NAT64-only network or
a mandatory egress proxy will make acquisition fail closed. Only `api.github.com` and
`codeload.github.com` are accepted origins.

## 2. Environment and secrets

### Generate secrets

```sh
python tools/phase1_env.py
chmod 600 .env
```

The tool creates `.env` with distinct random values and refuses to overwrite an existing
file. It never prints a value. `.env` is ignored by Git and must never be committed, pasted
into an issue, or copied between hosts: generate it on the host that uses it. The file header
says the values are for development; a host serving other users **(after gate)** must use
values generated on that host and kept only there.

| Variable in `.env` | Used by | Purpose |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `postgres` (first start), `tests` profile | PostgreSQL superuser; never given to an application service |
| `MIGRATION_PASSWORD` | `migrate`, `postgres` init | `rv_migrator`, owner of the core `repovox` database |
| `APP_DATABASE_PASSWORD` | `api`, `dispatcher`, `postgres` init | `rv_app`, the API's core role (the dispatcher uses it only for the media handoff reads) |
| `WORKER_DATABASE_PASSWORD` | `worker`, `dispatcher`, `postgres` init | `rv_worker`, analysis workers, dispatch and reconciliation |
| `MEDIA_MIGRATION_PASSWORD` | `media-migrate`, `postgres` init | `rvm_migrator`, owner of the `repovox_media` database |
| `MEDIA_APP_PASSWORD` | `api`, `dispatcher`, `postgres` init | `rvm_app`, the API's media role |
| `MEDIA_WORKER_PASSWORD` | `media-worker`, `postgres` init | `rvm_worker`, video rendering |
| `SESSION_SECRET` | `api` and workers | Session signing; at least 32 characters |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | `storage-config`, `storage-init` | Object storage administrator, used only to write the S3 identity file and create the bucket |
| `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY` | `storage-config`, `storage-init`, `api` and workers | The application's object storage identity |
| `SYNTHETIC_SOURCE_DIR` (optional, not generated) | `api`, `worker` | Development only: serve locally authored synthetic repositories. Leave unset outside development |

Core and media roles are separate and cannot cross: `rv_*` roles connect only to `repovox`,
`rvm_*` roles only to `repovox_media` (`infrastructure/local/init-db.sh`). The init script runs
once, when the `postgres-data` volume is first created. Changing a password in `.env` later
does not change the role; rotate it with `ALTER ROLE ... PASSWORD` and then update `.env`.

### Application settings

Settings are read with the prefix `REPOVOX_` (`apps/api/repovox/core/config.py`). The compose
file sets them in the shared `x-api` block.

| Setting | Code default | `docker-compose.yml` | Target production value | Notes |
| --- | --- | --- | --- | --- |
| `REPOVOX_ENVIRONMENT` | `production` | `development` | `production` **(after gate)** | Refused today, see the gate above |
| `REPOVOX_DEV_AUTH` | `false` | `true` | `false` **(after gate)** | Refused today |
| `REPOVOX_FIXTURES` | `false` | `true` | `false` | Accepted |
| `REPOVOX_ANALYSIS` | `false` | `true` | `true` | Static analysis through Stage 9 |
| `REPOVOX_VIDEO` | `false` | `true` | `true` | Video jobs in the media database |
| `REPOVOX_ORIGIN` | `http://localhost:3000` | `http://localhost:3000` | the reverse proxy's TLS origin **(after gate)** | Refused today unless local |
| `REPOVOX_DATABASE_URL` | none | core role per service | unchanged | `postgresql+psycopg://rv_...@postgres:5432/repovox` |
| `REPOVOX_WORKER_DATABASE_URL` | unset | `rv_worker` for `worker` and `dispatcher` | unchanged | |
| `REPOVOX_MEDIA_DATABASE_URL` | unset | `rvm_app` | unchanged | |
| `REPOVOX_MEDIA_WORKER_DATABASE_URL` | unset | `rvm_worker` for `media-worker` | unchanged | |
| `REPOVOX_MIGRATION_DATABASE_URL` | read by `apps/api/migrations/env.py` | `rv_migrator` for `migrate` | unchanged | |
| `REPOVOX_MEDIA_MIGRATION_DATABASE_URL` | read by `apps/api/migrations_media/env.py` | `rvm_migrator` for `media-migrate` | unchanged | |
| `REPOVOX_SESSION_SECRET` | none (required) | `SESSION_SECRET` | generated on the host | |
| `REPOVOX_SESSION_SECONDS` | `3600` | not set | `3600` | 60 to 86400 |
| `REPOVOX_REDIS_URL` | `redis://redis:6379/0` | same | same | Compose network only |
| `REPOVOX_STORAGE_ENDPOINT` | `http://storage:8333` | same | same | Compose network only |
| `REPOVOX_STORAGE_ACCESS_KEY`, `REPOVOX_STORAGE_SECRET_KEY` | none (required) | from `.env` | generated on the host | |
| `REPOVOX_STORAGE_BUCKET` | `repovox-private` | not set | `repovox-private` | Created by `storage-init` |
| `REPOVOX_GITHUB_TOKEN` | unset | not set | optional | Raises GitHub API rate limits; a secret, store it like `.env` |
| `REPOVOX_MEDIA_HANDOFF_SECONDS` | `3` | not set | `3` | `0` turns the API's pass off; the dispatcher still runs it every 5 seconds |
| `REPOVOX_SYNTHETIC_SOURCE_DIR` | unset | `${SYNTHETIC_SOURCE_DIR:-}` | unset | Development only |
| `REPOVOX_API_URL` (web) | `http://localhost:8000` | `http://api:8000` | `http://api:8000` | Read by `apps/web/src/app/api/v1/[...path]/route.ts` |

**(after gate)** Production values belong in a separate override file kept on the host, not in
`docker-compose.yml`, for example:

```yaml
# docker-compose.production.yml: an example only. The boot gate refuses it today.
# Use with: docker compose -f docker-compose.yml -f docker-compose.production.yml up -d
x-production: &production
  REPOVOX_ENVIRONMENT: production
  REPOVOX_DEV_AUTH: 'false'
  REPOVOX_FIXTURES: 'false'
  REPOVOX_ORIGIN: https://repovox.example.com
services:
  api: {environment: *production}
  worker: {environment: *production}
  dispatcher: {environment: *production}
  media-worker: {environment: *production}
```

Compose merges `environment` keys from the override into each service, so the database,
storage and secret settings from `docker-compose.yml` are kept.

### TLS reverse proxy (after gate)

Terminate TLS at a reverse proxy on the host and forward to the web container at
`127.0.0.1:3000`. The web server forwards `/api/v1/...` to the API over the compose network
(`REPOVOX_API_URL`), so the API's `127.0.0.1:8000` port does not need to be reachable from
outside the host and should not be published beyond loopback. Set `REPOVOX_ORIGIN` to the
proxy's exact `https://` origin.

## 3. Services, startup order and health

Every service, in the order Compose starts them. A service waits for every service listed
against it.

| Layer | Service | Waits for | Health or completion check | Runs as |
| --- | --- | --- | --- | --- |
| 0 | `postgres` | nothing | `pg_isready -U postgres -d repovox` every 3 s | upstream `postgres:16.13-alpine` default |
| 0 | `redis` | nothing | `redis-cli ping` every 3 s | upstream `redis:7.4.9-alpine` default |
| 0 | `storage-config` | nothing | one-shot; writes the S3 identity file, exits 0 | UID 10001 (`repovox`) |
| 1 | `migrate` | `postgres` healthy | one-shot `alembic -c apps/api/alembic.ini upgrade head` | UID 10001 |
| 1 | `media-migrate` | `postgres` healthy | one-shot `alembic -c apps/api/alembic_media.ini upgrade head` | UID 10001 |
| 1 | `storage` | `storage-config` completed | `wget http://127.0.0.1:9333/cluster/status` every 3 s | upstream `chrislusf/seaweedfs:4.17` default |
| 2 | `storage-init` | `storage` healthy | one-shot; creates the private bucket, exits 0 | UID 10001 |
| 3 | `api` | `migrate`, `media-migrate`, `storage-init` completed; `redis` healthy | `GET /ready` every 5 s | UID 10001 |
| 3 | `worker` | as `api` | none (process state only) | UID 10001 |
| 3 | `dispatcher` | as `api` | none (process state only) | UID 10001 |
| 3 | `media-worker` | as `api` | none (process state only) | UID 10001 |
| 4 | `web` | `api` healthy | `GET /sign-in` every 5 s | `node` |
| - | `tests` | profile `test` only | runs `pytest`; never part of a deployment | UID 10001 |

`api`, `worker`, `dispatcher`, `media-worker` and `tests` share one hardened block: read-only
root file system, a 2 GiB `noexec,nosuid,nodev` `/tmp`, 1 CPU, 2 GiB memory, 128 processes,
all capabilities dropped and `no-new-privileges`. Only `api` (`127.0.0.1:8000`) and `web`
(`127.0.0.1:3000`) publish ports, both on loopback.

## 4. Build, migrate and start

1. Check out the reviewed commit and confirm it:

   ```sh
   git fetch origin
   git checkout <reviewed-commit-sha>
   git log -1 --format='%H %an'
   ```

2. Generate `.env` (section 2) and build the images:

   ```sh
   docker compose build
   ```

3. Start PostgreSQL and apply both migration chains. The core chain ends at revision `0004`
   and the media chain at `m001`; both are idempotent at head.

   ```sh
   docker compose up -d postgres
   docker compose run --rm migrate        # core repovox: alembic upgrade head -> 0004
   docker compose run --rm media-migrate  # repovox_media: alembic upgrade head -> m001
   docker compose exec -T postgres psql -U postgres -d repovox -tAc 'SELECT version_num FROM alembic_version'
   docker compose exec -T postgres psql -U postgres -d repovox_media -tAc 'SELECT version_num FROM alembic_version'
   ```

   The two queries print `0004` and `m001`. The media migration refuses to run against a
   database that contains `generation_jobs`, so it cannot be pointed at the core database.

4. Start everything else; Compose follows the order in section 3:

   ```sh
   docker compose up -d
   docker compose ps
   ```

   `postgres`, `redis`, `storage`, `api` and `web` report `healthy`; `storage-config`,
   `storage-init`, `migrate` and `media-migrate` show `exited (0)`; `worker`, `dispatcher` and
   `media-worker` show `running`.

## 5. Smoke checks

```sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/sign-in
docker compose exec -T web node -e 'console.log(require("next/package.json").version, require("sharp").versions.sharp)'
docker compose exec -T api python -c 'import ctypes; print(ctypes.CDLL(None).syscall(444, None, 0, 1))'
docker compose logs --since 5m worker dispatcher media-worker
```

| Check | Expected |
| --- | --- |
| `/health` | `{"status":"alive","version":"0.1.0"}`: the process answers; says nothing about dependencies |
| `/ready` | `{"status":"ready","generation_available":false,"environment":"development"}`; HTTP 503 with `database_unavailable` when the core database cannot be reached |
| `/sign-in` | `200` |
| Web versions | `16.4.6 0.35.5` |
| Landlock inside the API container | `1` or higher |
| Worker logs | no repeating `reconciliation_dependency_unavailable`, `media_handoff_dependency_unavailable` or `broker_unavailable` events |

An end-to-end analysis or video job is the only check that exercises parser containment and
GitHub egress together. Run one only against a repository you are entitled to analyse; a
containment failure is reported as `parser_isolation_unavailable` and an egress failure as
`github_unavailable`, `github_timeout` or `github_address_blocked`.

## 6. 24-hour retention lifecycle

| Data | Where | Lifetime | What deletes it |
| --- | --- | --- | --- |
| Analysis archive and analysis bodies | object storage, core metadata in `repovox` | job admission + 24 hours | API visibility ends at expiry; reconciliation deletes the expired job's prefix, including upload orphans ([deployment design](deployment.md#phase-2-local-execution-and-retention)) |
| Published videos, captions and metadata | object storage, rows in `repovox_media` | media job creation + 24 hours (`expires_at`) | `media-worker` reconciliation lists `mv.expired()`, deletes the job's objects, then records `mv.mark_deleted` |
| Media job deadline | `repovox_media` | 45 minutes from admission | stages past the deadline end; a lost worker's lease is fenced and retried or ended |
| Media admission | `repovox_media` | 20 jobs per owner per 30 days | refused at admission |
| Scratch files | container `/tmp` (tmpfs) | the job, at most the container's life | removed after each run; tmpfs disappears with the container |

Retention runs inside `media-worker` and the core reconciliation in `dispatcher`, so both must
be running for deletion to happen on time. Stopping them pauses deletion; it does not extend
what users can see, because visibility already fails closed at expiry.

## 7. Backup and restore

- **Databases.** Take logical backups of both databases with the superuser inside the
  `postgres` container, and of the role definitions separately (the role dump contains
  password hashes; treat it as a secret):

  ```sh
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  docker compose exec -T postgres pg_dump -U postgres -Fc repovox > "repovox-$stamp.dump"
  docker compose exec -T postgres pg_dump -U postgres -Fc repovox_media > "repovox_media-$stamp.dump"
  docker compose exec -T postgres pg_dumpall -U postgres --roles-only > "roles-$stamp.sql"
  ```

  Encrypt the files and keep them off the host. Restore only into a disposable instance first
  (`pg_restore -U postgres -d <database> --clean --if-exists <file>`) and check the
  `alembic_version` of each database before using it.
- **Object storage.** Do not back up the `storage-data` volume. Everything in it expires within
  24 hours (section 6); a copy would keep source archives and videos past the retention
  promise. After a restore, rows that point at objects that no longer exist expire through the
  same reconciliation.
- **Redis** is started without persistence (`--save ''`, `--appendonly no`) and holds nothing to
  back up. Jobs and dispatch events are durable in PostgreSQL
  ([ADR-0002](../adr/0002-durable-jobs.md)): the dispatcher leaves an event unacknowledged until
  the broker accepts it and retries on its next poll, and reconciliation fences stages whose
  lease or deadline expired. A Redis restart is designed to delay work, not to lose job state.
- **`.env`** is the only copy of the generated secrets. Keep an encrypted copy with the
  database backups, or plan to rotate every role password on restore.

## 8. Upgrade and rollback

1. Take the backups in section 7.
2. Check out the new reviewed commit, `docker compose build`, then run `migrate` and
   `media-migrate` as in section 4 before `docker compose up -d`.
3. Repeat the smoke checks in section 5.

Rolling back the application: check out the previous reviewed commit, rebuild and
`docker compose up -d`. Rolling back the database: restore the backups taken in step 1 into a
fresh volume. Do not use `alembic downgrade` on a database that holds data: the core `0004`
downgrade refuses while any pilot attempt exists (`pilot_rollback_requires_empty_ledger`) and
the media `m001` downgrade refuses while any media job exists
(`media_rollback_requires_empty_database`), so neither can discard history to make a rollback
look clean.

## 9. Compose readiness audit, 2026-11-18

Read-only audit of `docker-compose.yml`, `infrastructure/local/api.Dockerfile`,
`infrastructure/local/web.Dockerfile` (the images are built from these; there is no
`apps/api/Dockerfile` or `apps/web/Dockerfile`), `infrastructure/local/init-db.sh`,
`apps/api/repovox/core/config.py` and `tools/phase1_env.py`. Docker is not installed on the
machine the audit ran on, so `docker compose config` and `docker compose up` were **not** run
there; the files were checked statically, and the CI `integration` job builds and runs the
stack. Nothing below was changed on this branch.

| # | Finding | Effect | Follow-up (needs its own review) |
| --- | --- | --- | --- |
| A1 | Production configuration is refused by `Settings.fail_closed` | No production or multi-user deployment is possible | Production identity adapter, origin allowlist, security review |
| A2 | All 12 required `${VAR:?}` references are generated by `tools/phase1_env.py`, none is left over; `SYNTHETIC_SOURCE_DIR` is the only optional one | `.env` generation is complete | none |
| A3 | The `depends_on` graph has no cycle and every `service_healthy` target has a healthcheck; every `service_completed_successfully` target is a one-shot service | Startup order is deterministic (section 3) | none |
| A4 | `worker`, `dispatcher` and `media-worker` have no healthcheck | A hung process shows as `running` | A liveness signal, such as a heartbeat file or database heartbeat |
| A5 | `web` runs as `node` but without `read_only`, `cap_drop`, `no-new-privileges` or resource limits | Weaker isolation than the API services | Harden after checking Next.js's writable cache paths |
| A6 | `postgres`, `redis` and `storage` run as their upstream images' default users, without dropped capabilities, resource limits or a restart policy | A crash is not restarted automatically; resource use is unbounded | Restart policy and limits sized from measurements |
| A7 | Redis has no password and no persistence; it publishes no port | Reachable only from the compose network; queue contents are transient by design | Optional authentication |
| A8 | Only `api` and `web` publish ports, both on `127.0.0.1` | Nothing is exposed beyond the host | none |
| A9 | Every `REPOVOX_*` value in the compose file is read: by `Settings`, by a migration environment, by the tests, or (`REPOVOX_API_URL`) by the web route handler | No dead configuration | none |

## 10. Release verification and known gate failure

The web application pins Next.js `16.4.6` (from `16.4.2`). `16.4.6` is outside the ranges of
[GHSA-mfr8-8qww-v76h](https://github.com/advisories/GHSA-mfr8-8qww-v76h) (`>= 16.3.0, <= 16.4.4`)
and [GHSA-vc7v-qv4w-wrv8](https://github.com/advisories/GHSA-vc7v-qv4w-wrv8)
(`>= 16.2.0, <= 16.4.4`); `sharp` stays `0.35.5`. CI asserts both versions.

`npm audit --audit-level=high` in `apps/web` still reports
[GHSA-fc5q-39xc-vjpf](https://github.com/advisories/GHSA-fc5q-39xc-vjpf), a high-severity
`picomatch` ReDoS. It reaches the project only through the test runner
(`vitest` -> `vite` / `tinyglobby` -> `fdir` -> `picomatch`), which is not in the production
image (`.next/standalone` only). The advisory covers every published `picomatch` release up to
the latest, `4.0.7`, and was widened on 2026-11-17 after the last green CI run on
`feature/repository-to-video`. npm's only suggested fix is a downgrade of `vitest` to `3.1.4`.
Until a patched `picomatch` is released or the owner decides how the audit gate treats
development-only dependencies, the frontend job's audit step fails on every branch.
