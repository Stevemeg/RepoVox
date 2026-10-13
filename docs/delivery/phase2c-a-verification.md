# Phase 2C-A exploratory preparation verification

2026-10-13. Technical preparation only; independent AI source review is pending.
Status: **READY FOR BLIND INDEPENDENT AI REVIEW**. Stop before comparison or reveal.
See [source-only handoff](../development/exploratory-handoff.md),
[machine-readable readiness](../ai/exploratory-readiness.json),
[ADR-0014](../adr/0014-ai-audited-exploratory-track.md) and
[official owner decisions](phase2b-decisions.md).

## A. Repository and PR

Accepted base `e87a95c4763331e3cb73211eb02f7acbc738941a`, branch
`phase2/ai-audited-pilot`, stacked target `phase2/eval-entry`. PRs #1–#4 were fetched
and remain open/unmerged. No merges, history rewriting, force push or deployment.
Final commit/PR/CI are recorded in the handoff and GitHub checks, not self-certified.
No database migration, dependency, frontend or model change.

## B. Policy and engineering

`AI_AUDITED_EXPLORATORY` has strict non-human/non-official/no-training policy literals.
Official corpus/candidates/readiness and accepted gold/scoring contracts keep their
accepted content; official corpus is UNFROZEN with zero approved entries or gold.
New code produces source-only packets, exclusive seals, original Git-tree checks,
raw-response capture checks, correction lineage, scoped predictions and accepted
source-fact scoring. Capture hashes do not authenticate reviewer identity; genuine
owner-inspected ChatGPT conversation evidence remains mandatory. No real reference,
gold labels, model inference or evaluation scores were generated.

The sole accepted analysis change is a six-line default-identity preparation hook.
Click's full source parse failed at the unchanged Stage 4 fact limit. The explicit
offline exploratory runner restricts eligible/context files **after** full original
Stage 3 screening; original paths/hashes remain inventoried. Normal API/worker
analysis stays full scope. Parser sandbox, byte/fact/time limits, pinned HTTPS,
archive safety, RLS, immutable S3 artifacts, fencing and Stage 9 boundary remain.

## C. Rights and source approvals

Owner approved Click/p-limit conditionally on rights screening, explicitly excluded
ai-job-agent and separately approved pinned echo-kernel as the replacement before
archive acquisition. No third-party job descriptions were admitted, archived or
submitted to static analysis. Sole repository ownership was not used as permission
for those materials.

Pinned full SHAs, original-license hashes, rights-decision hashes, file inventory,
actual notice findings and scope live in the private volume's per-family preflight
and rights files. Three permitted internal exploratory decisions were recorded by
the implementation assistant, not invented independent human approvals.

| Repository | License evidence SHA256 | File-level findings and obligations |
| --- | --- | --- |
| Click | `9a8ad106a394e853bfe21f42f4e72d592819a22805d991b5f3275029292b658d` | BSD-3-Clause Pallets notice; parser.py incorporates optparse with Gregory P. Ward/PSF notices. PSF license chain retained alongside the archive. 155 initial textual files plus 21 remaining textual files and 2 binary JPEG examples inspected/screened; images excluded from review. |
| p-limit | `5c932d88256b4ab958f64a856fa48e8bd1f55bc1d96b8149c65689e0c61789d3` | MIT Sindre Sorhus notice retained; all 16 tree files checked, including dotfiles; .npmrc excluded by existing filtering. No vendored dependency source identified. |
| echo-kernel | `6662bee895c042d198c56cbdee170f6d1c127cec45985b83eb25d2c19c9ea25d` | BSD-3-Clause JupyterLite notice and TS headers; Python metadata references LICENSE. All 25 pinned files checked. Copier ancestry jupyterlab/extension-template v4.3.8 (BSD-3-Clause) recorded, not represented as unrelated ancestry. |

