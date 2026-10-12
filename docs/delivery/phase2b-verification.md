# Phase 2B verification and EVAL-ENTRY handoff

Version `phase2b-handoff-1.0`, 2026-10-12. Implementation assistant report, not independent
approval. [Decision register](phase2b-decisions.md) · [Readiness](../ai/evaluation-readiness.json).

## A. Repository

`phase2/eval-entry` branches from exact independently accepted Phase 2 engineering
SHA `b60ba5484a0710caf64c310e910110d625a01768`. PR #3 was fetched and confirmed
open/draft/unmerged with that exact HEAD and base `phase1/saas-foundation`.
The new PR targets `phase2/repository-intelligence`; no prior PR is modified or merged.
Final branch SHA and PR link are reported in the PR/final handoff after commit; a commit
cannot embed its own hash. No force push or history rewriting.

## B. Corpus tooling

Separate strict candidate/preparation/receipt contracts preserve gold 1.0, corpus 2.0
and source-fact 1.0. Individually selected metadata/license hashing, blank protected
review worksheets, source fingerprints/grouping suggestions, complete digest-sealed
receipts, materialized variant inventory checks, hidden authorship evidence, actual
POSIX boundary checks, readiness and dry-run verification are implemented. Freeze
requires these supplements plus every accepted threshold/source/provenance gate.
Declared counts exclude self/unappointed/partial/unclear records. Metadata-only counts
are visibly unverified. No approval generator or analyzer-backed gold exists.
Accepted ingestion, parser, PKM, evidence verifier, orchestration, API, migrations,
frontend and dependency locks are unchanged. Corpus admission changes are justified
by preventing edited/partial labels, unsupported flags and unreviewed variants from
being counted. ADR-0013 explains the additive freeze prerequisite and rollback:
discard draft preparation packets/branch; no application/database migration required.
Removing the supplement must not confer official eligibility on unreviewed records.

## C. Candidate sources

[Seven real candidates](../ai/evaluation-candidates.json), individually pinned with
inspected root license hashes: two owner-account repositories, Click, is, p-limit,
Datasette and JupyterLite. Preliminary slices: two Python, two JS/TS, three mixed.
Zero rights-reviewed/owner-approved sources. No archives acquired. Scope/ancestry,
notices/retention/reviewer access and exact source classification remain pending.
Original license text stays outside Git; public catalog contains metadata/hashes only.

## D. Gold workflow

[Handbook](../development/evaluation-authoring.md),
[checklist](../development/evaluation-review-checklist.md), immutable review receipt,
complete claim/edge coverage and annotation digest bind source/SHA/status/rights/split/
variants. Independent humans author/review semantic expectations; scorer is unchanged.
Source existence/range/hash checks cannot prove entailment or authenticate a human.
Corrections require re-review; worksheet decisions/identities start null.

## E. Independent human review

**PENDING OWNER APPOINTMENT.** [Appointment packet](../development/evaluation-reviewer-packet.md)
covers skills, independence/conflicts, confidentiality, process, workload and recorded
adjudication/approval. No reviewer, signature, human-reviewed label or completion date
is invented. ChatGPT remains technical validator, not an independent human rater.

## F. Adversarial corpus

[Versioned plan](../development/evaluation-adversarial-plan.md): 100 planned slots on
twenty pending parent slots, five per parent, twenty threat categories. **Zero official
materialized or approved variants.** Synthetic security/workflow fixtures do not count.

## G. Protected storage

Official custodian/storage/rights access is unapproved and unprovisioned. The Linux
probe demonstrates disposable synthetic 0700/0600 protection across separate Unix
identities and OS-denied worker reads. It cannot prove official provisioning, mounts,
reviewer access, immutable backups/restore or hidden final-run registration. Windows
ACL equivalence remains fail-closed. [Storage guide](../development/evaluation-storage.md)
states physical evidence and remaining duties; no hidden source/gold is public.

## H. Evaluation readiness

Seven candidates; zero verified rights-approved families; DEV 0/20, TEST 0/60;
held-out Python 0/20, JS/TS 0/20, mixed 0/20; genuinely new owner hidden 0/10;
approved variants 0/100 on 0/20 held-out parents; reviewed claims 0/600; supported
reviewed edges 0/120. Appointment pending; no official annotations, rights clearance,
protected storage or contamination review. Freeze eligibility false; official corpus
**UNFROZEN**. Preparation is reviewable engineering, not independent approval.

## I. Costs

Actual cash spend $0. No paid services. [Effort log](../ai/evaluation-effort.json) keeps
human preparation/license/annotation/review/adjudication hours null because no measured
time sheets exist. No pilot throughput or remaining-hour forecast is fabricated.
Batch C must measure actual work before scaling or approving budget. Automated test
wall time is not human labor.

## J. Testing and CI

Synthetic algorithm freeze uses a separately named full-sized test corpus, simulated evidence
and explicit synthetic identities; it confers no official approval. Linux-only storage
checks run in the real-service suite; host Windows skips are disclosed. CI adds the
new branch/stacked target and readiness command while retaining all existing jobs and
read-only permissions. No bot commits or paid workloads.

