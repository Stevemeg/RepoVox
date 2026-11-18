# ADR-0024: GitHub OAuth identity for operator-provisioned accounts

Status: proposed; independent security review required before merge or any public
deployment. Date: 2026-11-18. Branch `feat/js-ts-frameworks-and-deploy-readiness`
(draft PR #17). Related: [self-hosted deployment guide](../operations/deployment-guide.md),
[threat model](../security/threat-model.md), [data model](../architecture/data-model.md).

The owner authorized a production identity adapter and HTTPS origin support. Core
migrations stay at `0004`, media at `m001`; `rv.job_guard`, `rv.video_disabled`, pilot
controls and every governance gate are unchanged.

## Context

`Settings.fail_closed` refused every production configuration because no production identity
adapter existed. The API's database role `rv_app` may only read its own `users` row (row-level
security) and cannot insert or update `users` or `quota_accounts`; the only identity function,
`rv.dev_identity`, returns the two seeded development identities. Signing people up on first
login would need a new privileged SQL function, which means a new core revision. The owner
chose an allowlist instead of a migration.

## Decision

- **Identity adapter.** `REPOVOX_AUTH_PROVIDER=github` uses the OAuth 2.0 authorization code
  flow (`repovox/auth/github.py`). `GET /v1/auth/github/login` sets a single-use 256-bit
  `state` and a PKCE code verifier (RFC 7636, S256) in `HttpOnly`, `SameSite=Lax` cookies
  (`Secure` on an `https://` origin) and redirects to GitHub with scope `read:user` and the
  code challenge. `GET /v1/auth/github/callback` compares the state with
  `hmac.compare_digest`, clears both cookies on every outcome, exchanges the code and
  verifier over TLS with a 10-second timeout and no redirects, and reads the account's
  numeric id. The access
  token is used for that one request and never stored, logged or sent to the browser.
- **Allowlist.** An operator provisions each allowed account with
  `python -m repovox.auth.accounts add` on the `migrate` service. It runs as `rv_migrator`
  acting as `rv_executor`, the mechanism that seeds the development identities. The owner
  id is `uuid5(fixed namespace, "github:<numeric id>")`, so a renamed login keeps its
  tenant. The callback reads the user row as that owner under RLS. It signs in only an
  active, provisioned account (403 `account_not_provisioned` otherwise) and issues the
  standard RepoVox session. `disable` stops sign-in and revokes open sessions.
- **Fail closed in production.** Production refuses development identities, fixtures,
  synthetic sources and any adapter other than GitHub with a non-empty client id and
  secret. The origin must be an exact `https://host[:port]` (no path, query, fragment, user
  info or wildcard), or a loopback origin only with `REPOVOX_ALLOW_LOOPBACK_ORIGIN=true`.
  Development and test keep every earlier rule and may exercise the GitHub adapter, never
  together with the development identities.
- **Browser.** The sign-in page asks the API's public `/v1/auth/config` on the server and
  offers either "Continue with GitHub" or the development identities, never both. If the
  API cannot answer, it offers neither. The web proxy allows the two GitHub routes as GET
  only; only the callback may carry a query (at most 2 KiB), and only these two routes pass
  a redirect to the browser.

## Consequences

- No self sign-up: every account is provisioned by an operator, and display name and email
  come from provisioning, not from GitHub.
- The GitHub client secret is in `.env` and is given to every service that validates
  production settings (`api`, `worker`, `dispatcher`, `media-worker`), not only the API.
- `httpx` moves from a development to a runtime dependency (`httpx`, `httpcore` added to
  the runtime profile, which `pip-audit` covers).
- A failed callback returns a JSON error page rather than the sign-in page.
- There is no per-client rate limit on the callback. A forged state is refused before any
  outbound request, but valid-looking codes reach GitHub.
- Not reviewed: TLS termination, reverse-proxy configuration and GitHub OAuth App
  settings are operator responsibilities, documented in the deployment guide.
