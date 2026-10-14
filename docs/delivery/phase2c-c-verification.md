# Phase 2C-C engineering verification

Date: 2026-10-14. Implementation-assistant evidence, not independent acceptance.

## Baseline and scope

Fetched and inspected the actual Git/GitHub state. The clean starting branch was
`phase2/ai-audited-pilot`, exactly `8b1674de8459725bba25646e3fdd223a57316150`.
PRs #1–#5 were open and unmerged; #5 targets `phase2/eval-entry`. The new branch
is `phase2/canonical-fact-remediation`, stacked against #5's branch. No older PR
was edited or merged. The owner explicitly approved the narrowly scoped additive
artifact-version migration after the hardcoded persistence constraint was found.

This work addresses F-02/F-03 structural understanding and N-01 evidence trust.
It includes no acquisition, evaluation expansion, model work, deployment or
spending. Synthetic engineering fixtures are not official evaluation entries.

## Failure mechanisms

The historical 2C-B comparison reported 84 independent facts, 795 predictions,
zero exact matches, and 404/404 valid source citations. It also reported 8 versus
391 graph edges, 76 versus 404 symbols and 8 versus 1 entrypoint candidates.
These are historical counts, not rerun measurements. Zero exact pairing is not
zero semantic accuracy: the independent annotations are partial, and syntax
vocabulary, import attributes, ranges and graph levels did not interoperate.

| Mechanism | Engineering response |
| --- | --- |
| Parser-rule labels formed part of v1 identity | Add explicit v2 identity with extractor provenance separated |
| Imports conflated modules, members and local aliases | Preserve explicit parsed module/member/binding/type-only metadata |
| Graph primarily connected modules to syntax | Add qualified member-import, inheritance, lexical-call and constructor edges |
| Packaging/library/plugin declarations were missing or conflated | Add typed candidates with conservative ranks and execution disclaimers |
| Individual configuration fields cited whole files | Localize original JSON properties and TOML assignments |
| Artifact persistence hardcoded old metadata | Add versioned completion procedure, retain old procedure, reject mixed-version jobs |

## Canonical contract and compatibility

[ADR-0015](../adr/0015-canonical-source-fact-semantics.md) and the
[normative specification](../development/canonical-facts.md) define
`source-fact-2.0`, analysis `2.3` and rules `static-rules-v2`. Repository SHA,
complete original-file checksum, byte/line location, member, alias, binding,
dispatch, relationship and resolution remain identity-bearing. Only parser-rule
provenance and support ordering are normalized. Exact original source anchors
and endpoints are required; duplicate canonical facts are rejected.

Legacy analysis 2.2 models were copied unchanged into `contracts_v22.py` and
dispatched explicitly by envelope version. Its published schema is unchanged.
The original gold, corpus, exploratory and source-fact-1.0 scorer implementations
and schemas have no diff. Existing independent synthetic v1 evaluation-path tests
still pass. There is no translation or rescore of historical references.

The new fact records are emitted in ordinary analysis, without exploratory
repository names, reference IDs or private answers in production rules. A future
independent v2 annotation/scoring integration needs explicit version selection
and review; this PR does not substitute v2 identities into the accepted v1 scorer.

## Parser, graph and entrypoint behavior

`bindings.py` computes lexical scopes and conservative name bindings from the
parsed syntax. Module/member imports retain aliases; JS/TS imports record each
named/default/namespace binding and type-only status. Python base expressions
have their own source ranges. Classes, nested functions, arrows, direct named
exports, call sites and constructor expressions retain qualified names.

`relationships.py` adds `imports_symbol`, `inherits`, `calls_lexically` and
`instantiates` with source/target identities and original supporting symbols.
Resolution requires a unique local target. External dependencies, ambiguous
module extensions, cycles, type-only imports, parameters, rebinding, conditional
definitions, dynamic property calls and replaced/decorated definitions prevent
qualified resolution. Python self/forward bases do not acquire resolved edges.
The existing module graph and unresolved expression observations remain present.

