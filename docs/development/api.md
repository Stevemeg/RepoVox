# Phase 1 API

API version `v1`; release `0.1.0`; fixture pipeline `phase1-fixture-v1`; immutable fixture object version `trusted-fixture-v1`. The approved artifact schema `2.1` remains untouched; harmless fixture objects are a separate contract and never claim to be analysis artifacts. [Local setup](local.md) · [Orchestration](orchestration.md)

All tenant routes derive identity from a signed server-issued session, then verify its nonce, expiry and revocation in PostgreSQL. Clients cannot submit `owner_id`. Every mutation except local sign-in requires `Origin: http://localhost:3000` and `X-CSRF-Token` equal to the `rv_csrf` cookie; sign-in itself requires that Origin. Browser requests go through `/api/v1` on Next.js, with the same cookies/headers. Cookie-authenticated direct API requests still need these protections.

| Method/path | Behavior |
| --- | --- |
| POST `/v1/auth/development/sign-in` | Body subject `alex` or `sam`; sets local session/CSRF cookies. Five sign-ins/minute/backend-observed client address; BFF clients share its address. |
| GET `/v1/auth/session` | Minimal account/environment/fixture availability. |
| POST `/v1/auth/sign-out` | Revokes session; clears both cookies. |
| GET/POST `/v1/projects` | List own live projects, or create title/canonical locator. Thirty creates/minute and 100 live records/user local resource guard. |
| GET/PATCH/DELETE `/v1/projects/{uuid}` | Read, rename, or immediately revoke owned project access and enqueue cleanup. Delete returns 202, not a completed-deletion claim. |
| GET `/v1/jobs`, `/v1/projects/{uuid}/jobs` | Persisted owner-only job summaries. Lists are bounded to 100 recent records. |
| GET `/v1/jobs/{uuid}` | Sanitized stages, attempts, state history and usage ledger; no private object keys/worker IDs/lease internals. |
| POST `/v1/projects/{uuid}/jobs` | Always 503 `secure_acquisition_unavailable` for an authorized owned project. A client SHA/synthetic flag cannot enable generation. |
| POST `/v1/development/projects/{uuid}/fixture-jobs` | Explicit fixture admission only when enabled; body fixture `normal`, `transient_once` or `permanent_failure`; required `Idempotency-Key`. Server creates synthetic snapshot. |
| POST `/v1/jobs/{uuid}/cancel` | Owner-only intent/epoch change and immediate fence revocation for these short trusted fixtures. |
| POST `/v1/development/jobs/{uuid}/retry` | New synthetic job with prior-job FK, new key/reservation; original terminal record immutable. |
| GET `/health`, `/ready`, `/openapi.json`, `/docs` | Non-tenant operational/schema endpoints; no internal-resource metadata. |

Bodies forbid extra fields. Canonical locators allow only HTTPS github.com/owner/repo, optional `.git` and trailing slash, with lowercase storage; query, fragment, credentials, ports and nested paths fail. Nothing clones or fetches this URL.

Stable responses include 401 session failure, 403 CSRF/origin rejection, 404 unauthorized-safe missing resource, 409 idempotency/terminal conflict, 422 invalid request, 429 quota/rate and 503 unavailable dependency/admission. Errors expose only `error.code` and correlation `request_id`, never SQL, supplied payloads or traces. Request logs contain method/status/correlation/duration only. Environment/session/storage values are never logged.

API routes call typed services; PostgreSQL procedures handle admission/worker transitions. The generated [OpenAPI contract](../../packages/contracts/openapi.json) is checked for drift. Full repository acquisition, consent/commit-resolution generation admission, cursor history, account deletion and production OIDC remain later-phase requirements.
