# Phase 2 verification and independent review handoff

Historical submission reviewed at `b35d93d`. Evaluation-tooling findings R2-01/R2-02
and their superseding verification are recorded in [review corrections](phase2-review-corrections.md).

Date: 2026-10-12. This records observed engineering results, not independent acceptance
or production readiness. The official corpus remains UNFROZEN. No Phase 3 work, model
download/training, media generation, deployment, paid infrastructure or merge occurred.

## A. Repository and PR

- Branch: `phase2/repository-intelligence`; base: `phase1/saas-foundation` at accepted
  `ec09b733ab3ceffe592ad96d07902b92596dfd1b`.
- [Draft stacked PR #3](https://github.com/Stevemeg/RepoVox/pull/3).
  Initial implementation revision: `1d1a922ead69a861917679321b7567f83a255787`.
  Final engineering revision: `6e1acf1253f152d322fe966a5b305386bbf42dac`.
  Follow-up verification/corpus-integrity commits retain this history. The PR head and
  final handoff identify the final SHA; a report cannot embed its own commit hash.
- Fetched and inspected remote main (`190a2787b2b9cdf7ddbd6391db1bd9079534746d`),
  Phase 0/1 branches and PRs #1/#2. Both remain open/unmerged at their accepted heads.
  Accepted Phase 0 `e35d8ef8a8a53cb34e46271a9813b5332ea42c1f` and Phase 1 are
  ancestors. No history rewriting, force push or retargeting was performed.
- Provider payloads, source excerpts, upstream license copies, screenshots and generated
  logs are ignored local artifacts, absent from Git. Working-tree and attribution checks
  are repeated at final handoff.

## B. Implementation architecture

The existing Next.js/FastAPI/PostgreSQL/Redis-Celery/outbox/lease engine is extended.
`apps/api/repovox/analysis/` contains `github`, `transport`, `archive`, `privacy`,
`filtering`, `parser`, `graph`, `documentation`, `grounding`, `contracts`, `sandbox`
and `runner`. `services/jobs.py`, API routes, storage and the existing worker integrate
these modules. `apps/web/src/components/analysis-panel.tsx` displays verified bundles;
the existing workspace provides development admission, pinning and progress.

[ADR-0010](../adr/0010-phase2-static-analysis-boundary.md) introduces static artifact
envelope 2.2/PKM `analysis-1.0` while retaining accepted media/Director 2.1 contracts.
There is no downstream Director adapter or Stages 10–14 implementation.
[ADR-0011](../adr/0011-parser-process-isolation.md) records Linux process isolation,
GitHub's ambiguous 404 and the local S3 capacity correction. The parser is a constrained
trusted subprocess, not a second job engine or microservice.

## C. GitHub acquisition

`urlsplit` plus explicit ASCII hostname/netloc/path rules accepts only HTTPS GitHub
owner/repository, optional `.git` and trailing slash. Credentials, ports, query/fragment,
lookalikes, IPs, Unicode host tricks, encoded paths, traversal and tree/blob URLs fail.
Canonical identity is lowercase. Approved API metadata must match that identity and be
public. Default-branch HEAD resolves once to a complete 40-character SHA. Idempotent
replay and explicit retry retain the snapshot; downstream acquisition constructs only
`codeload.github.com/{owner}/{repo}/tar.gz/{sha}`. Renames/redirects are rejected.

Dedicated stdlib HTTPS transport ignores repository config and proxies. At connection
time it bounds DNS, rejects any non-public answer (including mapped/transition and
special translation networks), connects to the checked numeric IP, and verifies its peer
and TLS with original-host SNI/system trust. No redirects are followed. MIME, duplicate
headers and response encoding are checked. Aggregate timers and streaming counters
enforce limits without trusting Content-Length. API credentials, if configured, stay
server-side and never reach codeload or the parser environment.

Limits: compressed 100 MiB; extracted regular data 250 MiB; 10,000 regular files;
eligible file 1 MiB; 5,000 eligible supported files/100 MiB; bounded nesting depth,
tar-header/padding expansion and static-fact/output caps. Fresh bounded scratch uses
exclusive creation and resolved containment. Absolute/parent/drive/UNC/NUL/control
paths, links, devices, FIFOs, sparse entries, duplicates, normalization/case collisions,
multiple roots, nested archive payloads and malformed/overflow archives fail.

Sanitized codes distinguish invalid URL, invalid metadata, private metadata, missing,
removed, access denied, rate limited, unavailable, timeout, blocked address, redirect,
response type/encoding, unsafe archive and resource overflow. GitHub unauthenticated
404 does not reveal whether a repository is private or absent; it remains
`repository_not_found`, rather than fabricating a distinction. See the exact behavior
and limits in [analysis documentation](../development/analysis.md).

## D. Source intelligence

Real pinned Tree-sitter parsers: Python 0.25.0, JavaScript 0.25.0, TypeScript 0.23.2,
runtime 0.25.2. Supports `.py`, `.js/.jsx/.mjs/.cjs`, `.ts/.tsx`. Modules, classes,
functions/methods/parameters, imports/reexports/CommonJS requires, exports, decorators,
call expressions and Python main guards have stable IDs, original hashes and ranges.
Bounded JSON/TOML readers provide declared dependency/entry configuration. Lifecycle
scripts, Git hooks/submodules/LFS, imports, setup scripts, submitted tests and README
commands are never executed or installed.

A bounded registry initially recognizes imported FastAPI, Flask and Express bindings
with structural construction/route/listen candidates. Deterministic ranking deprioritizes
tests. Unresolved declarations and absent entry points remain explicit. All eligible
supported modules are examined; unsupported components are listed, without claiming
whole-monorepo semantic understanding. Local literal imports may resolve statically;
calls remain unresolved without lexical-binding/dataflow proof. Qualified flows are
static import reachability, not observed runtime execution. Purpose, security,
performance, correctness and successful external connections are not certified.

## E. Project Knowledge Model

[Strict schema](../architecture/analysis.schema.json) covers Stages 3–9 payloads,
snapshot/owner/input digests, graph, symbols, candidates, qualified flows, dependency
declarations, claims, evidence, ledger, coverage, omissions and explicit limitations.
Pipeline `phase2-static-v1`, acquisition `github-archive-v1`, rules `static-rules-v1`
and grammar versions persist. Original bytes are preserved for evidence hashing.

Every discovered regular file has hash/bytes/language/classification/decision/reason.
Vendor/build/generated/minified/binary/invalid UTF-8/unsupported/oversized/secret paths
are excluded or failed explicitly. Whole-file parser errors contribute zero parsed
bytes. Acceptance requires at least one successfully parsed non-test supported file and
90% of eligible supported source bytes; thresholds are not lowered.

Evidence uses original LF byte-to-line mapping, 1-based inclusive bounds, SHA/path/hash,
rule/symbol IDs, safe bounded excerpts/redaction spans and escaped pinned permalinks.
For example, actual evidence `e-0df43a4829e24a72bdb03e533ae4d101` cites
`src/sample/__init__.py`, lines 1–3, SHA-256
`78952151cc8ec61f2cc1f983660ad4ba0a415676c859291b671726c13e46983c` at
[pypa/sampleproject pinned source](https://github.com/pypa/sampleproject/blob/621e4974ca25ce531773def586ba3ed8e736b3fc/src/sample/__init__.py#L1-L3).
The link is not the verifier: original privately acquired bytes remain authoritative.

Stage 9 rehashes/reparses original files and reconstructs symbols/config/graph/entries/
flows. It checks every evidence ID, snapshot SHA, path, hash, boundaries, display excerpt
and supported rule, then matches narrow claim templates. Exact source declarations
may be verified; unresolved references remain inferred; README mentions are
documentation-only; invented/changed/semantic unsupported claims cannot self-certify.
Serialization preserves verdicts. Potential documentation/implementation conflicts are
explicit, with human semantic review still required. Canonical examples remain synthetic;
live source excerpts stay outside Git and normal project APIs cannot expose gold data.

## F. Job orchestration

Additive Alembic 0002 preserves existing data and extends immutable snapshots, owner/
job/stage/snapshot composite references, forced RLS, analysis results, input/output
digests, version/coverage metadata, attempts, usage and recovery. Stage 1 runs real
resolution at authenticated admission and is auditable; Stages 2–9 use existing
outbox/leases/fences/attempts/reconciliation. Private conditional uploads and checksum
read-back precede atomic pointer publication under the current fence. Unknown commit
outcomes do not delete a possibly committed object.

Completed committed artifacts are reused after restart, with checksummed digest chains;
Stage 9 intentionally reparses. Corruption fails permanently; transient failures have
bounded retry/backoff. Cancellation, lease expiry, job deadline and stale publication
are guarded. CPU, RSS, wall-time and byte observations are recorded without invented
costs. Terminal source/artifacts expire after 24 hours, including orphan-prefix cleanup;
Linux cleanup handles bounded terminal scratch. Project tombstones immediately revoke
access. Production deletion/backups/restore and cloud IAM remain later deployment gates.

Development POST requires auth/owner/CSRF/origin/idempotency/processing acknowledgement.
Owner-only GET returns the final verified bundle. Stage 9 terminates the existing job
as `failed` with `phase2_pipeline_boundary`; Stages 10–14 remain unimplemented/failed.
This auditable static result is not successful video generation. Fixture regressions
retain `phase1_fixture_boundary`. The normal generation endpoint returns 503; no MP4
or successful video-generation job is created.

## G. Evaluation corpus

[Actual manifest](../ai/evaluation-corpus.manifest.json): UNFROZEN; reviewer
**PENDING OWNER APPOINTMENT**. Official candidate/approved families: **0/0**;
EVAL_DEV/EVAL_TEST: **0/0**; newly owner-authored hidden families **0**; approved
adversarial variants **0**; independently reviewed gold claims/edges **0/0**.
Engineering test fixtures and licensed smoke samples are not corpus admission.

`evaluation/corpus.py`, `evaluation/scoring.py`, `tools/phase2_corpus.py` and the
[preparation workflow](../development/evaluation-preparation.md) implement actual
source-manifest intake/screening/fingerprints, rights/reviewer-access/attribution/retention
records, family/derivative grouping, source-citation authoring checks, actual-human
appointment provenance, independent preparer/reviewer requirements, disagreements/
adjudication/approval hashes, split controls, freeze digests and withdrawal lineage.
Freezing rechecks all source inventory and fingerprints, including uncited files.
Physical provenance documents and actual cited source are required, not hash-shaped
strings alone. External custodian POSIX 0700/0600 storage is absent from API/worker
mounts and database grants. Training/calibration are denied for both evaluation splits;
held-out prompt/development access is denied. Registered final access requires freeze.

Freeze requires the approved 20 development/60 held-out, 20 each held-out language
slice, 10 hidden newly owner-authored, 100 variants over at least 20 held-out families,
600 source-grounded claims/120 supported edges, rights/reviews/anti-contamination
evidence. Current freeze command correctly returns BLOCKED/exit 2. No appointed human,
owner rights approvals, gold reviews, provisioned protected corpus or frozen split exists.
These are exact EVAL-ENTRY blockers. Software checks do not authenticate a human's
identity or review quality; independent acceptance must inspect actual provenance.

An additional constrained Linux custodian probe used an empty labelled tooling record:
external store owner UID 10001, directory 0700/file 0600 and duplicate publication denial
passed; an actual process under UID 10002 received PermissionError reading it. The
network-disabled probe container was removed. This demonstrates the implemented local
access boundary, not a provisioned held-out corpus or appointed reviewer.

Independent CPU scoring imports no analysis implementation. It compares graph, symbols,
entries, citation byte validity and gold verdicts with explicit denominators; unscored
claims remain unscored rather than inventing false-verification results. Aggregate counts,
language coverage/errors/conflicts/safety observations are available. No independent
benchmark scores exist without reviewed gold. No held-out tuning or model weights.

## H. Security validation

Offline tests exercise canonicalization/SSRF/DNS rebinding/private IPv4/IPv6/metadata,
strict controlled TLS, timeout/rate/status/header/stream guards; hostile tar entries,
collisions/bombs/count/size/depth/malformed input; Python/TS parse errors and coverage;
unresolved/dynamic relationships, README conflicts, forged symbols/ranges/hashes/evidence;
secret canaries, redaction LF ranges, and setup/lifecycle/import/hook/submodule/README
execution tripwires. The canary test checks HTTP/log/worker-message sanitization and no
private-source object publication. Harmless malicious-looking repository code stays data.

Linux sandbox tests demonstrate non-root UID, read-only base, no Docker socket,
bounded tmpfs/CPU/memory/PIDs/rlimits, no credentials, seccomp socket/exec/process/mount
denials and Landlock denial of unrelated files/scratch writes. Acquisition's dedicated
transport has GitHub-only source fetch privileges; the parent still uses required
PostgreSQL/Redis/S3 service connections. Parsing has no network. Unsupported isolation
platforms fail; Windows-host unit tests do not claim Linux containment.

Actual PostgreSQL two-owner/RLS/composite-FK tests, owner-private object checks, current-
fence publication, duplicate delivery, lease/deadline/cancellation/retry/corrupt artifact,
HEAD pinning, concurrent immutable snapshot reuse and two killed worker fault probes pass.
Lease/backoff test clocks are advanced explicitly; no recovery SLA is inferred. Production
OS-image CVE scanning, managed IAM, cloud egress, kernel fleet validation, capacity/load
and backup/deletion restore remain unexecuted deployment gates. Secret detection is
conservative and incomplete; rejected legitimate fixtures are not overridden.

## I. Automated verification

Environment: Windows PowerShell, host Python 3.12.0, Node 24.18.0; Docker Engine 29.5.3
Linux/WSL kernel 6.18.33.2; Python 3.12.12 containers, PostgreSQL 16.13, Redis 7.4.9,
SeaweedFS 4.17. Existing unrelated service occupied port 8000; only this disposable
project used an ignored override to 8001. No other project was stopped or reset.

| Exact command / check | Observed outcome |
| --- | --- |
| `uv run ruff check apps/api tests tools/phase1*.py tools/phase2*.py` | Pass |
| `uv run ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py` | Pass |
| `uv run mypy` | Pass, 40 source files |
| `uv run pytest tests/unit -q` | 163 passed, 62 warnings, 15.39s; targeted corpus follow-up 17 passed |
| `docker compose -p repovox-test -f docker-compose.yml -f .artifacts/phase2-ports.yml run --rm --build tests` | 187 passed, 64 warnings, 45.80s before final corpus follow-up |
| CI `docker compose run --rm --build tests` on final engineering revision | 188 passed, 64 warnings, 32.36s; actual clean migrations/services |
| `uv run python tools/check_docs.py` | Pass: 31 required paths, 41 Markdown, 304 links, 9 JSON |
| `uv run python tools/cost_model.py --check` | Pass, retained estimates/contracts; no spending |
| `uv run python -m unittest discover -s tools -p 'test_*.py' -v` | 32 passed |
| `uv run python tools/phase1_contracts.py --check` | Pass |
| `uv run python tools/phase2_contracts.py --check` | Pass |
| `uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json` | Actual zero counts, UNFROZEN |
| Same corpus command with `--action freeze` | BLOCKED, exit 2, expected unmet prerequisites |
| `npm --prefix apps/web run lint` / `run typecheck` / `test` / `run build` | Pass; final 17 tests, including new proxy admission/result/denial regressions |
| `npm --prefix apps/web run test:e2e` | 1 passed, 16.6s; original fixture browser flow retained |
| `uv run pip-audit --local` | No known vulnerabilities; local RepoVox package has no PyPI audit entry |
| `npm --prefix apps/web audit --audit-level=high` | 0 vulnerabilities |
| Gitleaks 8.30.0 `git /repo --staged --redact --exit-code 1` | Pass after constructing entropy test canary at runtime |
| `git diff --check` / staged equivalent | Pass |

Mermaid CLI 11.15.0/system Chrome rendered all five accepted architecture/data/Director
diagrams to ignored temp SVGs. Rendering is not a semantic diagram audit. Phase 1 runtime
smoke used `COMPOSE_PROJECT_NAME=repovox-test`, the ignored port override in `COMPOSE_FILE`,
`REPOVOX_RUNTIME_API_URL=http://localhost:8001`, then
`uv run python tools/phase1_runtime.py`: real Redis interruption/recovery, durable outbox,
graceful worker/dispatcher restart and immediate project/logout revocation passed.

Live API/Celery analysis of sampleproject: nine succeeded stages, terminal
`phase2_pipeline_boundary`, 50 verified/21 inferred, 39 citations, 43.25s;
Sam's result GET 404 and normal generation POST 503. Test project deleted afterward.
Frontend unit tests cover escaped excerpts, safe pinned links and labelled uncertainty.
The actual Chromium browser development workflow also passed consent gating, live
sampleproject Stages 1–9, matching SHA and 50 verified/21 inferred display, disclosure
of source permalinks, mobile document-width containment, project deletion and sign-out.
Generated desktop/mobile screenshots and the probe report remain ignored local evidence.

Failures repaired: initial migration function ownership/schema privileges; local S3
volume allocation; local port/browser availability; source scanner pathological
regex cost; parameter/CJS/reexport/config dedup extraction; shared immutable snapshot
admission race; ambiguous transport headers; final lint/canary false positive. The live
browser probe caught missing analysis routes in the BFF allowlist, repaired in
`6e1acf1` with four regression cases. Analysis admission has a bounded 15-second proxy
timeout around its 10-second GitHub resolution and DB publication; retained routes keep
their accepted 10-second timeout. A temporary helper's hidden citation locator was
corrected to open the existing evidence disclosure before inspecting the link. The full
suite's one Redis-queue assertion failed with live consumers running (186 passed/1 failed);
stopping only test-stack worker/dispatcher yielded all 187 passing without weakening the
accepted test. A temporary live helper initially used a nonexistent generation route;
the corrected helper passed. Deprecation warnings: native parser timeout API, existing
Starlette/httpx test client and Alembic legacy path separator; none suppressed.

GitHub Actions uses four least-privilege jobs (Python, frontend, real-service integration/
browser and history secret scan). Final engineering
[PR run 38262645038](https://github.com/Stevemeg/RepoVox/actions/runs/38262645038) on
`6e1acf1253f152d322fe966a5b305386bbf42dac` completed successfully in all four jobs:
163 offline tests (9.63s), 188 container tests (32.36s), 17 frontend tests, one browser
test (13.2s), actual recovery smoke, lint/types/build/contracts/audits/history scan.
Job logs and conclusions were inspected. The final documentation revision is checked
again before handoff; its results are linked in the PR/final report. No unexecuted check
is counted as passed.
Initial implementation [PR run 38261125135](https://github.com/Stevemeg/RepoVox/actions/runs/38261125135)
completed successfully in all four jobs: 187 container tests (34.99s), browser 1 pass
(14.6s), actual Redis/outbox/restart/revocation smoke, Python/frontend/audits/secret scan.
The duplicate push run was cancelled by workflow concurrency, not counted as a pass.

## J. Real repository results

Each source's actual pinned license text was read individually, with its checksum
retained outside Git. MIT/BSD-3-Clause permits these engineering analyses with retained
notices; this is not official corpus rights approval, redistribution or training.
The following fresh runs used the constrained Linux image with real parsers and the
production acquisition implementation, not expected/hardcoded summaries.

| Repository / full pinned SHA | License | Examined files | Parsed / eligible bytes | Symbols / edges | V / I / D / U | Valid citations | Wall seconds / parent+child peak KiB / child CPU seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pypa/sampleproject `621e4974ca25ce531773def586ba3ed8e736b3fc` | MIT | 12 | 2,133 / 2,133 | 39 / 32 | 50 / 21 / 0 / 0 | 39 / 39 | 7.3892 / 73,260+72,948 / 2.3870 |
| juliangruber/isarray `3c1b04a4a7e89791cedaecf1f1bc8d6ecd0f897b` | MIT | 21 | 1,310 / 1,310 | 73 / 70 | 78 / 65 / 0 / 0 | 73 / 73 | 7.8359 / 74,492+73,660 / 2.3890 |
| sindresorhus/ts-extras `323908522c9f90f07f99378b43891da742f2319f` | MIT | 81 | 198,042 / 198,042 | 3,079 / 3,007 | 3,586 / 2,500 / 0 / 0 | 3,079 / 3,079 | 17.5267 / 175,012+154,424 / 9.2365 |
| pallets/flask `d086db856be187255b8ec61ef409357393020f32` | BSD-3-Clause | 236 | 588,784 / 588,784 | 7,041 / 6,922 | 9,505 / 4,433 / 25 / 0 | 7,041 / 7,041 | 28.6036 / 307,052+267,128 / 18.4661 |

All have 100% eligible supported-byte coverage and zero parser errors. Parent/child RSS
are separate process peaks, not aggregate host consumption. Parallel sample timing is
an observation, not a benchmark/SLA. sampleproject has an unresolved declared CLI target
and no selected reliable entry; isarray selects declared `index.js`; ts-extras has no
entry; Flask selects the Python main guard in `src/flask/cli.py` among 71 candidates.
Flask contains HTML/Jinja examples, which are unsupported: its supported parse scope is
Python, not a claimed Python+JS result. The real-service controlled synthetic fixture
contains both Python and TypeScript. Licensed live mixed-language acquisition attempts
were rejected; no successful live mixed-supported sample is claimed.

Edge classifications respectively: 11/0/21, 5/0/65, 507/0/2,500, 2,313/176/4,433
declared/resolved-static/unresolved. These include syntax/containment/import relationships;
counts do not measure semantic correctness. No independent gold precision/recall score.

Additional inspected attempts retained defenses: expressjs/express
`a419aa7350389a275ab45fde2e849ed1f02449ef` MIT `secret_detected`; ts-pattern
`c92ca435c7e1827e0fd55c539080ef1bfd6fe3f0` MIT `secret_detected`; full-stack-fastapi-template
`7257e606cb94eada1dca40173e2b7f99dd549bc6` MIT `archive_unsafe_entry`;
flask-debugtoolbar `5751c9ddac8d9571c0bcb25ff586a9eac27af022` BSD-3-Clause
`secret_detected`. type-fest `e9f614f191aa039e4aefa2d41d62c2a3fd070cfd` first required
rights review (ambiguous metadata); after inspecting pinned `license-mit`, `archive_nested`
still rejected it. ts-reset redirected and was rejected before SHA resolution. No bypass
or extra repository download to fill corpus counts occurred. Parsing success does not
prove semantically perfect understanding.

## K. Sole-contributor audit

Before every commit the existing global Git config and `git var` author/committer are
inspected: **Stevemeg <konabharath2004@gmail.com>**. Authenticated GitHub account ID
146036166 is Stevemeg; accepted Phase 1 and published Phase 2 commit author/committer
associations match that account and email. The email endpoint was unavailable; no claim
of its verification was fabricated. Commits are unsigned, not cryptographically Verified.
All 13 existing commits and complete messages were audited; Phase 2 follow-ups are
audited before handoff. No co-author/generated-by trailers, AI/bot identities or rewritten
history. Connector PR creation returned integration 403; the owner's existing Git
credential created authorized PR #3 via GitHub REST without changing identity or logging
credentials. External human review remains outside Git and unappointed.

## L. Outstanding risks and decisions

- Owner must appoint an actual independent human reviewer different from label preparer,
  approve newly owner-authored/permitted source rights, prepare required families/gold,
  provision a protected custodian boundary and complete source reviews/adjudication/freeze.
  No budget, reviewer identity or approval is assumed. No spending occurred.
- Semantic purpose/entailment, arbitrary framework patterns, binding/dataflow/call
  resolution, unsupported languages/generated/large files and complete conflict semantics
  remain qualified omissions. The licensed live mixed-supported sample gap is disclosed.
- Conservative secret/normalization/nested-archive protections may reject legitimate
  sources; automated scanning can miss secrets. Publicity alone never supplies corpus rights.
- Kernel/container tests establish this local profile, not production containment/IAM/
  penetration testing, image security, scale or recovery promises. Custodian withdrawal
  records invalidate lineage; physical source/gold/backup deletion still requires provisioned
  storage and authorized custodian procedures. No protected dataset is currently stored.
- Independent ChatGPT technical validation and EVAL-ENTRY remain mandatory. Phase 3,
  merges, model work, infrastructure purchases/deployment and production admission remain
  unauthorized and disabled.

## M. Final status

**ENGINEERING READY — PHASE 2 BLOCKED ON EVAL-ENTRY**

Engineering tests, CI and live workflows above are observed; independent acceptance has
not been self-awarded. The official corpus remains UNFROZEN until an actual independent
human reviewer is appointed, permitted repositories are approved, required families/gold
are prepared and all reviews/adjudications/freeze prerequisites are met. PR #3 remains
unmerged. Stop here; no Phase 3, model, media, spending, deployment or merge authorization.
