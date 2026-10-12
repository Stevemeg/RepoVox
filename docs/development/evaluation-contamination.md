# Evaluation contamination and withdrawal procedure

Version `evaluation-contamination-1.0`, 2026-10-12. [Training exclusions](../ai/training-strategy.md) · [Source families](../ai/evaluation-rights.md) · [Storage](evaluation-storage.md).

Assign each repository's forks, revisions, copied templates, descendants and mutations
to one reviewed family before split assignment. Record canonical URLs/SHAs, ancestry
evidence and explicit unknowns. GitHub non-fork metadata is only a suggestion; manually
inspect templates/history and copied code where rights allow it. Unknown family ancestry
blocks admission. Duplicate IDs/derivative aliases fail freeze, including duplicates
within one alias list.

The accepted intake hashes complete screened source inventories and fingerprints
eligible files at least 64 bytes long. Freeze rechecks inventory/SHA/hash and detects
cross-family fingerprint overlap; small files, semantic clones, rewritten code and
unknown base pretraining remain limitations. Supplement exact hashes with whitespace
normalized source fingerprints and similarity/ancestry review. Normalize only for
triage; never change original citation hashes or use a normalization match as proof of
semantic identity. Inspect suspected common snippets and regroup/exclude as necessary;
do not weaken the exact-overlap gate or use model verdicts to label independence.

`uv run python tools/phase2_preparation.py --fingerprints PRIVATE_SOURCE --output
PRIVATE_STORE/fingerprints.json` writes keyed raw/normalized inventories inside a
protected store, printing only the key. `grouping_suggestions` compares inventories
and returns overlapping family groups for manual review; it never approves ancestry.

Keep a private contamination manifest with inputs/tool version/hash, all split/family
assignments, raw/normalized fingerprint findings, manual ancestry decisions and cleared
or unresolved overlap. Freeze needs its immutable hash and custodian operational review;
a record saying "clear" alone cannot demonstrate the comparison. No actual approved
corpus comparison exists today. The readiness report says NO_APPROVED_CORPUS.

Before any later training, calibration or prompt experiment, compare its family ancestry
and raw/normalized fingerprints to both evaluation pools without exposing protected
gold. Any overlap blocks admission; DEV is excluded from fine-tuning/calibration too.
TEST source/gold is unavailable to prompt tuning or calibration. Maintain access logs
and final-run registration; a leaked or iteratively tuned TEST pool is invalid and needs
a new independently prepared version, not another claimed pass. Unknown upstream base
pretraining contamination must be disclosed; new private owner works reduce risk but
cannot prove universal absence.

Withdrawal/takedown identifies every family descendant and affected immutable version,
source/gold/rubric/variant and score report. Existing `withdraw` sets WITHDRAWN and
invalidates dependent reports; physical source/gold/backup deletion is a separate
custodian duty. Preserve minimal suppression hashes, invalidate eligibility, replace
and independently re-review/freeze a new version, then rerun only separately authorized
evaluation. Do not rewrite a frozen manifest or silently reduce its denominator.
