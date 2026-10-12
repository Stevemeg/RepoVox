# Phase 1 verification record

Review handoff, 2026-10-12. Independent validator: ChatGPT. Sole human maintainer/contributor: Stevemeg. Accepted Phase 0 baseline `e35d8ef8a8a53cb34e46271a9813b5332ea42c1f`. This is implementation evidence, not independent PASS, Phase 1 completion, merge authorization or permission to enter Phase 2.

## A. Repository state

Branch `phase1/saas-foundation` was created directly from the accepted SHA after `git fetch origin`. [PR #2](https://github.com/Stevemeg/RepoVox/pull/2) targets `phase0/foundation` because PR #1 is open/unmerged. Implementation SHA: `6ba3f6467e6933dd6642d7a62a9dba5f91f01aa7`, with [all four CI jobs green](https://github.com/Stevemeg/RepoVox/actions/runs/38206146094). An evidence-only follow-up commit records this report; its final SHA/clean-tree check is in the handoff. No merge, rebase, force push or accepted-history rewrite.

## B. Architecture

`apps/web` Next.js 16.4.0/TypeScript local BFF/UI; `apps/api/repovox` modular FastAPI factory/configuration/auth/typed services/schemas/SQL transactions/workers/storage; Alembic migration `0001`; public OpenAPI under `packages/contracts`; PostgreSQL/Redis/SeaweedFS and separate API/worker/dispatcher processes in Compose; tests, tooling and read-only CI. [ADR-009](../adr/0009-local-object-storage.md) records the permitted local S3 substitute. Diff against accepted Phase 0 shows no architecture, product, AI/research, security, operations/cost or roadmap changes. [Local instructions](../development/local.md).

## C. Backend

[API endpoint table](../development/api.md) documents implemented auth/session/logout, project CRUD, job lists/details/stages/attempts/history/usage, fixture admission/retry/cancel and health/readiness/OpenAPI routes. Two local identities use signed server sessions, nonce/CSRF hashes, one-hour expiry and revocation. Mutations require exact Origin plus CSRF; sign-in requires Origin and a durable rate limit. Production boot fails closed. Every identity/owner comes from validated server session, never submitted owner IDs. Real generation returns 503; fixture SHA/owner fields are rejected.

[Migrations](../development/migrations.md) documents PostgreSQL RLS/composite FKs, restricted roles, future tables and deliberately disabled destructive downgrade. Fresh CI migration applies successfully. Runtime connection/query/idle-transaction timeouts are bounded, with five pooled connections plus five overflow. Structured logs contain timestamp/service/environment/version/correlation/method/status/duration, with no URL/header/body/SQL/secret logging; raw Uvicorn access logging is disabled and configuration errors hide inputs. OpenAPI export/drift and strict types pass.

## D. Frontend

Responsive sign-in, overview, projects/details, jobs/stages/attempt/history/usage and settings. Persisted API data drives records; loading/error/empty/expiration states; keyboard dialog focus/escape; logout clears state and rejects stale session responses. Eleven component/API tests and the production build pass. One live browser flow proves redirect/sign-in/project create/fixture history/delete/logout, with desktop 1440px and mobile 375px screenshots outside Git. Visual QA caught and corrected a squeezed mobile notice; browser assertions check overflow and readable notice width. No playback, acquisition, real analysis, complete WCAG assessment or AI/media results claimed.

## E. Job orchestration

[Implementation](../development/orchestration.md) covers versioned guarded job/stage states, owner/key digest, atomic owner/global quota reservations, usage ledger, deadlines, fences/heartbeats, bounded retries, cancellation, outbox, repeated delivery, reconciliation and cleanup. All fourteen stage IDs are retained. Acquire writes/checks harmless private fixture JSON; filter deliberately ends at `failed/phase1_fixture_boundary`. Synthetic success is forbidden. Retry creates a new job/reservation, never resets terminal history. Deleted projects reject fixture replay and coordinate durable object cleanup. Real-service/fault assertions pass; no entire video pipeline success is claimed.

## F. Security

Actual PostgreSQL tests verify ENABLE/FORCE RLS, no-context zero rows, pooled-context reset, owner-only API/direct DB project/job/snapshot/stage reads, cross-owner mutation/deletion rejection and composite FK SQLSTATE 23503. Forged owner INSERT fails 42501. Application role cannot execute worker claims; worker cannot read tenant tables or execute admission; neither has superuser, BYPASSRLS, table ownership or executor membership. Migration SET ROLEs to the NOLOGIN function owner before revoking PUBLIC/granting execution; tests caught and fixed the original NOINHERIT grantor mistake.

Negative session/expiry/revocation/forgery, Origin/CSRF, production config/input redaction, owner/SHA fields, quota/rate, illegal/terminal transition, idempotency, early retry and stale publication tests pass. Real S3 tests prove checksums, conditional immutable writes, wrong-owner read/delete denial, anonymous 401/403 and cleanup. Runtime bucket credentials are shared within local trusted services, not per-tenant production IAM. SQL credentials must never be handed to end users: transaction owner context relies on the trusted authenticated service boundary. Production identity, acquisition/sandbox, inference/media/delivery, full deletion/restore and remaining [SEC-A–H](../security/threat-model.md#security-acceptance-suite) remain later gates.

## G. Executed checks and failures

Windows host: Python 3.12.0, Node 24.18.0, UV 0.11.29, Docker client/server initially 29.5.3. Fresh CI runtime: Ubuntu 24.04.5, Python 3.12, Node 24.18.0; container Python 3.12.12, PostgreSQL 16.13, Redis 7.4.9 and SeaweedFS 4.17. Commands below include historical failures as well as final observed checks.

| Exact command | Observed result |
| --- | --- |
| `uv venv .venv --python 3.12; uv lock; uv sync --frozen` | Completed; 99 resolved packages, 98 installed on Windows. |
| `.venv/Scripts/python.exe -m pytest tests/unit -q` | 14 passed, one Starlette/httpx deprecation warning; no service isolation claim. |
| `.venv/Scripts/python.exe -m ruff check apps/api tests tools/phase1*.py --fix` | Passed after formatting/string splitting/unused-import corrections. |
| `.venv/Scripts/python.exe -m mypy` | Strict checks passed for 23 source files after typed service wiring and validator corrections. |
| `.venv/Scripts/python.exe tools/phase1_contracts.py` | Deterministic public contract exported; no DB/network contact. |
| `docker compose up -d postgres redis minio storage-init migrate` | Failed: MinIO image unavailable. Official source distribution inspected; local choice changed by ADR-009. |
| `docker pull quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` and corresponding mc pull | Failed 401 from registry; no credentials changed or unauthorized workaround. |
| `docker pull chrislusf/seaweedfs:4.17`, `postgres:16.13-alpine`, `redis:7.4.9-alpine` | Pulled successfully. |
| `docker compose up -d postgres redis storage storage-init migrate` | Initially failed on psycopg `%I`; escaping corrected. Storage health check corrected to IPv4. Fresh CI reruns succeed. |
| `npm install`, `npm ci` in apps/web | Initially failed on full disk/invalid partial versions. Isolated lock generation and normal `npm ci` recovered the installation. |
| `npm audit --json` | Initially five high lint-transitive findings; controlled ESLint/TypeScript/hooks stack removed them. Re-audit reports zero. |
| `docker compose up -d --build postgres redis storage storage-init migrate` | Interrupted by full disk/read-only Docker filesystem; not a migration or runtime success. |
| `uv run ruff check apps/api tests tools/phase1*.py`; `uv run ruff format --check apps/api tests tools/phase1*.py`; `uv run mypy` | All CI quality checks pass, strict types across 23 source files. |
| `uv run python tools/check_docs.py`; `uv run python tools/cost_model.py --check`; `uv run python -m unittest discover -s tools -p 'test_*.py' -v`; `uv run python tools/phase1_contracts.py --check` | Accepted documentation/schema/state/evaluation/cost/attribution checks pass; 32 Phase 0 unit tests pass; OpenAPI has no drift. |
| `uv run pip-audit --local` | No known third-party vulnerabilities. Local RepoVox package is not on PyPI and is reviewed through code/tests instead. |
| `npm --prefix apps/web run lint`; `npm --prefix apps/web run typecheck`; `npm --prefix apps/web test`; `npm --prefix apps/web run build`; `npm --prefix apps/web audit --audit-level=high` | Lint, generated-route TypeScript, 11 tests, optimized Next.js build and zero-vulnerability audit pass locally/CI. |
| `docker compose up -d --build postgres redis storage storage-init migrate`; `docker compose run --rm --build tests` | Fresh CI migration/bucket setup exits zero; 29 tests pass (14 units, 15 real PostgreSQL/Redis/S3 integration tests). No integration skips. |
| `docker compose up -d --build --wait api web worker dispatcher`; `python tools/phase1_runtime.py` | Fresh CI full local stack boots; actual Redis stop/admission/recovery and graceful restart checks pass. |
| `cd apps/web; npx playwright install --with-deps chromium; npm run test:e2e` | Complete live browser flow passes; desktop/mobile screenshots captured in seven-day CI artifacts outside Git. |
| `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.30.0 git /repo --redact --exit-code 1` | CI Git-history secret scan passes. |
| `git diff --check`; `git diff --cached --check` | Pass before commits. |

First CI integration run: two failures/23 passes (nullable query typing and PUBLIC procedure execution). Explicit UUID typing and grants under the actual function owner fixed both; later real-role assertions pass. A GitHub temporary PR merge identity caused a documentation audit failure; CI now checks the authentic owner-authored head, with no history rewrite. Initial Vitest alias failure is fixed. One Starlette/httpx TestClient deprecation warning remains; no test is skipped. Superseded duplicate runs are cancelled by concurrency, not reported as successes.

Disk initially had ~0.6 GB free, later filled during build/install and made Docker read-only. Cache cleanup/reinstall recovered frontend dependencies; the owner freed ~68 GB. Controlled Docker/WSL restart did not recover the engine. Owner chose to restart Windows/Docker later. Windows-host live integration/browser/recovery reruns are therefore unexecuted; the actual fresh Linux Compose evidence is distinguished below. No factory reset, unrelated project deletion or local persistent-volume reset. Automatic review rejected direct recursive partial-node_modules cleanup as blocked by policy; normal npm reinstall later recovered it. GitHub connector PR creation returned 403; existing Git credentials were verified as Stevemeg and created the authorized draft without identity/permission changes.

Unchanged Phase 0 diagrams were not re-rendered. No actual repository acquisition/analysis, GPU/model/TTS/video, cloud deployment, production load/SEC-A–H or restore/PITR tests were run. CI has contents:read, generated ephemeral local credentials and no Git-write operations. [Final implementation CI](https://github.com/Stevemeg/RepoVox/actions/runs/38206146094) has four successful jobs; the evidence-only follow-up is checked again before handoff.

## H. Local runtime evidence

Windows Docker is still unavailable. Fresh Ubuntu Compose CI migration/storage setup exits zero; PostgreSQL/Redis/SeaweedFS/API/Next.js become healthy and worker/dispatcher consume messages. API health is alive, readiness reports generation unavailable. Tests/smoke observe sign-in 200, owned create 201, fixture admission 202, persisted job 200, deletion 202 then resource 404, logout 204 then unauthorized access. Browser checks execute through the actual BFF.

Small-workload assertions: twelve concurrent project creates/eight threads produce six isolated records/user; eight same-key admissions produce one job/reservation; eight quota contenders take exactly one remaining slot; eight lease contenders produce one claim. Twelve pooled owner/no-owner cycles do not leak context. Duplicate messages commit one output/settlement; expired fence heartbeat/publication fails; retries stop at three and deadlines/cancellation/terminal resets are enforced. Tests use explicit DB-clock failure injection, not an actual inference process crash.

Real Redis publication failure leaves outbox pending. Queue flush loses notifications; reconciliation republishes database-ready work. A real Celery subprocess executes fixtures. The live smoke stops Redis, admits a durable queued fixture, confirms queued state after six seconds, restarts Redis and observes one acquire output plus explicit Phase 1 boundary. Graceful worker/dispatcher restart preserves terminal history; cleanup revokes access immediately. Earlier successful suite duration 13.62s/browser flow 13.2s are suite timings, not throughput/RPS/p95/availability or GPU/video measurements. [Test commands and sample sizes](../development/testing.md).

## I. Attribution audit

Before every commit, the four required config/author/committer commands showed existing `Stevemeg <konabharath2004@gmail.com>` from global configuration; it was never changed. GitHub credential/profile and all twelve commits through implementation HEAD associate author and committer with Stevemeg (ID 146036166), with the same email. All are unsigned, not cryptographically Verified. The evidence-only commit is audited separately in the handoff.

Full `git log --all --format='%H %an <%ae> | %cn <%ce>%n%B'` audit shows only authentic owner identities/conventional messages, no Co-authored-by/Generated-by or bot attribution; workflows contain no commit/push operations. GitHub's temporary PR merge ref has platform attribution, is outside branch/main ancestry, and is not checked out by CI. Accepted SHA remains an ancestor; remote main remains `190a2787b2b9cdf7ddbd6391db1bd9079534746d`, Phase 0 remains the accepted SHA. Corrections are normal follow-up commits.

## J. Known limitations

Windows Docker still requires the owner's deferred restart; no current Windows live-stack success is claimed. Reproducibility/security/recovery evidence comes from fresh Ubuntu Compose CI. Development identity and shared local bucket credential are not production security. Minimal future persistence tables have no generation integrations. Full live-data purge/account/identity deletion, orphan/expiry sweep, object-version deletion, backup suppression/restore, cursor pagination, production OIDC/IAM and later Phase 0 gates remain deferred. Fixture completion cannot satisfy real generation success. No cloud resources, GPU purchase/provisioning, weights, paid APIs, training or Phase 2 acquisition work. Independent validation and owner authorization remain required before merge/Phase 2.

## K. Status

**READY FOR INDEPENDENT PHASE 1 REVIEW**, based on the actual fresh Linux Compose runtime, tests and visible CI evidence. The final handoff also confirms the evidence commit's CI/clean-tree audit. Windows Docker's external recovery remains disclosed above. This is not independent PASS, Phase 1 completion, merge authorization or Phase 2 entry.
