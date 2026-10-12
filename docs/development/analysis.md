# Phase 2 repository analysis

[Pipeline](../architecture/pipeline.md) · [Schema 2.2](../architecture/analysis.schema.json) · [ADR-0010](../adr/0010-phase2-static-analysis-boundary.md) · [Isolation](../adr/0011-parser-process-isolation.md) · [Evaluation preparation](evaluation-preparation.md)

## Admission and pinning

Local `REPOVOX_ANALYSIS=true` enables authenticated development analysis only.
`POST /v1/development/projects/{project_id}/analysis-jobs` requires CSRF/origin,
an owner-scoped project, an idempotency key and
`{"processing_acknowledged":true}`. Stage 1 validates a real URL parser result against
exact `https://github.com/owner/repository`, optional `.git` and trailing slash.
No credentials/ports/query/fragment/encoded path/alternate host/Unicode host/tree/blob
URL is accepted. GitHub metadata must be public and match the canonical locator.
Default branch is resolved once to forty lowercase hexadecimal SHA characters.
The browser BFF explicitly allows these admission/result routes. Admission's proxy
timeout is 15 seconds around the 10-second aggregate GitHub resolution and bounded DB
publication; other routes retain their existing 10-second timeout and strict allowlist.

Identical idempotency requests return the persisted job without another lookup.
Explicit retry uses the prior immutable snapshot, even if HEAD changes. New analysis
admission resolves current HEAD. Renames/redirects are rejected rather than changing
repository identity. `repository_private`, `repository_removed`,
`repository_not_found`, `github_rate_limited`, `github_access_denied`,
`github_timeout`, `github_unavailable`, `github_invalid_metadata` and
`repository_identity_changed` are sanitized; provider bodies never cross the API.
Unauthenticated GitHub 404 is ambiguous, as documented in ADR-0011.

## Hostile archive and source handling

Only internally constructed codeload archives at the pinned SHA are requested.
Streaming bounds apply without Content-Length, as well as declared size and aggregate
time. TLS checks and connection-time DNS pinning are independent of repository config.
API credentials are server-managed and stripped from parser environment and artifacts.

Extraction uses a fresh job scratch directory, exclusive regular-file creation and
resolved containment. No `extractall`. It rejects links/devices/FIFOs/sparse members,
absolute/parent/drive/UNC/NUL/control paths, duplicate members, NFKC/case collisions,
multiple roots, nested archives, malformed tar/gzip, depth/resource overflow and hidden
non-NUL data after tar filename terminators. Tar expansion includes headers/padding,
not only declared files. Scratch is removed on handled exit. Worker container tmpfs
bounds interrupted scratch; abnormal container death clears it on container removal.

All bytes are screened before original archives are published. Known credential/key
patterns fail `secret_detected`, including secret-looking fixtures. Suspicious entropy
is redacted in excerpts while preserving original LF line numbers and redaction spans.
`.env`/key/credential paths never produce display evidence. Scanners have false
positives and false negatives; there is no user override or perfect-detection claim.
Only original byte hashes/line offsets ground evidence. Upstream links are convenience
citations, never verification authority.

## Static intelligence and coverage

Pinned Tree-sitter grammars parse Python, JS/JSX/MJS/CJS, TS/TSX. Extract modules,
classes/functions/methods, parameters, imports, exports, decorators, call sites and
Python main guards. Bounded JSON/TOML readers inspect dependency constraints and entry
targets; lock versions are null. Imported FastAPI/Flask/Express bindings plus constructor
syntax support qualified framework/application/route candidates. README words alone
do not establish implementation use. No repository installs/imports/tests/hooks/LFS/
submodules/scripts/plugins run; package lifecycle and README commands are data.

Every regular file has a manifest hash/size/classification/decision/reason. Vendor,
generated/build/minified/binary/invalid UTF-8/unsupported/oversized/sensitive paths are
excluded or failed explicitly. Tests are included in byte coverage but deprioritized
for primary entry selection. Whole-file parser errors contribute zero parsed bytes.
At least one supported non-test file and 90% eligible supported bytes must parse.
Eligible overflow fails; exclusions never secretly alter the threshold.

All modules are analyzed within supported scope; no implicit dominant-component claim.
Literal local import resolution is qualified. Calls/dynamic dispatch/package search
paths remain unresolved. Qualified flows describe bounded static import reachability
from entry candidates, not runtime order. Technical claims use exact supported
templates. The verifier re-parses original bytes, reconstructs symbols/graph/entries,
checks SHA/path/hash/ranges/excerpt/rule/IDs, and assigns verified/inferred/documentation-
only/unsupported. Semantic edits, invented evidence or graph data cannot self-certify.
Potential README/implementation stack mismatch remains explicit for human review.

## Durable publication and visibility

Migration 0002 adds real snapshots, stage input digests, immutable owner/job/stage/
snapshot-bound artifacts and results, forced RLS and composite FKs. Upload uses private
conditional-create keys and read-back checksums. `rv.finish_analysis` validates the
current lease/fence and complete upstream digest chain in the publication transaction.
Stale workers cannot publish. Restarts reuse committed bodies; verification intentionally
re-extracts original source. Existing attempts, quota locks, retries, reconciliation,
cancellation and deadlines remain authoritative. No Redis result state is introduced.

Stage 9 commits a result then ends generation with `phase2_pipeline_boundary`.
`GET /v1/development/jobs/{job_id}/analysis` returns the owner-only verified bundle;
source archives/intermediates and evaluation gold have no normal project API.
Bodies expire at admission +24 hours; worker reconciliation removes expired terminal
job object prefixes, including orphan uploads. Project deletion revokes access first.
Full account/backup erasure/restore guarantees remain later deployment gates.
Success/media inserts and production generation remain disabled.

CPU, peak child RSS, handler wall time and artifact bytes are recorded without invented
prices. Local output/fact ceilings are documented in the PRD; they may reject large
repositories even when basic archive/source caps fit. A green fixture run does not
prove runtime behavior, performance, complete architecture or production security.
