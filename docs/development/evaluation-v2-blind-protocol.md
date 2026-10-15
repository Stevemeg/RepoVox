# Future v2 blind pilot protocol — design only

No new pilot is authorized or executed by Phase 2C-D. These steps require separate
owner approval and independent acceptance of the v2 evaluator first.

1. Obtain source-specific rights, reviewer access, retention/withdrawal rules,
   custodian identity/location, scope and budget approval. Use no official TEST gold.
2. Acquire pinned sources through the accepted secure ingestion engine. Preserve
   rights notices, inspected Git/blob evidence, complete original hashes, filtering,
   secret screening and exclusions. Never execute repository code.
3. Prepare `evaluation-source-scope-2.0` and source-only A. Its strict schema contains
   scope commitment and original numbered excerpts only. Preserve original bytes.
4. Freeze and record the approved engineering and scorer Git commits before analysis.
   Run the authorized static analysis, preserve original verify bytes, and produce
   the versioned prediction projection. No reference or answer input is permitted.
5. Seal B before handing off A. Record SOURCE_APPROVED and PREDICTION_SEALED events.
6. Hand only A, source permalinks, permitted scope and opaque A/B commitments to the
   independent reviewer. Record SOURCE_HANDED_OFF. Do not expose predictions.
7. The reviewer independently writes v2 assertions from source, with explicit scope,
   unknowns, evidence judgments and semantic limitations. No analyzer suggestions.
8. Capture the actual original response separately from exported reference files.
   Preserve exact bytes and owner-attested conversation evidence; record
   RESPONSE_CAPTURED. Hashes/timestamps do not authenticate ChatGPT provider identity.
9. Validate original reference bytes, A/B/scope bindings, source citations and capture
   evidence; preserve them and record REFERENCE_SEALED. Do not normalize/rewrite gold.
10. Verify all retained events, exact bytes, independent trusted event-head commitment,
    original source and scope before B parsing. Record PREDICTION_REVEALED, then parse
    the existing B. `reveal` implements this ordering; invalid source stops first.
11. `compare_sealed` requires the retained reveal event and uses the pre-approved scorer.
    Preserve the complete report bytes and record COMPARISON_SEALED. No overwrite.
12. Give the independent reviewer source-grounded discrepancies and report commitments.
    Every new correction preserves its predecessor, explanation, source citations
    and retained owner approval. Record `revision_context: post_reveal_correction`
    after reveal; never relabel it as a blind source-only correction.
    Post-reveal revisions are explicitly post-reveal diagnostics, never a new blind run.

## Custody controls and limitations

Use a new authorized v2 namespace outside Git and the historical custodian materials.
`Store` requires POSIX owner permissions, rejects overlap with Git, checks separate
worker identity and tenant on access, and writes exclusive 0600 files in a 0700
directory. The original capture/reference byte stream is hashed and stored unchanged.
Never mount this directory into routine API/worker containers or upload raw data to CI.

Sequence reservation files prevent replay/forking through the trusted tooling. Events
contain the previous event hash, UTC capture time, scope, tenant/session, engineering
and scorer commits, payload commitment and trusted execution context. Retain the final
event hash independently; without an external commitment, local history replacement
cannot be excluded. A partial write fails closed and requires custodian recovery;
do not delete reservation files to bypass chronology.

DAC and checksums are not administrator-proof WORM, legal proof, actual reviewer
authentication or evidence of reading code. Approved operators can access protected
files; administrators can change the host. A local clock can be wrong. Owner-attested
review evidence must be described accurately. Synthetic tests do not provision or
authorize an official custodian.

On withdrawal, stop affected comparisons, record invalidation lineage and remove
source/reference/capture copies from the custodian, exports and backups according to
approved retention rules. Manifests alone do not delete bytes. Restore backups into an
isolated custodian, recheck hashes/events/permissions and withdrawal records before use.
No backup service or infrastructure is provisioned by this implementation.

## Source-only authoring interface

An authorized custodian first stores approved source/proof/reference bytes using
`Store.write` and retains their SHA-256 values. It never uses analyzer output to fill
reference expected statuses. Then, inside that POSIX boundary:

```text
uv run python tools/phase2_v2_reference.py --store PRIVATE_ROOT --tenant TENANT \
  --worker-uid APPLICATION_UID --source PRIVATE_ROOT/SOURCE \
  --scope-sha256 SCOPE_HASH --reference-sha256 ORIGINAL_REFERENCE_HASH \
  --proof-sha256 RIGHTS_HASH --proof-sha256 PIN_VERIFICATION_HASH \
  --proof-sha256 BLIND_SOURCE_HASH --proof-sha256 ORIGINAL_RESPONSE_HASH \
  --proof-sha256 SOURCE_ONLY_ATTESTATION_HASH
```

Repeat `--predecessor-sha256` and proof options for immutable revisions. Output reports
only structural validation, reference commitment and counts; it never issues semantic
approval. The CLI accepts no prediction payload and provides no gold-generation or
automatic blind-review action. Future operational reveal/comparison uses the reviewed
library protocol only after separate authorization.

The trusted custodian must verify the executing checkout against the approved
`scorer_commit` and the prediction engineering commit before operating the protocol.
Event metadata records that approval; it is not remote attestation of executing
code. `compare_sealed` separately rechecks the retained reveal reservation and
prediction engineering binding, even if the lower-level event writer was used.