| Exact command | Observed result |
| --- | --- |
| `uv run ruff check apps/api tests tools/phase1*.py tools/phase2*.py` | Passed |
| `uv run ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py` | 69 files formatted |
| `uv run mypy` | Passed, 42 source files |
| `uv run pytest tests/unit -q` | 210 passed / 22 POSIX skips before the final additional duplicate-edge case; final case included in Linux and CI |
| `uv run pytest tests/unit/test_preparation.py -q` | Final Windows preparation run: 17 passed / 23 POSIX skips |
| `docker compose -p repovox-test stop worker dispatcher` | Stopped exclusive consumers before destructive disposable tests |
| `docker compose -p repovox-test up -d --build postgres redis storage storage-init migrate` | Actual services/migration succeeded |
| `docker compose -p repovox-test run --rm --build tests` | Full Linux suite: 257 passed / 1 Windows-specific skip; real PostgreSQL/Redis/S3 and actual parsers |
| `docker compose -p repovox-test run --rm --no-deps tests pytest tests/unit/test_preparation.py -q` | Final: 39 passed / 1 Windows-specific skip; includes CLI worksheet/freeze/report consistency |
| `docker compose -p repovox-test run --rm --no-deps --user 0 --cap-add SETUID --cap-add SETGID --cap-add CHOWN tests python tools/phase2_storage_probe.py` | OS_DENIED for worker UID 10001; custodian UID 10002; actual 0700/0600 |
| `docker inspect repovox-test-worker-1 --format '{{.Config.User}} {{json .Mounts}}'` and equivalent API command | Both user `repovox`, empty volume mounts; no official custodian exists/mount supplied |
| `uv run python tools/check_docs.py` | Paths/Markdown/JSON/contracts/IDs/Git audit passed |
| `uv run python tools/cost_model.py --check` | Accepted hypothesis arithmetic passed; no measured effort implied |
| `uv run python -m unittest discover -s tools -p 'test_*.py' -v` | 32 passed |
| `uv run python tools/phase1_contracts.py --check` | OpenAPI unchanged and passed |
| `uv run python tools/phase2_contracts.py --check` | Existing and supplemental schemas passed; accepted schema bytes unchanged |
| `uv run python tools/phase2_preparation.py --catalog docs/ai/evaluation-candidates.json --manifest docs/ai/evaluation-corpus.manifest.json --output docs/ai/evaluation-readiness.json --check` | Aggregate matches tracked readiness; official counts zero |
| `uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json --action freeze` | Expected process exit 2 / BLOCKED; manifest remains UNFROZEN |
| `uv run pip-audit --local` | No known vulnerabilities; local repovox package absent on PyPI and unauditable there |
| `npm --prefix apps/web ci`, `run lint`, `run typecheck`, `test`, `run build`, `audit --audit-level=high` | Passed; 17 tests, successful build, zero audit vulnerabilities |
| `npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i INPUT -o EXTERNAL_OUTPUT` | README's overview/data-model/Director inputs rendered all five SVGs outside Git; Chrome config outside Git |
| `docker run --rm -v "${PWD}:/repo" zricethezav/gitleaks:v8.30.0 git /repo --staged --redact --exit-code 1` | No staged leaks |
| Same scanner with `--log-opts=--all` instead of `--staged` | No leaks in all 18 inherited commits |
| `git diff --check` and `git diff --cached --check` | Passed |

Initial failures are disclosed: GitHub CLI `gh` was unavailable (used connected GitHub
tools and public REST instead); Docker was initially stopped (started installed Desktop);
new lint/type errors were corrected; two forged-range tests initially expected a source
error while the stricter relational citation guard rejected them earlier (corrected test
inputs, safeguards retained). The first DAC probe's root parent was denied traversal
under dropped capabilities; corrected it to obtain only metadata from the custodian
child and restore disposable directory ownership for cleanup, without granting worker
access. Corrected reruns passed. Existing Starlette/Tree-sitter/Alembic deprecations
remain warnings; no integration service failure is hidden as a successful skip.

CI conclusions on the final remote SHA are inspected in the PR handoff. No green result
from an earlier SHA is substituted for the final revision.

## K. Sole-contributor audit

Existing authentic global Git author/committer: Stevemeg; email configuration unchanged.
Before every commit inspect config origins and both Git identities, and confirm actual
GitHub author/committer association with Stevemeg. Inspect complete messages/history
for AI/bot/unexpected trailers. Cryptographic signatures and account association are
different; unsigned commits are not described as signed. Synthetic test identities
are algorithm test data, not personnel/approvals or Git contributors.

## L. Unresolved owner actions

D2B-01 actual human appointment; D2B-02 scoped source rights/owner decisions;
D2B-03 genuine new hidden authorship/provenance; D2B-04 specific custodian/isolation;
D2B-05 measured annotation/review budget; D2B-06 retention/access/withdrawal/backup
authorization. No additional source acquisition, official annotations/review/freeze
can proceed merely because schemas/tests are green.

## M. Final status

**PREPARATION COMPLETE — HUMAN/RIGHTS APPROVAL BLOCKED** after technical verification.
Official corpus remains UNFROZEN. No independent PASS, benchmark, model/training,
paid infrastructure, merge, production-readiness claim or Phase 3.
