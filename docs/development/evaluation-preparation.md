# Evaluation corpus preparation tooling

[Approved targets and EVAL-ENTRY](../ai/evaluation-plan.md) · [Current manifest](../ai/evaluation-corpus.manifest.json) · [Schema](../ai/evaluation-corpus.schema.json) · [Cost assumptions](../operations/cost-model.md#research-and-specialization-budget)

Status: UNFROZEN. Independent human reviewer: **PENDING OWNER APPOINTMENT**.
Corpus contract is now `evaluation-corpus-2.0`, with canonical `gold-evaluation-1.0`
annotations and `source-fact-1.0` matching. See [gold authoring and scoring](evaluation-gold.md).
No official admitted families, gold claims, gold edges, protected fixtures
or frozen split currently exist. The [Phase 2B catalog](../ai/evaluation-candidate-catalog.md)
contains seven preliminary candidates, all pending rights/owner approval. Dynamically created engineering fixtures and public
live-smoke samples are not an evaluation corpus or approved independent gold.

`repovox.evaluation.corpus` supplies strict rights/family/citation/review/appointment/
manifest contracts, immutable manifest hashing, family/derivative/fingerprint overlap
checks, count gates, separate split/purpose access policy and withdrawal report
invalidation. `tools/phase2_corpus.py` inspects manifests, validates source citation
hashes/ranges, requests freeze only when prerequisites exist, and records withdrawal.
It never produces human appointments, rights grants, labels or approvals.

Phase 2B adds separate `eval-entry-preparation-1.0` and `evaluation-candidates-1.0`
contracts, digest-sealed complete human review receipts, hidden authorship and materialized
variant evidence, actual POSIX boundary checks and metadata-only versus verified dry-run
readiness. Existing corpus/gold/source-fact contracts and scorer remain unchanged.
See [authoring](evaluation-authoring.md), [reviewer packet](evaluation-reviewer-packet.md),
[batch plan](evaluation-batches.md), [protected storage](evaluation-storage.md),
[contamination](evaluation-contamination.md), [adversarial plan](evaluation-adversarial-plan.md),
[readiness](../ai/evaluation-readiness.json) and [owner decisions](../delivery/phase2b-decisions.md).
Freeze now requires the actual protected preparation packet in addition to the accepted
source/provenance checks. Neither schemas nor arbitrary evidence hashes authenticate
human approval; custodian/owner verification of private records remains mandatory.

## Repeatable intake and review

1. Owner prepares new synthetic sources specifically for RepoVox outside Git, or
   individually reviews public candidates. Pin actual commits; retain license text/hash,
   actual evaluation permission evidence, attribution, permitted human access, retention
   and withdrawal lineage. Public visibility alone is insufficient; ambiguous rights
   remain pending/excluded. Do not collect arbitrary repositories to meet counts.
2. Use secure ingestion/source manifests and secret/privacy screening. Record source
   manifest hash, code fingerprints, reviewed family grouping/fork/template ancestry,
   language slice and split. Source bytes and hidden labels stay outside ordinary
   application storage. No source execution or dependency installs.
3. Gold preparer manually writes source symbols, entrypoints, qualified edges and atomic
   claim facts/expected verdicts in the canonical gold contract. Purpose, expected
   abstentions, conflicts and adversarial observations needing semantic review are
   recorded in the separately reviewed rubric/provenance and explicit safety observations.
   `validate_labels` checks file containment/hashes/line ranges and required support;
   it cannot establish semantic entailment. Do not use analyzer/model output as gold.
4. Owner appoints an actual independent human and records appointment/rights evidence.
   Preparer and reviewer IDs must differ. Record source review, disagreements,
   adjudication and approval evidence hashes. ChatGPT is the technical validator, not
   a human reviewer; no invented appointment or self-signature is permitted.
5. Custodian supplies access/contamination/deletion manifests and immutable source/gold/
   rubric/review versions. Freeze family assignments before benchmarking. All descendants
   remain in one family/split. Review must cover the real approved targets: 20 EVAL_DEV,
   60 EVAL_TEST including 20 per language slice and ten new owner-authored hidden families,
   100 distinct adversarial variants from at least twenty held-out families, 600 claims
   and 120 supported edges. Missing prerequisites make freeze fail, not reduce targets.

## Access and contamination boundaries

The `evaluation` PostgreSQL schema has no ordinary application/worker/executor grants.
No project routes expose corpus metadata/gold. The offline custodian store requires an
external POSIX directory owned by its process with mode 0700 and immutable 0600 files;
it rejects Git-contained paths and unsupported Windows ACL claims. Do not mount it into
API, acquisition, parser or prompt-development containers. Linux parser Landlock also
denies unassigned filesystem reads, and parser environment contains no custodian keys.
Actual protected sources/access identities are absent until owner appointment and
custodian provisioning; no protected-corpus access-control deployment is claimed.

Both EVAL_DEV and EVAL_TEST are forbidden for training/calibration. EVAL_TEST is denied
to development/prompt-tuning; controlled final evaluation requires frozen corpus and
registered configuration. Human preparation uses a distinct appointed custodian/review
workflow before freeze, not a prompt-tuning path. Later model phases must implement their
own restricted runner capabilities and cannot infer authorization from a manifest flag.
Fingerprints/family checks do not prove absence from unknown base pretraining.

Withdrawal invalidates the corpus and dependent reports, preserving minimal suppression
lineage. Custodian removes actual live source/gold under the documented retention policy;
manifest invalidation alone does not prove physical or backup deletion/unlearning.

## Deterministic evaluator

`repovox.evaluation.scoring` imports no analyzer modules. It validates the canonical
gold inputs, compares symbol/import/graph/entry sets, and pairs atomic facts using
original source identities rather than assuming equal IDs. It reports both pairing
denominators, false verification among matched labelled facts, unscored predictions,
unsupported rejection, precision/recall and original citation validity. Zero/partial
pairing is INCOMPLETE, including in aggregates; complete pairing is not an acceptance
PASS. It reports coverage, parser/conflict/safety observations. Semantic support, purpose,
adversarial behavior and secret leakage observations require actual reviewed annotations
and executed instrumentation; absent observations are not passes. No Director weights,
paid evaluator, training or calibration is used.

```powershell
uv run python tools/phase2_contracts.py --check
uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json
# Expected exit 2: no independent appointment/corpus; never a successful freeze.
uv run python tools/phase2_corpus.py docs/ai/evaluation-corpus.manifest.json --action freeze
```

Full Phase 2 acceptance remains blocked by actual rights-approved corpus preparation,
independent human review and freeze; green engineering tooling cannot substitute.
