# ADR-0014: Separate blind AI exploratory evidence

Status: proposed for independent technical review; owner authorized implementation.
Date: 2026-10-13. Version: `exploratory-preparation-1.0`.

The accepted [independent gold contract](0012-independent-gold-contract.md) and
[human preparation supplement](0013-eval-entry-preparation-evidence.md) remain
unchanged. The owner authorized a separate, small AI source-review experiment.
ChatGPT is `INDEPENDENT_AI_TECHNICAL_REVIEWER`, never an actual human approver.

Use `AI_AUDITED_EXPLORATORY` outside Git and outside official DEV/TEST namespaces.
Strict policy literals prohibit official counts, human-review attribution, training,
held-out benchmark claims, full corpus freezing and production certification.
Official corpus, candidates and readiness files retain their accepted bytes.

Package A accepts only original source, filtering inventory, pinned links, checksums,
line-numbered redacted excerpts, rights and scope limitations. Package B retains real
durable analysis artifacts and predictions separately. Seal B before A handoff; the
source-only export includes its opaque commitment, never predicted answers. Exclusive
writes, independent events and hash checks detect modifications; they are not WORM
storage or authenticated proof that someone read code.

All-file acquisition, secret screening, archive safety and isolated static parsing
remain required. Click's unbounded parse hit the existing 10,000-fact limit. A minimal
`AnalysisRunner.preparation_filter` hook defaults to identity. The opt-in exploratory
runner narrows eligible/context files after Stage 3's complete security scan, retaining
every original file/hash and explicit outside-scope reasons. It keeps parser/fact/byte
limits and source verification unchanged. Normal app jobs keep full scope. Scoped
manifests and scope lists are bound by artifact hashes and the sealed prediction;
selected-scope coverage must not be presented as whole-repository parser coverage.

After actual manual ChatGPT handoff, retain the raw response privately, record its
capture event, author the typed AI reference from that response and seal it against A/B.
Source-fact alignment and scoring reuse the accepted scorer without relaxed pairing.
Mechanical capture hashes establish bytes/order, not reviewer identity or independence;
the owner must inspect authentic conversation evidence and confirm the blind process.
Comparison cannot self-award independent PASS; unsupported semantic observations need
explicit source review and unresolved comparisons remain INCOMPLETE/REVIEW_REQUIRED.
Corrections require a new reference seal with private change rationale and source
evidence; preserve prior versions and reports, never edit approved bytes.

No database migration, dependency, paid service, model, deployment or training is added.
Rollback stops offline tooling and withdraws exploratory versions; default analysis is
unchanged. Sources/packets, S3 copies and owner exports require actual custodian deletion
on withdrawal; hashes/flags alone do not delete data. Official human reviewer,
authorship, rights, retention, custodian and full corpus gates remain unresolved.

See [handoff](../development/exploratory-handoff.md) and
[verification](../delivery/phase2c-a-verification.md).
