# Isolated Node/Next security remediation

Date: 2026-10-23. Status: implementation under independent review; no merge or
deployment authorization. Branch `security/node-next-remediation`, stacked on
exact PR #12 `119f8bdd62578d8d7fa015ec8ebefe2f8b19bec8`. PRs #9–#12 must remain
draft and unchanged. This correction does not confer repository-wide PKI acceptance.

## Upstream evidence and selected pins

The [October 14 Next.js notice](https://nextjs.org/blog/nextjs-security-update-october-14-2026)
and upstream advisories identify 16.4.1 as the patched 16.x minimum. We select
the requested exact **16.4.2**, the subsequent stable maintenance release, matching
the existing audit recommendation. The [16.4.2 release](https://github.com/vercel/next.js/releases/tag/v16.4.2)
includes maintenance corrections in addition to those security fixes.

| Advisory | Issue | Patched dependency |
| --- | --- | --- |
| [GHSA-2464-fhr4-w9xw](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw) | SVG image optimization memory corruption/RCE on glibc | Next ≥16.4.1; sharp ≥0.35.5 |
| [GHSA-p3m5-59mp-jv5r](https://github.com/vercel/next.js/security/advisories/GHSA-p3m5-59mp-jv5r) | App Router Server Actions CPU denial of service | Next ≥16.4.1 |
| [GHSA-673q-mjm6-r5xr](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr) | Cache Components typed-array RCE | Next ≥16.4.1 |

RepoVox uses App Router. Source inspection found no `next/image`, `use cache`,
`use server`, Cache Components enablement or SVG optimization override. The BFF
uses Route Handlers, not Server Actions. This bounds observed feature usage; it
is neither exploitation testing nor a reason to retain vulnerable framework code.
React/React DOM remain 19.3.0. Next's compiled internals are updated with Next.

The [October 21 Node security announcement](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)
and [24.22.1 release](https://nodejs.org/en/blog/release/v24.22.1) establish the
exact **24.22.1 LTS** pin. The official vulnerability index still lists that release
as latest on inspection. It refreshes NSS roots to 3.131.1, blocks compromised
public keys and updates OpenSSL 3.5.9, c-ares 1.34.9 and Undici 7.30.1. Relevant
24.x corrections include DNS NUL validation (CVE-2026-105482), TLS host/IP validation
(105483/106069/106072), Brotli memory safety (111497), HTTP agent guard (105481),
snapshot entropy (106074) and filesystem permission checks (106073). We do not
claim independent exploit validation of these upstream corrections.

## Complete installation surface and minimal resolution

- `apps/web/package.json` and lock: Next 16.4.0 → 16.4.2; exact Node engine added.
- `.node-version`: 24.22.1; project `.npmrc`: strict engine/HTTPS, official registry.
- Both frontend Docker stages: 24.18.0-alpine → 24.22.1-alpine, pinned to the
  official multi-platform index `sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53`.
- Frontend and browser setup-node use 24.22.1. Both existing workflows run for
  the new PR base. All previous quality/security jobs remain mandatory.
- README/current local runbook use 24.22.1. Historical verification reports retain
  the versions actually tested; they are not current installation instructions.
- Playwright runs under the selected host Node and targets the rebuilt standalone
  web container. No separate browser-specific Node installation is configured.
- No repository-controlled alternate Node image, custom CA bundle or trust override
  was found. GitHub action-internal JavaScript runtimes and Chromium's own trust
  store are distinct upstream dependencies, not claimed repaired by this pin.

Controlled `npm install --package-lock-only --ignore-scripts --no-fund --audit=false`
used the verified new runtime; the separate mandatory audit is never disabled.
No `audit fix --force` or broad refresh was used. There are still **312** lock
records: **301 are fully unchanged**; root metadata and these ten packages change:
`next`, `@next/env`, and `@next/swc-{darwin-arm64,darwin-x64,linux-arm64-gnu,linux-arm64-musl,linux-x64-gnu,linux-x64-musl,win32-arm64-msvc,win32-x64-msvc}`,
all 16.4.0 → 16.4.2 with new registry integrity/resolved values. The Next sharp
requirement changes ^0.35.4 → ^0.35.5; actual sharp remains **0.35.5**, platform
sharp packages remain 0.35.5 and libvips package artifacts remain **1.3.4**.
No override or unrelated dependency change is introduced.

## Binary, image and trust evidence

The Windows portable ZIP was fetched over normal validated HTTPS using PR #12's
hash-verified patched public CA bundle, outside Git/OneDrive. Its hash matches both
the distribution SHASUMS and release page. The signature file is preserved; a
PGP signature is not claimed independently verified. No global runtime is replaced.

| Artifact | SHA-256 |
| --- | --- |
| Official node-v24.22.1-win-x64.zip | d2046d28c2c3dcd211ac5145c0bf30e2047ef9dfb306693c8c6e2eccd8b95fa5 |
| Extracted official node.exe | d702daa815eabbff763c7d3808e235cf031cf2ca70211b56847bc72f51e240e5 |
| Sorted root DER fingerprint list, LF terminated | 077fe6a7639d6ef14a8fe2661e92b064f7701b8df283e1445f38a66a47b07acb |

`tools/security_node.mjs` reads the **actual** executable/version/hash and Node
`tls.getCACertificates` default/bundled stores, parses every PEM with
`X509Certificate`, and emits every DER SHA-256. The tested Windows runtime has
**118 bundled and 118 effective roots**, equal sets. Both banned anchors are absent:

- emSign ECC Root CA G3: `86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b`.
- AAA Certificate Services: `d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4`.

The checker rejects a wrong Node version, empty stores, banned roots, changed
effective roots, startup flags and presence of `NODE_EXTRA_CA_CERTS`,
`NODE_USE_SYSTEM_CA`, `NODE_OPTIONS`, `NODE_TLS_REJECT_UNAUTHORIZED`, `SSL_CERT_FILE`
or `SSL_CERT_DIR`. It withholds override values and never edits trust. This strict
repo profile forbids silent custom/system-CA fallback; it is not an arbitrary Node
configuration validator. Unit policy mutations are explicitly synthetic; CLI,
container and CI trust inventories are real, unmocked X509 inspection. A clean
inventory establishes active configuration, not universal certificate validity.

Official Docker Hub registry manifest bytes and content-digest are independently
recorded before pinning. Fresh CI builds inspect trust in both build/runtime stages,
then inspect the **running** web container and browser host, record actual image
IDs/digests and installed Next/sharp/libvips. The build retains standalone output,
nonroot `node` user, existing Compose isolation and all response security headers.

## Verification and evidence location

Reproduce with exact Node 24.22.1:

```sh
node tools/security_node.mjs
node --test tools/security_node.test.mjs
cd apps/web
npm ci
npm ls next sharp
npm run lint
npm run typecheck
npm test
npm run build
npm audit --audit-level=high
npm run test:e2e
```

The last command requires the disposable full local application stack. The new
browser regression checks exact CSP/headers, absent framework disclosure,
unauthenticated rejection, BFF path/query/body-size boundaries and real-session
CSRF denial, alongside the unchanged full user workflow. Audit success is not
exploit testing. Actual Linux/container/SQL/media results and final-head links
are recorded in the draft PR handoff after completion; unavailable checks must
remain unverified, never inferred from Windows tests.

Original commands, stdout/stderr, exit codes, package manifests, lock-record diff,
public root fingerprints, artifact hashes and PR metadata are preserved outside
Git/OneDrive at `C:\Users\konab\AppData\Local\RepoVox\node-next-6423194505f644549457b138697536b7`.
An early evidence-printer Unicode encoding failure occurred **after** a successful
Node test subprocess and durable result capture; it is preserved. The logger's
console encoding was fixed without changing the test or its recorded exit status.
The first local lint/type invocations overlapped the initial clean installation
and failed on missing executable shims. Their original errors are preserved;
both checks were rerun only after the successful installation completed.

## Remaining debt, boundaries and reviewer checklist

The [Python remediation](python-trust-remediation.md) remains intact. Its dormant
botocore 1.43.111 fallback PEM has 127 roots, SHA-256
`ed93d6346236d4f0278f617f5245091f37d001806a49ce42ce0ad5bec858d28e`, including
AAA. The tested SDK selects patched certifi; the fallback remains unresolved.
The Windows global root store still includes AAA; unrelated global Python/Node/uv
installations are not remediated here. Evidence is retained from PR #12; these
stores are not modified or represented as clean. Future work needs separately
reviewed upstream SDK bundle replacement, owner-operated Windows trust update and
an inventory/upgrade of unrelated installations. Do not hand-edit third-party PEMs,
disable TLS or extrapolate scoped audit success to repository-wide acceptance.

Review the exact ten-package lock diff, image manifest/actual binary identities,
real root inventories, negative trust checks, browser security assertions, complete
final-head CI and unchanged original PR metadata. Owner and independent security
review remain required. No accepted analyzer/scorer, source-fact identity, SQL or
migration 0004, custody, retention, AWS behavior, Python lock/bootstrap or media
implementation changes. No real data, owner key, AWS API/credentials, pilot, A/B,
reveal, scoring, spending, deployment, merge or Phase 3/6. CR-04 remains pending;
EVAL-ENTRY UNFROZEN; historical 0/84 unchanged; historical November 14/16, 2026
deadlines and all protected custody remain untouched.
