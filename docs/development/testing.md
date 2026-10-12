# Phase 1 testing

[Verification record](../delivery/phase1-verification.md) · [Local runtime](local.md) · [Migration isolation](migrations.md)

## Host checks

```powershell
uv sync --frozen
uv run ruff check apps/api tests tools/phase1*.py
uv run ruff format --check apps/api tests tools/phase1*.py
uv run mypy
uv run pytest tests/unit -q
uv run python tools/check_docs.py
uv run python tools/cost_model.py --check
uv run python -m unittest discover -s tools -p "test_*.py" -v
uv run python tools/phase1_contracts.py --check
uv run pip-audit --local
npm --prefix apps/web ci
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/web audit --audit-level=high
git diff --check
```

UV and npm lockfiles resolve exact versions. Missing service/administrator variables are errors, never successful integration skips. The API unit suite validates canonical URL input, strict fixture bodies and fail-closed production configuration. Frontend component tests cover auth/expiration, loading/error/empty states, project creation, synthetic labels and disabled generation. They complement the full browser flow, rather than proving backend behavior.

## Disposable real-service tests

Integration tests truncate their database and inject failures. Keep them isolated from your development records:

```powershell
docker compose -p repovox-test up -d --build postgres redis storage storage-init migrate
docker compose -p repovox-test run --rm --build tests
docker compose -p repovox-test down --volumes
```

Tests use actual PostgreSQL restricted roles/RLS/composite FKs, real Redis/Celery and the local S3 server. No SQLite or mocks substitute for these boundaries. The test administrator URL exists only in the test runner. Tests create two identities, twelve concurrent project requests, eight same-key admissions, eight competing quota admissions, eight lease contenders, repeated pooled owner/no-owner transactions, outbox failure injection/loss recovery and a real Celery subprocess. Test assertions check durable counts and outcomes. No measured RPS/p95/availability claims are derived from these sample sizes.

## Browser and recovery smoke

Run the main development stack, then:

```powershell
npm --prefix apps/web exec playwright install chromium
npm --prefix apps/web run test:e2e
python tools/phase1_runtime.py
```

The runtime script uses only local browser/API addresses and this project's Redis service. It creates disposable labelled records, stops/restarts Redis, checks durable admission/outbox recovery, restarts the worker and dispatcher gracefully, and verifies final explicit fixture-boundary state. It deletes its test project afterward. Run this only against this development stack; concurrent work may delay quotas. It does not operate other Compose projects or cloud resources.

## CI

GitHub Actions checks Python/TypeScript lint/types, frontend unit/browser tests/build, dependency audits, secret scanning, accepted documentation/contracts, and a fresh real-service migration/integration run. Workflows have read-only repository permissions, no production credentials, no paid keys and no Git-write operations. Ephemeral local test secrets are generated on the runner. Failed or absent integration services fail CI. The independent review handoff requires visible green results on the final implementation revision.
