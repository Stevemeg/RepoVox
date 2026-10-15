# Phase 2C-D implementation verification

Date: 2026-10-15. Implementation-assistant evidence; independent review pending.

## Baseline and boundaries

Verified the remote baseline at `9557938f69f0c71f124abe4633089e531e753693` using
`git ls-remote origin` and the GitHub commit/PR/workflow APIs. The local working
tree already had the requested v2 branch at that commit plus uncommitted v2 work;
that work was preserved, inspected, corrected and verified in this session.
PR #6 was draft, based on `phase2/ai-audited-pilot`; its accepted CI run
[38548459461](https://github.com/Stevemeg/RepoVox/actions/runs/38548459461) succeeded.
Continued `phase2/source-fact-v2-evaluation` from that exact commit. No prior PR was changed.

The work supports F-02/F-03 and evidence trust through additive offline evaluation.
No historical source/reference/prediction/capture/comparison volume was opened,
rewritten or rescored. No source acquisition, new blind pilot, model, deployment,
paid service or production database operation occurred. Official EVAL-ENTRY remains
UNFROZEN with unchanged human-reviewed counts. Historical 0/84 remains an exact
interoperability result, not a semantic accuracy estimate.

## Design and implementation

The [normative specification](../development/evaluation-v2.md) documents independent
reference/expected-status semantics, exact identities, projection, metrics and
completeness. [ADR-0016](../adr/0016-independent-source-fact-v2-evaluation.md) records
the additive version boundary and shared-code independence analysis.

New modules separate reference/source validation (`v2.py`), comparison/aggregation
(`scoring_v2.py`), prediction-only ledger binding (`projection_v2.py`) and custody/
future chronology (`custody_v2.py`). Schemas, a source-only validation CLI, schema
checks and a disposable OS access-denial probe accompany the implementation.

The production ledger has no explicit canonical fact key. The new adapter checks
the sealed declared subject and exact static assertion grammar before copying an
existing status. It does not invoke production parsing/verifying or author gold.
Entrypoint facts lack ledger verdicts and remain unreviewed. Runtime prose cannot
inherit a syntax verdict. Original analysis bytes are required to reproduce a real
projection. No production schema or normal application stage is modified.

Only complete identities form scoring pairs. A diagnostic index can show unique
single-field classification/category/target differences, never count them as pairs.
Source checks gate comparison; hash-valid citations are not semantic entailment.
Unknowns and unprojected claims remain explicit. Reports recompute their rows,
counts, ratios and completeness; aggregate inputs are version/hash checked and
micro-counted, retaining incomplete families and rejecting duplicates/tenant mixing.

Private storage reuses the accepted DAC boundary check. Files are exclusive,
content-addressed and 0600; session sequence reservations reject replay. Events bind
scope, retained payload, predecessor, frozen engineering/scorer commits and actual
local UTC time. Real original capture bytes and source-only attestation are required.
Pre-reveal validation checks original sources before prediction parsing. These are
owner-attested local records, not provider signatures or administrator-proof WORM.

## Synthetic matrix and verification

The new evaluation fixtures are manually specified from synthetic Python, TypeScript
and JSON source,
independent of production extraction. Separate projection tests use synthetic real
analysis only as predictions. They do not reuse historical pilot names, IDs or answers.
Coverage includes identity equivalence/non-equivalence; imports/members/aliases;
byte/hash/commit/dispatch/support distinctions; wrong graph targets and types;
entrypoint category/target differences; inferred/documentation/unsupported/unknown
verdicts; partial/complete/empty references; source/capture/packet tampering;
revision lineage; micro-aggregation; duplicate/mixed-version/tenant rejection;
runtime assertion exclusion; private permissions; immutable reports and chronology.

Actual final-head CI is linked in the draft PR, not inferred from the accepted baseline.

The [adversarial matrix](../development/evaluation-v2-test-matrix.md) maps all 32
requested categories to the 97 new collected test cases. Fixtures include expected
rejections with explicit error checks and known-positive controls. They are never
independent gold. Observed local evidence was recorded on 2026-10-15 UTC; the
prepublication ledger was inspected at 06:33:19 UTC.

| Exact command | Actual local result |
| --- | --- |
| `uv run ruff check apps/api tests tools/phase1*.py tools/phase2*.py` | Passed |
| `uv run ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py` | 92 files already formatted |
| `uv run mypy` | Passed, 52 source files |
| `uv run pytest tests/unit -q` | 423 passed, 36 POSIX-only skips, 29.75 seconds |
| `uv run python tools/phase1_contracts.py --check` | Public OpenAPI unchanged and checked |
| `uv run python tools/phase2_contracts.py --check` | Existing analysis/evaluation contracts checked |
| `uv run python tools/phase2_v2_contracts.py --check` | All seven v2 schema exports checked |
| `uv run python tools/check_docs.py` | 71 Markdown files, 461 local links/anchors; contract/phase/identity checks passed |
| `uv run python tools/cost_model.py --check` | Passed; no cost assumptions or spending changed |
| `uv run python -m unittest discover -s tools -p 'test_*.py' -v` | 32 passed, 0.851 seconds |
| `uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json` | UNFROZEN; zero approved families/gold; reviewer pending |
| `uv run python tools/phase2_preparation.py --catalog docs/ai/evaluation-candidates.json --manifest docs/ai/evaluation-corpus.manifest.json --output docs/ai/evaluation-readiness.json --check` | Existing readiness bytes match; official gates remain unmet |
| `uv run pip-audit --local` | No known dependency vulnerabilities; local RepoVox package is not on PyPI and is not audited |
| `git diff --cached --check` | Passed |

Disposable Linux service commands use the existing isolated test project only:

```powershell
docker desktop start
docker compose -p repovox-test -f docker-compose.yml -f .artifacts/phase2-ports.yml stop api worker dispatcher
docker compose -p repovox-test -f docker-compose.yml -f .artifacts/phase2-ports.yml up -d --build postgres redis storage storage-init migrate
docker compose -p repovox-test -f docker-compose.yml -f .artifacts/phase2-ports.yml run --rm --no-deps --build tests
docker compose -p repovox-test -f docker-compose.yml -f .artifacts/phase2-ports.yml run --rm --no-deps --user 0 --cap-add SETUID --cap-add SETGID --cap-add CHOWN tests python tools/phase2_storage_probe.py
docker compose -p repovox-test -f docker-compose.yml -f .artifacts/phase2-ports.yml run --rm --no-deps --user 0 --cap-add SETUID --cap-add SETGID --cap-add CHOWN tests python tools/phase2_v2_storage_probe.py
```

Both probes returned `worker_read: OS_DENIED`, directory mode `0o700`, file mode
`0o600`, custodian UID 10002 and worker UID 10001. Neither stores official evidence.
No new migration was authored; existing additive migration regressions run only
against disposable synthetic databases. CI repeats fresh migration, integration,
runtime/browser regressions, frontend tests/build/audit and secret scanning.
Frontend source is unchanged; final-head CI supplies its regression evidence.

Final-code Linux run: **485 passed, 2 Windows-only skips in 122.20 seconds**,
including all 28 integration tests and all POSIX custody tests. The additional
Windows-only v2 fail-closed test explains the second Linux skip relative to the
accepted baseline. Skipped tests are never reported as passing. Earlier developing
Linux runs passed 474 and 482 tests, each with two skips, before the last controls
were added; the 485-test run supersedes them.

All five existing Mermaid diagrams rendered with
`npx.cmd --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig`
and the README's three input/output pairs (`docs/architecture/overview.md`,
`docs/architecture/data-model.md`, `docs/ai/director-architecture.md`). Chrome
configuration and rendered SVGs remain under the operating-system temporary
directory, outside Git.

