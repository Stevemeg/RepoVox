# Evaluation batch plan

Version `evaluation-batches-1.0`, 2026-10-12. [Targets](../ai/evaluation-plan.md) · [Readiness](../ai/evaluation-readiness.json) · [Effort log](../ai/evaluation-effort.json) · [Decisions](../delivery/phase2b-decisions.md).

| Batch | Authorized preparation / exit condition | Current state |
| --- | --- | --- |
| A | Owner-authorized synthetic engineering source → manual test annotations → schemas/source checks → blank worksheet/receipt/seal → scoring → full-sized synthetic freeze test; no official data | Tooling verified in tests; receipts simulate approval and never appoint humans |
| B | Individually selected shortlist, exact pins/license hashes, rights/access/provenance screening and owner decisions | Seven preliminary candidates; all pending, no source archives acquired |
| C | After owner rights/storage/budget approvals and actual reviewer appointment, select three small approved families, one per slice; independently author/review all facts and variants; measure real time | Blocked on owner/human prerequisites |
| D | Review pilot disagreement rate, workload and source limits; owner budgets further batches of roughly five to ten families with recorded family/split ancestry and no gold leakage | Not started; size subject to measured pilot |
| E | Validate all evidence, counts, access/contamination/retention and immutable versions, independently review EVAL-ENTRY handoff; freeze only full qualifying corpus | Not eligible; official UNFROZEN |

Maintain twenty DEV families and sixty TEST families (at least twenty Python, twenty
JS/TS and twenty mixed), ten genuinely newly owner-authored hidden TEST families,
one hundred independently reviewed variants on twenty TEST parents, six hundred
reviewed source-grounded claims and one hundred twenty supported reviewed edges.
Never substitute tooling fixtures, descendants, padded duplicate facts or generated
mutations for the approved targets. No partial official freeze.

After Batch C, record individual annotation/source/license/review/adjudication minutes
by family/slice/complexity, annotation/edge/variant counts, exclusions, corrections and
cash receipts if any. Forecast remaining labor from observed per-family distributions
and uncertainty; the three-family pilot is small and cannot establish broad throughput.
Budget changes require owner approval. No spending or human labor hours have been
measured/authorized by this work; automated elapsed test times are not review effort.

For metadata-only report, run `uv run python tools/phase2_preparation.py --catalog
docs/ai/evaluation-candidates.json --manifest docs/ai/evaluation-corpus.manifest.json`.
This explicitly marks approvals/storage unverified. After actual prerequisites, a
protected dry-run adds `--verify --source PRIVATE_FAMILY_ROOT --provenance
PRIVATE_PROVENANCE --preparation PRIVATE_PACKET`. The packet contains scoped approved
catalog records, sealed human receipts, reviewed variants/authorship and authenticated
operational/budget/retention evidence. Dry-run success means mechanical eligibility,
never an independent PASS. Actual immutable freeze uses `tools/phase2_corpus.py`
with the same evidence and an external protected output. Stop before Phase 3.

Freeze output is an immutable `eval-entry-freeze-record-1.0` wrapper containing the
accepted `corpus` object plus the exact preparation-packet SHA-256; retain both bytes
in the approved version. Load its `corpus` field into the existing Corpus contract.
The wrapper binds supplemental rights/review/variant/operational evidence without
silently changing corpus 2.0's freeze digest. Independent gate approval remains separate.
