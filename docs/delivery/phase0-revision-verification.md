# Phase 0 self-hosted revision verification

Revision against `ba9ec7ef000378c325ebb367250331a59874aad5`, 2026-10-08. **Phase 0 remains unapproved. READY FOR INDEPENDENT RE-REVIEW means documentation handoff, not approval or production readiness.** Existing [PR #1](https://github.com/Stevemeg/RepoVox/pull/1), branch `phase0/foundation`, base `main`. New submission SHA is reported in the PR/final completion report; this document does not claim to know its own enclosing commit hash.

## Executed evidence and limits

| Exact command/action | Observed result |
| --- | --- |
| `python tools/check_docs.py` | PASS: required files, Markdown links/anchors/fences/tables, JSON parsing, Draft202012 schemas, 10 synthetic artifact contracts, Director input/output/persisted safe visuals and citations, original byte/SHA/range/claim/audio/frame checks, 11 rejected mutations, F-01-13/N-01-08 traceability, state diagram transition set and Git identities/trailers. |
| `python tools/cost_model.py --check` | PASS: generated table matches document, GPU busy+load+idle partitions paid warm hours, utilization fleet sizing and CPU analysis/orchestration/TTS/render capacity below planning ceilings. No target requiring self-host inference cheaper than APIs. |
| `python tools/cost_model.py --json` | PASS: reproducible production/research/reference scenarios, capacity-limited break-even and slow/base/fast throughput sensitivities printed; no remote billing/model request. |
| `python -m unittest discover -s tools -p test_cost_model.py -v` | 9 tests PASS: workload units/attempts, zero-volume idle expense, replica capacity step, no double-counting loads, scenario/research separation, API replacement arithmetic, feasible/impossible break-even, loading/throughput sensitivity, invalid fleet inputs. |
| `git -c core.safecrlf=false diff --check` | PASS: no whitespace errors. CRLF normalization warnings from normal Git reads are benign; tracked LF policy preserved, identity config unchanged. |
| Mermaid CLI commands below | PASS: 2 architecture charts and 2 persistence/state charts rendered to SVG/PNG outside Git; previews inspected for readable roles, arrows and transitions. No video/media render occurred. |
| Official web research + Python urllib metadata/license retrieval | Model cards/configs/license texts, vLLM/PEFT/TTS/AWS/Runpod/price documentation inspected. [Inventory](../ai/research-sources.json) pins observed model revisions and available small license-text hashes. No model weight download, GPU benchmark, dataset collection or paid request. |
| `git config --show-origin user.name`; `git config --show-origin user.email`; `git var GIT_AUTHOR_IDENT`; `git var GIT_COMMITTER_IDENT` | Existing global config/effective author and committer both Stevemeg / konabharath2004@gmail.com. No settings changed. |
| `git log --all --format='%H %an <%ae> | %cn <%ce>%n%B'`; authenticated GitHub `/user`, commit and PR GETs | Before submission, both existing commits map author/committer to Stevemeg; authenticated account Stevemeg; PR open/unmerged, original head matches expected, main baseline preserved. No co-author/generated trailers or bot identities. Commits are unsigned, not cryptographically Verified. Repeat effective identity before commit and inspect new remote metadata/full messages after push; report definitive new SHA in handoff. |

PowerShell diagram commands executed (installed Chrome, no screenshot fabrication):

```powershell
$diagramConfig = Join-Path $env:TEMP 'repovox-puppeteer.json'
@{ executablePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe' } | ConvertTo-Json | Set-Content -LiteralPath $diagramConfig -Encoding ascii
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/overview.md -o "$env:TEMP/repovox-revision-architecture.svg"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/overview.md -o "$env:TEMP/repovox-revision-architecture.png"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/data-model.md -o "$env:TEMP/repovox-revision-data.svg"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/data-model.md -o "$env:TEMP/repovox-revision-data.png"
```

Failures corrected during revision: an initial doc check found a broken `research-and-training` anchor after the cost document replacement; corrected to `research-and-specialization-budget`, then checker passed. Two exploratory reads used incorrect ADR filenames; actual paths discovered with `rg --files`, then read. A Python default Windows encoding read failed on UTF-8 punctuation; subsequent edits use explicit UTF-8. Diff inspection also found old Unicode-sensitive PRD replacements had missed N-03/N-05; those rows were replaced by ID and checked for consistent 35min/budget policy. Diagram preview was too crowded; production and research boundaries separated and re-rendered. These are authoring corrections, not application failures.

Limits: deterministic contracts cannot establish semantic entailment/security/latency. No application, tenant RLS, sandbox, GPU fit/throughput, local model evaluation, fine-tuning, TTS synthesis, video encoding, staging/load/restore/security or production tests ran. All usage/timings/weight digests in examples are explicitly synthetic. Prices distinguish published lists from estimates; rights, region/budget and independent human review remain decisions, not hidden approvals. No service deployed, paid account created or resource provisioned.

## Mandatory revision self-audit

Complete here means Phase 0 design/documentation deliverable complete; implementation/evaluation results are deliberately future gates.

| Request | Status | File evidence |
| --- | --- | --- |
| 1 specialized model/self-host production policy | Complete | [PRD F-12/13](../product/prd.md), [ADR-005](../adr/0005-provider-and-render-boundaries.md), [AGENTS](../../AGENTS.md) |
| 2 inspect/preserve/change-impact | Complete | [Impact matrix](../ai/change-impact.md), historical 108-reference inventory, prior verification retained |
| 3 Director boundary/input/output/resources/licensing | Complete | [Director](../ai/director-architecture.md), [strict schema](../ai/director.schema.json) |
| 4 three official open-weight candidates/ranked baseline | Complete | [Model selection](../ai/model-selection.md), research source pins; footprint estimates clearly unmeasured |
| 5 baseline/dataset/PEFT/evaluate/release strategy | Complete | [Training stages A-E](../ai/training-strategy.md), [ADR-007](../adr/0007-model-promotion.md) |
| 6 evaluation negatives/held-out/numerical trust gates | Complete | [Evaluation plan](../ai/evaluation-plan.md), N-01 retained, human versus model judging separated |
| 7 self-host TTS alternatives/voice/timing | Complete | [Speech](../ai/speech-strategy.md), audio sample/voice fields in [artifact schema](../architecture/artifact.schema.json) |
| 8 six workload roles/three hosting strategies/GPU controls | Complete | [Deployment](../operations/deployment.md), [overview/diagrams](../architecture/overview.md), [reliability](../operations/reliability.md), ADR-004/008 |
| 9 self-host costs/scenarios/break-even/tests | Complete | [Cost model](../operations/cost-model.md), cost-inputs.json, [calculator](../../tools/cost_model.py), [tests](../../tools/test_cost_model.py) |
| 10 model metadata/cache/usage/recovery/contracts | Complete | [Pipeline](../architecture/pipeline.md), [data model](../architecture/data-model.md), schema v2 and [synthetic examples](../architecture/examples/pipeline.json) |
| 11 product/roadmap/deployed multi-user milestone | Complete | [Roadmap phases 0-8](roadmap.md), [README](../../README.md), F-01-13/N-01-08 trace matrix |
| 12 updated ADR-004/005 and model/eval/GPU ADRs | Complete | [ADR index](../adr/README.md), ADR-006/007/008; 001-003 preserved and adjusted |
| 13 security/privacy extension and no-code-execution policy | Complete | [S-01-22 / SEC-A-H](../security/threat-model.md), private inference and isolated research roles |
| 14 sole contributor/no history rewrite | Complete design and pre-commit audit | AGENTS policy, identity commands and existing commit association above; final remote commit audit reported in handoff |
| 15 same PR #1, no replacement/no merge | Submission step | This record targets existing PR; final response confirms pushed head/updated body and unmerged state after GitHub readback |
| 16 documentation/schema/cost/diagrams verification | Complete | Executed command table above; no GPU/training/deployment claims |

Original Phase 0 requirements remain: public GitHub/Python/JS/TS/dev audience/3-5min/720p; auth/dashboard/progress/playback/download/history; excluded private repos/documents/avatars/teams/editor/advanced billing; all durable owner entities, PostgreSQL/outbox/fences/retries/cancellation/cleanup, verified source provenance and qualified uncertainty; secure untrusted acquisition, CI promotion/migrations/rollback/monitoring/incident/restore/retention. Evidence is in PRD, pipeline, data model, security and operations, linked above. No valid work discarded or application implementation introduced.

## Outstanding approval and evidence

[Owner decisions](roadmap.md#owner-decisions-before-implementationprovisioning): base/voice/data licenses and rights, provisional us-east-1/GPU quote/availability/standby, proposed $2,000 monthly production plus separate $2,500 research pilot budget, revised unmeasured warm p95 <=35min, retention/takedown, domain/on-call, independent human review appointments and truthful launch decision if specialization fails. The owner has decided the self-host strategy; provisional asset/hosting details still require later approval. No decision here authorizes external AI evaluation or paid training.