No contrary file permissions, installed dependency source or retention maximum were
identified within inspected scope. Retain complete copyright/conditions/disclaimers
with review copies; no endorsement or public archive publishing. Root license markers
alone did not grant admission. [Pinned source links and scope](../development/exploratory-handoff.md#source-scope-and-pinned-access).
This documents permissible-use screening for the authorized internal activity, not
a professional legal certification or permission for different future uses.

## D. Actual analysis and workload

All three final jobs actually executed durable Stages 1–9, real Linux parsers, graph,
PKM, evidence catalog and verification. Stage 9 completion intentionally ends with
`phase2_pipeline_boundary`; later model/media stages remain disabled. Every acquired
file was checked against the exact Git tree blob SHA, not only codeload URL or GitHub
language metadata. RLS query under a different owner returned zero analysis rows.

| Family | Whole eligible files / bytes | Selected parsed source files / bytes | Selected parse errors | Durable job seconds |
| --- | --- | --- | --- | --- |
| Click | 91 / 1,003,633 | 3 / 21,069 | 0 | 14.362808 |
| p-limit | 6 / 35,785 | 2 / 8,513 | 0 | 2.828136 |
| echo-kernel | 5 / 5,561 | 4 / 5,540 | 0 | 2.714060 |

Each selected source scope parsed 100% of its bytes. This is not whole-repository
parser coverage. Six selected configuration/documentation files supply context, not
eligible parser bytes. Fifteen source/context excerpts have zero detected redactions.
echo-kernel is genuinely mixed in the eligible manifest: 2 Python, 2 TS, 1 JS. Its
Python is limited packaging glue; the JS style import is outside final selected scope.
Proposal screening parsed all 5 individual pinned source blobs before owner approval,
without archive acquisition/admission. Approved pilot acquisition then used codeload
and the complete durable engine, separately from that screening.

PKM/symbol/edge/verdict/citation metrics and stage CPU/RSS measurements remain inside
sealed B to protect blindness. CPU/RSS observations are process measurements, not
hardware-normalized performance results. Click export resumed its completed durable
job; preserved stage usage is the time evidence, not the later export process's CPU.
Actual cash spending is **$0**; no paid service was provisioned. Human rights,
annotation/review/adjudication hours were not measured and remain null, not inferred
from automated run duration. No measured review throughput exists, so a defensible
80-family labor/cost projection is unavailable. Existing Phase 0 estimates remain
unmeasured hypotheses. This sample has no statistical representativeness claim.

## E–F. Blind A and sealed B

Private root: Docker volume `repovox-ai-audited-pilot-v1`,
`/exploratory/AI_AUDITED_EXPLORATORY/v1/<repository-with-hyphen>/`.
`handoff-seals.json` references immutable `sealed/package-a-<hash>.json` and
`sealed/package-b-<hash>.json`; [readiness](../ai/exploratory-readiness.json) records
opaque digests. B was sealed before A: Click 06:07:47 UTC, p-limit 06:08:13 UTC,
echo-kernel 06:09:36 UTC on 2026-10-13. Events have the actual local timestamps and
hashes, not fabricated reviewer completion times. All original seal hashes rechecked
unchanged after preparation. No protected source or predicted answers enter Git.

`phase2_exploratory_handoff.py` exports A, excerpts, pinned links, complete notices,
reference contracts and opaque B commitments only. The owner-readable ZIP is outside
Git under local `%TEMP%/repovox-ai-audited-review/`, with an export manifest. Its hash
and exact path appear in the final handoff. Predictions and generated answer keys are
excluded. No AI reference is supplied in the ZIP. The export does not re-seal B.
Final `blind-review-v2.zip` SHA256: `535fddb1acd1b80c471fc282d5484d958df703b8972db682a9310eac3907eea1`;
94,940 bytes, 33 entries, every manifest hash and all three A schemas checked.
Earlier v1 export remains preserved; v2 clarifies that the raw response checksum is
computed after capture, not invented by ChatGPT. A/B bytes and their seals are unchanged.
Windows export ACL permits the current owner, SYSTEM and Administrators; it is outside
OneDrive/Git. The ZIP retains the handoff text and contracts at export time.

## G. Demonstrated local isolation and limits

Actual exploratory files use custodian UID/GID 10002, directory 0700/file 0600.
An offline process with real application image UID/GID 10001 and a read-only mount
attempted four reads of real A/B/source/rights files: all raised OS PermissionError.
The custodian read and hash-checked actual packets. Normal API/worker containers have
no exploratory mount. Docker projects/volumes separate disposable regressions from
pilot DB/S3. No gold, hidden data or EVAL_TEST material was acquired or mounted.
Source parser access is limited to assigned source and trusted runtime; credentials
are omitted from its environment. No submitted code/dependency execution occurred.

This is local exploratory protection, not an official custodian approval, production
security proof, WORM archive or backup/restore test. Host/root remains trusted; hashes
detect changes but do not prevent privileged changes. No backups were made. Withdrawal
must invalidate dependent versions/reports and delete actual source/S3/Windows export
copies; minimal suppression lineage prevents restoration of withdrawn content.

## H. Verification commands and corrections

Executed checks:

```text
uv run ruff check apps/api tests tools/phase1*.py tools/phase2*.py
uv run ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py
uv run mypy
uv run pytest tests/unit -q
uv run python tools/check_docs.py
uv run python tools/cost_model.py --check
uv run python -m unittest discover -s tools -p 'test_*.py' -q
uv run python tools/phase1_contracts.py --check
uv run python tools/phase2_contracts.py --check
uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json
uv run python tools/phase2_preparation.py --catalog docs/ai/evaluation-candidates.json --manifest docs/ai/evaluation-corpus.manifest.json --output docs/ai/evaluation-readiness.json --check
uv run pip-audit --local
npm --prefix apps/web run lint
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/web audit --audit-level=high
docker compose -p repovox-test run --rm --build tests
npm --prefix apps/web run test:e2e
git diff --check
```

Initial Windows unit run: 231 passed/23 POSIX-specific skips. Linux full service run:
278 passed/1 Windows-specific skip, with real PostgreSQL/Redis/S3. Frontend: 17 tests,
lint/types/build and npm audit passed. Python audit found no known vulnerabilities;
local unpublished repovox package is not auditable on PyPI. Documentation estimate
suite: 32 tests passed. Final branch CI and browser/secret results are linked from the
handoff/PR; no live upstream source is sent through public CI. Regression evidence is
synthetic and separate from real pilot evidence.
Final focused exploratory suite: 24 passed. Browser interaction: 1 passed. The five
inherited Mermaid diagrams rendered successfully. Final CI reruns the complete suite
after the additional correction/contamination tests.

An overbroad `gitleaks dir /repo --redact --exit-code 1` scan of the whole working
directory returned 338 matches (172.60 MB, including ignored local/dependency data).
It is not a clean Git-history result. A separate exact non-ignored implementation
file projection scanned 1.80 MB with zero leaks; protected volumes/local credentials
were excluded from that projection. Final Git-history scan/CI checks the committed
revision. No raw detected values were printed or committed.

New tests cover track contamination, forbidden human attribution, source-only packet
validation, snapshot/rights/range/source changes, exclusive seals, original raw capture,
chronology/correction lineage, forged/duplicate references, unchanged accepted pairing,
pinned Git blobs, default/full versus opt-in scope and nested permission handling.
Inherited security tests cover README contradictions, forged locations/hashes,
unresolved imports/dynamic calls, unsupported semantics, ambiguous entrypoints,
missing/malformed sources and secret detection. No thresholds/safeguards were reduced.

Actual corrections before sealing: preflight used Git commit's tree SHA rather than
assuming commit SHA equals tree SHA; incomplete 0755 intermediate directories blocked
acquisition and were corrected to 0700; full Click parse fact cap prompted explicit
bounded scope; per-project idempotency key prevents conflict on retry; export query
removed nonexistent artifact `bytes` column; timestamps/Decimal usage units serialized
without inventing measurements. These export-only failures did not change persisted
predictions. Initial lint/type/test errors and a documentation link to this then-missing
report were corrected and rechecked. No independent review was fabricated to recover.

## I–K. Handoff, attribution and remaining gates

The owner must submit only A in a fresh ChatGPT conversation using the linked handoff.
Codex did not initiate ChatGPT review. Independent reference, authenticated blind
handoff evidence, adjudication and actual comparison are pending. No independent AI
or human PASS is claimed. Predictions stay sealed until that reference is recorded.
Scaling, official freeze and Phase 3 require separate owner authorization and gates.

Owner Git identity remains Stevemeg's existing author **and** committer; no co-authors,
AI/bot identities, fabricated human source authorship or history rewriting. Identity
origin, actual account association, complete messages and trailers are audited before
commit and handoff. Commits are unsigned and are not described as cryptographically
verified. Independent AI/human evaluation participation is separate from Git authorship.

Official requirements still missing: 20 DEV/60 TEST families; each of the 20 Python,
20 JS/TS and 20 mixed held-out slices; 10 genuinely new owner-authored hidden families;
100 reviewed variants across 20 held-out families; 600 independently human-reviewed
claims; 120 supported edges; actual appointed human reviewer; rights, retention,
custodian/access/budget approval and protected freeze. All approved official counts
remain zero. Exploratory sources/references cannot satisfy any of them.

## L. Stop condition

**READY FOR BLIND INDEPENDENT AI REVIEW** — preparation readiness only. Official
EVAL-ENTRY remains UNFROZEN. No prediction reveal, scoring, automatic expansion,
model training/benchmarking, deployment, merge or Phase 3.