Candidate categories distinguish executable-guard syntax, candidate commands,
library exports, types, build backends, packaging hooks and plugin declarations.
Coverage includes package main/module/bin/types/typings/export maps, default
exports, imported Click decorators, Jupyter hook conventions, setuptools calls,
and structural id/activate plugin objects. New non-application candidates do not
cross the executable selection threshold. No candidate proves execution.

## Citation precision and assertion semantics

JSON nested properties and array elements use original token spans. TOML uses
validated original assignment spans, including multiline values and comments.
Duplicate keys reject the configuration. Dependencies and entry targets reuse
those ranges in source evidence. Function/class citations remain the exact full
syntax-node definition span, including body; they are not claimed to be
header-only citations. Import declarations and base expressions retain their
original multiline or expression ranges. Whole-file hashes are never narrowed
to excerpt hashes.

Stage 9 re-extracts symbols, configuration, graph and canonical facts before
accepting static claims. Changed source, canonical metadata and wrong citations
are rejected. Documentation remains documentation-only; unresolved relationships
remain inferred. Static calls and constructors never assert successful execution.

## Regression matrix

`tests/unit/test_canonical_remediation.py` contains 42 deterministic cases using
explicitly authored, non-pilot source examples. They cover Python imports and
aliases; inheritance; Python/JS/TS lexical calls; nested arrows; parameters and
shadowing; rebinding; conditional/dynamic/external targets; import cycles and
ambiguous paths; type-only constructors; direct exports; CLI/packaging/plugin
candidates; nested/multiline configuration; duplicate keys; original SHA and
range checks; alternate parser display/provenance equivalence; meaningful
identity differences; canonical tampering/duplication; legacy envelope dispatch;
and binding time/fact limits. Every parsed fixture checks original byte-derived
line ranges and SHA-256. Semantic expectations are explicit assertions, not
analyzer-generated answer keys.

Existing tests retain documentation-only claims, forged evidence, missing source,
wrong source hashes/ranges, security screening, gold completeness, scoring,
official isolation and immutable review controls. No coverage gate was reduced.

## Persistence and security

Migration 0003 adds `rv.finish_analysis_v23` and `rv.analysis_scope_v23`. The old
completion function definition is unchanged, verified across a fresh 0002→0003
upgrade. A version guard prevents both legacy→new and new→legacy mixing. The
runner rejects incompatible prior artifacts before reading their payloads.
Startup now requires revision 0003. Existing 2.2 artifacts remain readable;
unfinished 2.2 jobs need an explicitly admitted new job rather than an automatic
upgrade. The fixed Stage 2–9 pipeline protocol remains `phase2-static-v1`.

The migration adds no columns, rewrites no evidence rows and preserves RLS,
fencing, object ownership, retention, worker restrictions and immutable artifact
triggers. Execution grants are applied as `rv_executor`, with public/application
execution revoked. Integration tests check the new grants and both version-mixing
directions, alongside existing stale-lease and cross-tenant controls.

Only the isolated `repovox-test` database was migrated. The private pilot database
and its volume were not migrated. A read-only, network-disabled custodian check
matched all 380 retained original files against the pre-comparison inventory,
with zero original additions/deletions and no prediction-payload parsing. No
private gold, raw packets, screenshots, conversation evidence or source archives
are included in the engineering diff or CI.

## Executed checks and development failures

Commands ran locally unless a CI run is explicitly linked in the PR handoff.

