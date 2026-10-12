# Evaluation candidate catalog

Version `evaluation-candidates-1.0`, captured 2026-10-12. [Structured records](evaluation-candidates.json) · [Rights procedure](evaluation-rights.md) · [Readiness](evaluation-readiness.json) · [Batch plan](../development/evaluation-batches.md).

Seven individually selected public candidates were screened using GitHub commit,
language and non-fork metadata and actual license bytes at the recorded full SHA.
Only metadata and license text were fetched; no repository archives or source code
were downloaded. Original license evidence remains in the local temporary screening
directory outside Git. That temporary directory is **not** an authorized protected
custodian or durable evidence store; re-fetch and verify hashes when transferring
approved evidence. GitHub language metadata is preliminary and may include tests or
documentation; actual slice assignment requires the screened pinned source inventory.

| Family | Preliminary slice | Pinned root license | Complexity / reason to consider |
| --- | --- | --- | --- |
| stevemeg-ai-job-agent | Mixed | MIT | Owner account; Python/JS architecture candidate, authorship unverified |
| stevemeg-enterprise-llm-gateway | Python | MIT | Owner account; larger multi-module candidate, may exceed limits |
| pallets-click | Python | BSD-3-Clause | CLI entrypoints and utility modules |
| sindresorhus-is | JS/TS | MIT | TypeScript library and export relationships |
| sindresorhus-p-limit | JS/TS | MIT | Small package, async/runtime qualification |
| simonw-datasette | Mixed | Apache-2.0 | Python/JS application, NOTICE and size screening needed |
| jupyterlite-jupyterlite | Mixed | BSD-3-Clause | Python/TS packages, generated/vendor/size screening needed |

All seven are **candidate / rights pending**, with zero rights-reviewed or owner-approved
records. Root license inspection is preliminary evidence, not a file-level rights
clearance. The catalog records full SHAs, exact text hashes, notice obligations,
pending redistribution/reviewer permissions, retention, ancestry uncertainty and
reasons. Empty ancestry means unknown, not proof of independent family origin.
The two repositories on Stevemeg's account are not asserted to be human-authored or
newly hidden. Existing public repos cannot satisfy the newly authored hidden target.

Repositories without an apparent license were not shortlisted; public visibility,
account ownership and a Git commit identity do not supply missing rights or authorship.
No developer has granted separate evaluation permission in this session. Large
repositories may be rejected; selecting a subproject needs a separately pinned scope,
rights and derivative-family review, not silent truncation or relaxed PRD limits.
Batch B is an initial balanced proposal, not an 80-family approved corpus.

Repeat individual screening with `uv run python tools/phase2_candidate.py
https://github.com/OWNER/REPO --output EXTERNAL_NEW_DIRECTORY`. It resolves the
actual SHA and hashes license bytes; it cannot approve rights or download an archive.
Review each candidate before any subsequent source acquisition. Never bulk-acquire
repositories to fill counts.