At 06:32 UTC, Gitleaks v8.30.0 scanned an export of the intended Git index
(2.17 MB) and all 24 existing commits (2.30 MB): zero leaks. Commands:
`git checkout-index --all --prefix=$scanPrefix`,
`docker run --rm -v "${scanRoot}:/scan:ro" zricethezav/gitleaks:v8.30.0 dir /scan --redact --exit-code 1`,
and `docker run --rm -v "${PWD}:/repo:ro" zricethezav/gitleaks:v8.30.0 git /repo --redact --exit-code 1`.
Only tracked public inputs were exported; no private custodian directory was read.

## Development failures and corrections

The initial focused run failed three cases because a synthetic entrypoint cited a
main guard missing from its source fixture; the original source was corrected.
Ruff initially identified two overlong lines and formatting/import-order issues;
all were corrected. Adding ledger-count validation correctly rejected a test that
changed a verdict without updating its histogram; the positive fixture now changes
both, with a separate negative histogram test. These failures are not passing checks.

Implementation inspection also corrected dropped reference observations, explicit
version enforcement, unknown-gold false-verification denominators, source read bounds,
correction approval/context, duplicate semantic subjects, mixed ledger metadata,
and frozen-engineering/reveal-reservation rechecks. Regression tests cover these.
GitHub CLI was unavailable; the GitHub connector and public read-only API supplied
repository evidence. Docker initially had no running daemon; its supported CLI
started it before Linux checks. A combined PowerShell API/Desktop-launch command
was rejected by automatic policy review; the separate read-only API request and
supported `docker desktop start` command succeeded. No blocked action is pending.

## Attribution, compatibility and rollback

The complete existing history has one author and committer identity:
`Stevemeg <konabharath2004@gmail.com>`. Full messages contain no AI co-author,
Generated-by or bot trailers. GitHub's accepted-commit API associates both author
and committer with account `Stevemeg`; the commit is unsigned, not cryptographically
Verified. Identity configuration and effective identities are inspected again
immediately before each new commit. CI has read-only repository permission and
does not create commits.

The staged diff leaves production analysis code, 2.2/2.3 schemas, migrations,
v1 gold/scoring/exploratory/corpus/preparation modules, official manifest/readiness,
dependency locks and frontend source unchanged. Historical private packets were
not accessed. Existing v1/legacy tests run in both complete suites. Rollback stops
the offline v2 tooling; no application deployment or database rollback is needed.

Development corrections are recorded before handoff. Existing tree-sitter, Starlette
and Alembic deprecation warnings remain visible; no dependency upgrades or warning
suppression is part of this phase.

## Limitations and next verification

Semantic entailment, authenticity of owner/reviewer attestations and prior rights/
snapshot evidence remain independent responsibilities. No cryptographic provider
authentication is claimed. Complete refers only to explicitly declared scope.
Entrypoint verdict gaps intentionally prevent complete formal acceptance for current
production predictions containing those facts. Exact differences may remain unpaired.
Runtime and prose observations require separate source review. No statistically
representative sample, real-world accuracy, annotation throughput or human labor
measurement exists from this engineering test run. No spending was initiated.

Review [the handoff](phase2c-d-reviewer-handoff.md), exact public diff and final-head
CI. Independent evaluator acceptance and separate owner pilot authorization are
required before future data acquisition, prediction generation or blind review.
