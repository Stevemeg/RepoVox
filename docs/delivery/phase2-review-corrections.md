# Phase 2 independent review corrections

Date: 2026-10-12. Findings R2-01/R2-02 apply to reviewed SHA
`b35d93da16d129b079d0e1d5586135215fdbca78`.
This supersedes the evaluation-tooling readiness assertions in the
[initial verification report](phase2-verification.md), while preserving its historical
ingestion/parser/security/orchestration results. No independent acceptance is self-awarded.

## A. Repository and PR

Continue `phase2/repository-intelligence`, based on accepted Phase 1
`ec09b733ab3ceffe592ad96d07902b92596dfd1b`, retaining accepted Phase 0 ancestry.
Update [existing draft PR #3](https://github.com/Stevemeg/RepoVox/pull/3), base
`phase1/saas-foundation`. PRs #1/#2/#3 remain unmerged. Final commit SHA, CI run and clean
working-tree evidence are recorded in the PR/handoff after publication; a committed
report cannot contain its own SHA. No rewritten history or force push.

## B. Exact changed files

Implementation and contracts:

- `apps/api/repovox/evaluation/gold.py`
- `apps/api/repovox/evaluation/corpus.py`
- `apps/api/repovox/evaluation/scoring.py`
- `tools/phase2_contracts.py`
- `docs/ai/gold-evaluation.schema.json`
- `docs/ai/evaluation-corpus.schema.json`
- `docs/ai/evaluation-corpus.manifest.json`

Tests and documentation:

- `tests/unit/test_evaluation_path.py`
- `tests/unit/test_corpus.py`
- `docs/development/evaluation-gold.md`
- `docs/development/evaluation-preparation.md`
- `docs/development/testing.md`
- `docs/adr/0012-independent-gold-contract.md`
- `docs/adr/README.md`
- `docs/delivery/phase2-review-corrections.md`
- `docs/delivery/phase2-verification.md`
- `README.md`

Git diff inspection confirms no changes to ingestion/acquisition/security controls,
Tree-sitter analysis, PKM/evidence verifier, worker orchestration, API/storage/migrations,
frontend implementation, dependencies or CI permissions/workflow. Existing tests are
retained; the prior corpus engineering fixture explicitly supplies newly required fields.

## C. GitHub acquisition

The reviewed strict URL handling, connection-time IP pinning/TLS, archive resource
guards and SHA pinning are preserved. Controlled TLS/archive regressions run in the full
suite. No submitted code executes and no new source download is needed for these fixes.

## D. Source intelligence

Existing Python/JavaScript/TypeScript parsers, structural facts, qualified entrypoints
and graph remain unchanged. The new full-path evaluator test uses two owner-authorized
synthetic Python source files, manually specified expected names/ranges/attributes,
seven symbols, one main guard, five qualified edges (including one resolved import and
one unresolved call relationship). Expected facts and verdicts are authored before
actual parser/pipeline output exists. No import execution or repository test execution.

## E. R2-01: Corrected canonical gold contract

`gold-evaluation-1.0` defines all scorer inputs: repository/SHA, explicit annotation scope,
required symbols, entrypoints, edges, claims and safety observations. `Family` inherits
it and retains rights/review/family/split metadata. The corpus contract advances to
`evaluation-corpus-2.0`; the empty preparation version is `eval-v2-preparation`.
Approved corpus targets and future model/training strategy are unchanged.

Exported standalone and corpus JSON Schemas agree with Pydantic. Relational Pydantic
validation and actual file/hash/range checks complement JSON Schema's field validation.
Unknown fields/types, missing structures, duplicate annotation IDs/facts and missing
support are rejected. No absent arrays silently become empty gold. Old annotations
require explicit reauthoring/re-review; no frozen approval is automatically upgraded.

The scorer accepts validated Family/GoldEvaluation objects or their JSON-loaded
dictionaries, with the verified analysis 2.2 payload. The deterministic path proves
manual authoring -> corpus intake -> serialization -> JSON Schema validation ->
Pydantic loading -> source validation -> scoring -> aggregate/report serialization.
No undocumented fields or runtime KeyErrors are needed.

R2-02 is fixed by `source-fact-1.0`: canonical repository/SHA/path/hash/range, syntax
kind/name/language/rule/attributes and qualified edge endpoints/support. Gold/prediction
IDs, status, confidence and prose are excluded from identity. Prediction-local IDs
resolve only inside their own artifact. A separate exact assertion grammar prevents
semantic text changes from retaining a match through a reused subject ID. Unknown
semantics and ambiguous duplicate atoms remain unscored. Gold verdicts never come from
predictions. [Full semantics and formulas](../development/evaluation-gold.md).

## F. Orchestration and phase boundary

No durable-job or database changes. Regression tests retain atomic fenced publication,
owner-scoped private artifacts, retries/resume, worker death, cancellation/deadlines,
outbox delivery and the Stage 9 `phase2_pipeline_boundary`. Normal generation remains
disabled; no completed video, model work or Phase 3.

## G. EVAL-ENTRY

Actual official manifest: **UNFROZEN**, reviewer **PENDING OWNER APPOINTMENT**.
Candidates/approved families 0/0, EVAL_DEV/EVAL_TEST 0/0, hidden families 0,
approved adversarial variants 0, reviewed gold claims/edges 0/0.

The test annotations are labelled TOOLING_FIXTURE with pending rights, no reviewer,
no gold review and no approval. They are not admitted official corpus labels. No hidden
fixtures or fabricated appointments are created. Existing protected held-out/training/
calibration access rules remain tested. Freeze also rejects partial annotation scope.

Missing owner actions remain: appoint an actual independent human reviewer different
from preparer; approve actual repository rights/provenance and protected custodian access;
prepare the required source/gold/family/adversarial counts; complete independent source
reviews/adjudication and freeze the split/access/contamination/deletion lineage.

## H. R2-02 negative and metric evidence

Full-path fixture: **12 gold / 12 predictions / 12 matches**, 100% matching on both sides,
no unmatched/unscored claims, 11 verified expected facts and one inferred edge,
zero false verification. Symbol, graph/import and entry precision/recall are 1.0;
seven of seven original citations resolve. Gold and prediction IDs differ for every pair.
Renaming prediction IDs with valid ledger associations leaves metrics unchanged.

A manually authored absent `ghost()` hard negative raises the fixture to 13 gold and
13 predictions. A deliberately false verified prediction produces one false verification,
reviewed verified precision 11/12, unsupported rejection 0/1 and REJECTED. The same
test prediction labelled unsupported produces zero false verification and rejection
1/1; independent expected unsupported remains fixed in both cases.

Partial gold (one annotation against twelve predictions) reports 1/12 prediction pairing,
eleven unscored predictions and INCOMPLETE, even if completeness is self-reported.
Zero-match semantic mutations report zero coverage, undefined reviewed precision and
INCOMPLETE. Missing predicted facts, same-ID/different facts and distinct-ID duplicate
atoms cannot be hidden by successful-looking aggregates.

Mandatory negatives cover absent symbols/entrypoints, wrong/unknown claim identifiers,
duplicate IDs, missing/forged evidence, changed source/hash/SHA/ranges, unmatched
predictions/gold, partial/empty gold, malformed types/fields and ambiguous facts.
No annotations are reverse-engineered from predictions. The independent evaluator
imports no analyzer/verifier implementation. Citation presence is not entailment.

Reports include both counts/coverage ratios, matched/unmatched ID lists, correctness,
false verification and denominator, unsupported rejection denominator/recall, reviewed
verified precision/recall and all unscored predictions requiring human review. Zero
denominators are null. At least one pair and 100% pairing on both sides are required;
source problems/partial scope are INCOMPLETE. Complete pairing can only be
REVIEW_REQUIRED or REJECTED, never acceptance PASS. Aggregates propagate incompleteness.

## I. Exact regression verification

Environment: Windows PowerShell/Python 3.12.0/Node 24.18.0; constrained Linux/WSL
containers, Python 3.12.12, real PostgreSQL 16.13/Redis 7.4.9/private SeaweedFS 4.17.
Own disposable project uses ignored API-port override 8001; unrelated port 8000 is untouched.

| Command | Actual local result |
| --- | --- |
| `uv run ruff check apps/api tests tools/phase1*.py tools/phase2*.py` | Pass |
| `uv run ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py` | Pass, 64 files |
| `uv run mypy` | Pass, 41 source files |
| `uv run pytest tests/unit/test_evaluation_path.py tests/unit/test_corpus.py -q --tb=short` | 47 passed, 3.20s |
| `uv run pytest tests/unit -q` | 193 passed, 20.11s |
| `docker compose -p repovox-test -f docker-compose.yml -f .artifacts/phase2-ports.yml run --rm --build tests` | 218 passed, 56.30s; own worker/dispatcher stopped before suite |
| `uv run python tools/check_docs.py` | Pass: 31 required paths, 44 Markdown files, 316 links, 10 JSON files |
| `uv run python tools/cost_model.py --check` | Pass |
| `uv run python -m unittest discover -s tools -p 'test_*.py' -v` | 32 passed |
| `uv run python tools/phase1_contracts.py --check` | Pass |
| `uv run python tools/phase2_contracts.py --check` | Pass, including standalone gold/corpus export |
| `uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json` | Actual zero official counts, UNFROZEN |
| Same corpus command with `--action freeze` | BLOCKED, expected exit 2 |
| `uv run pip-audit --local` | No known vulnerabilities; local RepoVox package has no PyPI audit entry |
| `npm --prefix apps/web run lint`, `run typecheck`, `test`, `run build` | Pass; 17 tests |
| `npm --prefix apps/web audit --audit-level=high` | 0 vulnerabilities |
| `uv run python tools/phase1_runtime.py` | Redis interruption/outbox delivery/restart/terminal immutability/revocation pass |
| `npm --prefix apps/web run test:e2e` | 1 passed, 16.9s |
| `git diff --check` and staged equivalent | Pass before publication |

Runtime uses COMPOSE_PROJECT_NAME=repovox-test, COMPOSE_FILE with ignored port override
and REPOVOX_RUNTIME_API_URL=http://localhost:8001. Gitleaks 8.30.0 staged scan found no
leaks. The full-history scan and final GitHub Actions results are checked before handoff
and linked in PR #3.
Mermaid CLI 11.15.0 rerendered all five README architecture/data/Director charts using
system Chrome; generated SVGs remain outside Git. No visual/media execution claim.

During implementation, the full-path test exposed an incorrect multiple-inheritance
configuration on the prediction projection (extra fields rejected). It was repaired by
explicit projection config; the complete serialization/scoring path now passes. Initial
lint/type issues were repaired. Existing deprecation warnings for the native parser
timeout API, Starlette/httpx and Alembic remain disclosed, not suppressed. No existing
regression test was removed or weakened.

## J. Source scope and limitations

No additional public live acquisition was run: the ingestion/parsing implementation is
unchanged, and its prior licensed results remain historical evidence. This correction's
full path runs the real parsers and verifier on newly authored synthetic engineering
source, not hardcoded prediction summaries. No official independent benchmark results.

Same-line identical source identities may require a richer future contract. The exact
assertion adapter intentionally abstains on broader semantic claims. Partial pairing
cannot support acceptance even if conditional reviewed precision is numerically high.
Actual human provenance and semantic label quality still need independent review.

## K. Git attribution

Before every commit inspect existing author/committer configuration and both Git idents.
Authenticated GitHub account and accepted commit association are Stevemeg, with unchanged
`Stevemeg <konabharath2004@gmail.com>`. Audit all existing/full messages and correction
commits at handoff. No AI/bot identities or co-author/generated-by trailers, unsigned
commits are not described as signed, and no history/attribution is rewritten.

## L. Outstanding decisions

Only owner-approved real source preparation, rights, independent-human appointment,
review/adjudication, protected corpus provisioning and freeze can satisfy EVAL-ENTRY.
No rights, reviewer, hidden fixture, approval or corpus completion count is fabricated.
No spending, deployment, merges, models/training/benchmarks or Phase 3 was initiated.

## M. Re-review status

R2-01/R2-02 engineering corrections are implemented and locally verified. Final CI and
attribution are checked before handoff, without self-awarding independent acceptance.
With those checks green: **ENGINEERING READY — PHASE 2 BLOCKED ON EVAL-ENTRY**.
Stop at updated unmerged PR #3 for independent re-review.