| Command/check | Observed result |
| --- | --- |
| `uv run ruff check apps/api tests tools/phase1*.py tools/phase2*.py` | Passed |
| `uv run ruff format --check apps/api tests tools/phase1*.py tools/phase2*.py` | 81 files formatted at that checkpoint |
| `uv run mypy` | Passed, 48 source files |
| `uv run pytest tests/unit -q --disable-warnings` | Windows: 276 passed, 23 POSIX-only skips, 27.06 seconds |
| `uv run pytest tests/unit/test_canonical_remediation.py -q --disable-warnings` | 42 passed, 1.29 seconds |
| Linux `pytest -q --tb=short` | Final code: 326 passed, 1 Windows-only skip, 94.84 seconds; includes all unit and integration tests |
| Linux `pytest tests/integration -q --tb=short --maxfail=2` | 28 passed, 49.86 seconds |
| `python tools/phase2_storage_probe.py` in restricted Docker test environment | Synthetic custodian UID 10002, worker UID 10001; OS read denied; modes 0700/0600 |
| `uv run python tools/check_docs.py` | Documentation, links, contracts, IDs and attribution checks passed |
| `uv run python tools/cost_model.py --check` | Passed; historical estimates remain hypotheses |
| `uv run python -m unittest discover -s tools -p 'test_*.py' -v` | 32 passed |
| `uv run python tools/phase1_contracts.py --check` | OpenAPI unchanged |
| `uv run python tools/phase2_contracts.py --check` | Frozen and additive schemas passed |
| Corpus and preparation CLI checks | Official corpus UNFROZEN; all approved/reviewed counts remain zero |
| Frontend lint/types/test/build | Passed; 17 tests; local build succeeded |
| `npm --prefix apps/web audit --audit-level=high` | Zero vulnerabilities |
| `uv run pip-audit --local` | No known vulnerabilities; local RepoVox package has no PyPI audit record |
| Gitleaks v8.30.0 on intended public-file export | Zero leaks, 211 files / approximately 1.95 MB at that checkpoint |
| `npm --prefix apps/web run test:e2e` | One browser regression passed, 17.4 seconds |

Docker test commands use
`docker compose -p repovox-test -f docker-compose.yml -f .artifacts/phase2-ports.yml`
with `run --rm --no-deps tests`. API/worker/dispatcher processes were stopped
before integration fixtures truncated their disposable data, then restored.
No protected evaluation data was mounted into ordinary services or public CI.

Development failures were fixed rather than hidden: new fields initially failed
the old schema assertion, which now explicitly checks 2.3 while legacy validation
has a separate test; a Windows text-edit encoding error in an existing Unicode
collision fixture was restored from original UTF-8 bytes; endpoint support was
added to canonical relationship records; mypy/formatting findings were corrected.
The first migration integration run had 3 failures and 23 setup errors: startup
still required 0002 and new-function ACL revocation had run under the wrong role.
The startup version and role-context grants were corrected. The development test
database ACLs were repaired explicitly; the fresh upgrade test then verified the
corrected migration, and all 28 integration tests passed. No bypass was added.

The final-head CI workflow includes all new tests and the existing full Linux
suite, synthetic runtime/browser regression, dependency audits and history secret
scan. Its actual run URL and outcome belong in the draft PR's final review
handoff; pending CI is not a claimed pass.

## Measurements, limits and next verification

Durations above are actual automated execution times, not human labor. Human review time was not measured and no human approval was recorded. No
purchases or paid external services were initiated. No pilot latency
or accuracy was recomputed. No new CPU/RSS performance study was performed.
The accepted sandbox retains wall/CPU/memory/file caps; binding analysis now adds
a two-second budget, ancestry depth cap and early fact-count check.

Remaining limitations include runtime dispatch, external implementations,
namespace-property calls, transitive re-exports, package search paths, complex
parameter patterns and dynamically constructed framework/plugin wiring. Generic
plugin id/activate shape can identify unrelated objects; it is a low-ranked
candidate requiring review, not a framework identity assertion. TOML array/inline
table elements can share their enclosing assignment span. Whole-file parse
coverage does not imply semantic coverage. No broad real-world accuracy claim is
supported by these tests.

Review [the public engineering handoff](phase2c-c-reviewer-handoff.md), the
canonical contract, parser ambiguities, versioned persistence and final-head CI.
Independent engineering acceptance is pending. Official EVAL-ENTRY remains
UNFROZEN; approved human-reviewed counts and historical 2C-B results are unchanged.
Stop before any new evaluation, model experiment, merge or Phase 3.
