# Local development

Phase 1 implements a development-only SaaS foundation following the accepted Phase 0 baseline at `e35d8ef8a8a53cb34e46271a9813b5332ea42c1f`. It requires independent review before any later phase. No paid AI, model weights, submitted-code execution or cloud provisioning is used.

## Start

Install Docker Desktop with Linux containers, Docker Compose v2, Python 3.11+ and Node 24.22.1. Allow at least 15 GB free disk space for images, dependencies and builds; actual storage use varies. From the repository root:

```powershell
python tools/phase1_env.py
docker compose up -d --build
docker compose ps -a
```

Use the exact `.node-version` runtime before `npm ci` in `apps/web`; its project
configuration rejects incompatible Node engines and requires HTTPS certificate
validation. Run `node tools/security_node.mjs` and
`node --test tools/security_node.test.mjs` from the repository root. The inspector
rejects trust/startup overrides; do not remove them silently to obtain a pass.
See the [security evidence and remaining debt](../security/node-next-remediation.md).

The first command creates an ignored `.env` with distinct random local values and refuses to overwrite an existing file. `.env.example` lists names and placeholders. The historical `MINIO_ROOT_*` variable names identify local S3 bootstrap credentials; the actual local server is [SeaweedFS](../adr/0009-local-object-storage.md). Only its bootstrap containers receive those credentials. The API/worker receive a bucket-scoped service credential. API database role is `rv_app`, worker role `rv_worker`; migration role `rv_migrator` is separate. None has superuser/BYPASSRLS. PostgreSQL's local bootstrap administrator is confined to bootstrap and disposable test administration.

Migrations and private bucket setup run before the API. Open `http://localhost:3000`, choose Alex Chen or Sam Rivera, and add `https://github.com/owner/repo` as a project. This stores an unprocessed locator without checking whether it exists, is public, or is owned by you. No HTTP acquisition occurs. Generate video remains disabled. Project details offer a clearly labelled synthetic fixture; its persisted records show queue/worker behavior and the explicit `phase1_fixture_boundary` outcome. It does not complete video generation.

`http://localhost:8000/health` is liveness; `/ready` verifies database connectivity and returns `generation_available: false`. `/docs` contains FastAPI OpenAPI documentation. Authentication cookies use HttpOnly for the session, SameSite=Strict, one-hour expiry, and a server-side nonce record; Secure is disabled only for local HTTP. Mutations require exact local Origin and a session-bound CSRF header. Production boot is disabled until the managed identity adapter exists. The Next.js BFF forwards only documented local routes to a fixed backend origin; it accepts no fetch destination from a user.

## Stop and resume

```powershell
docker compose down
docker compose up -d
```

Named database/storage volumes survive `down`. Redis is intentionally nonpersistent; PostgreSQL outbox/reconciliation restores delivery. Do not use the development credentials outside this environment. Existing database volumes keep their original role passwords; changing `.env` alone does not rotate them.

## Explicit reset

This erases only this Compose project's database, local objects and storage credential volume. Do it only when intentionally discarding development data:

```powershell
docker compose down --volumes
docker compose up -d --build
```

Use a separate Compose project (`-p repovox-test`) for disposable integration tests, as described in [testing](testing.md). Never point its test administrator at a valuable development database. Tests truncate project/session/ledger data.

## Host tooling

Use a dedicated Python environment and the [security bootstrap](../security/python-trust-remediation.md)
before package installation. This does not update unrelated host installations.

```powershell
python tools/security_bootstrap.py
uv sync --frozen
npm --prefix apps/web ci
npm --prefix apps/web run dev
```

Host frontend development requires a running Compose API; its default BFF destination is localhost:8000. Python type/lint/unit checks do not need containers. Critical isolation/orchestration tests require actual PostgreSQL, Redis and S3-compatible services and fail when configuration/services are absent. [API](api.md), [migrations](migrations.md), [orchestration](orchestration.md), [verification](../delivery/phase1-verification.md).
