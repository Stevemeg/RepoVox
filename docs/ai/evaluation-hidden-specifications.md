# Proposed owner-authored hidden families

Version `hidden-specifications-1.0`, 2026-10-12. [Provenance decisions](../delivery/phase2b-decisions.md) · [Gold handbook](../development/evaluation-authoring.md).

These are **Codex-prepared specification proposals**, not implementations, owner works,
gold labels or approved evaluation entries. No hidden repository was authored in this
session. The owner chooses and personally implements approved specifications in private
repositories inside the approved custodian boundary. Keep actual names, code, detailed
cases and gold private; public proposals alone cannot provide hidden provenance.

| Proposal | Slice | Scope and independently observable static challenges |
| --- | --- | --- |
| H01 | Python | File inventory utility; CLI/main guard, filtering functions and unused helper; documented feature intentionally absent |
| H02 | Python | Small API app with routes, service and repository modules; dependency declaration differs from an implemented integration |
| H03 | Python | Plugin utility with registry, aliases and dynamic selection; static unresolved targets require explicit qualification |
| H04 | JS/TS | JavaScript concurrency package; default/named exports, promises and distinct same-name functions; execution never asserted |
| H05 | JS/TS | JavaScript CLI/package with multiple command declarations, test runner and unused script target; distinguish candidates |
| H06 | JS/TS | TypeScript validation library; re-exports, interface/type-only imports, overloads and missing optional dependency |
| H07 | Mixed | Python service plus TypeScript client; shared conceptual API does not prove a static cross-language call edge |
| H08 | Mixed | Multi-module Python worker and JS dashboard; duplicated symbol names, queue contract and stale architecture diagram |
| H09 | Mixed | Python CLI with JS build helper; conditional imports, renamed module, ambiguous import paths and unresolved reflection |
| H10 | Mixed | Small Python/TS extension host; several entry candidates, dynamic dispatch, missing referenced component and contradictory README |

Complexity is a proposal: keep each family within [PRD limits](../product/prd.md#supported-limitations),
with enough distinct reviewable facts to cover claims/edges and honest insufficient
evidence cases. No target requires padding trivial duplicates to reach 600 claims.
The ten do not alone meet the twenty-per-language held-out quotas. Variants belong to
their parent family, never a fresh hidden-family count.

For every actual work, owner records creation date, authorship declaration, upstream
snippets/templates/dependencies, any AI assistance and precise source portions authored
by the owner. A human reviewer confirms the provenance basis. AI-written implementations
committed under the owner's identity cannot become genuinely human-authored by signing
a declaration. Codex can supply test harnesses and scaffolding in separately labeled
engineering locations; copied scaffolding must be disclosed and does not establish
independence. Reject or regroup copied templates. Never commit protected sources or
answers into RepoVox's public history. `HiddenAuthorship` records hash private owner
declaration, provenance and reviewer confirmation; all are absent today.
