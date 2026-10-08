# Phase 0 targeted remediation verification

2026-10-08. Remediates independent FAIL findings R0-01/R0-02/R0-03 against `5bd559234eb50a8e151d9ba73e40ebd243dbc23f`. Work stays on `phase0/foundation`, existing [PR #1](https://github.com/Stevemeg/RepoVox/pull/1), targeting main. Phase 0 is unapproved until independent re-review; no merge or next-phase work. This is the current check record; [earlier revision record](phase0-revision-verification.md) retains historical execution evidence.

## Finding resolutions

| Finding | Resolution and exact evidence | Status |
| --- | --- | --- |
| R0-01 | [Director contract](../ai/director-architecture.md#stage-contracts-and-deterministic-assembly), [stage-specific schemas](../ai/director.schema.json), [14-stage pipeline](../architecture/pipeline.md), [artifact schema](../architecture/artifact.schema.json), [valid examples](../architecture/examples/pipeline.json), [chunk persistence](../architecture/data-model.md#director-chunk-persistence-and-resume), [ADR-002](../adr/0002-durable-jobs.md), [ADR-005](../adr/0005-provider-and-render-boundaries.md) and [contract tests](../../tools/test_director_contracts.py). | Complete at documentation level; runtime remains future work. |
| R0-02 | [Pre-baseline corpus/gold freeze and Phase 3 gates](../ai/evaluation-plan.md#evaluation-corpus-preparation-and-freeze), [Stages A/B/D](../ai/training-strategy.md), [phase dependencies](roadmap.md#implementation-phases), [ADR-007](../adr/0007-model-promotion.md), [calibration exclusions](../ai/model-selection.md). | Complete design; no corpus/reviewer/benchmark exists. |
| R0-03 | [Labor/corpus/scaling formulas](../operations/cost-model.md#research-and-specialization-budget), [inputs](../operations/cost-inputs.json), [calculator](../../tools/cost_model.py), [cost tests](../../tools/test_cost_model.py), [revised owner budget proposals](roadmap.md#owner-decisions-before-implementationprovisioning). | Complete arithmetic design; rates/times unmeasured. |

Stage 10 model responses use `stage10_chunk`, with two assigned topics each; final deterministic output is `stage10_output`. It owns scenes, safe visual instructions and locked claim citation/status mappings. Stage 11 uses `stage11_chunk`, pinned to the exact persisted storyboard digest; final output is `stage11_output` with narration only. Three complete partial-topic chunks/stage are validated and sealed immutably, then assembled without inference in fixed scene order. Final artifact publication remains one fenced atomic stage pointer. Wrong-stage/missing/duplicate/unsafe data fail instead of being repaired by silent renaming.

Retries reuse completed chunks in the same job and request only missing work after old execution stops. Durable counters cap each stage at three calls/attempt and four physical calls across two attempts, including one shared failure/repair allowance; <=360 seconds/attempt, <=180/call. Per-request <=12,288 prompt/4,096 output/16,384 context; all calls share <=120k prompt/12k output/1,200 GPU-seconds/job. Claim/evidence/uncertainty survive assembly; reference equality does not establish semantic entailment. Pending operation intents use logical chunk keys before a completed-chunk FK can exist. No paid fallback.

Correct sequence: Phase 2 secure analysis plus independently rights-reviewed evaluation collection, source-based gold, independent human review, hidden fixture preparation, frozen family splits/access/contamination manifests -> Phase 3 EVAL-ENTRY then registered unchanged-base benchmark/EVAL-EXIT -> Phase 4 separate training-data collection -> Phase 5 specialization and registered comparative evaluation -> Phases 6/7 actual TTS/render/staging gates -> Phase 8 deployed SaaS. Both EVAL_DEV and EVAL_TEST families/descendants are excluded from training/calibration. Failed held-out tests require a newly prepared untouched test version before another promotion attempt. ChatGPT's technical audit is distinct from human gold/output review. N-01 trust thresholds are retained.

## Reproducible cost outcomes

| Training examples | Training preparation hours | Training preparation imputed labor | Initial research cash | Initial research imputed labor | Combined initial estimate |
| --- | --- | --- | --- | --- | --- |
| 100 | 98.83 | $2,143.33 | $195.04 | $14,150.00 | $14,345.04 |
| 500 | 395.50 | $8,076.67 | $196.32 | $20,083.33 | $20,279.65 |
| 1,000 | 766.33 | $15,493.33 | $197.92 | $27,500.00 | $27,697.92 |

Independent evaluation gold preparation alone: 467 hours/$10,306.67 imputed labor and $3.76 CPU cash; protected held-out portion 367.33h/$8,113.33/$2.92 (60 families, 100 variants, ten hidden within the 60). New base/candidate output scoring costs another $1,700/cycle; included once in initial totals, not confused with gold preparation. Initial GPU allowance is 96 training + 24 evaluation hours, $190.80 cash. Monthly storage excluded from initial totals. Ten/20/40-minute drafting sensitivities keep source verification, rights/provenance and independent review time intact. None are measured annotation speeds.

Optional quarterly 100-example research cycle allocates $1,347.76/month including recurring labor and storage; one-time independent corpus preparation is not charged again each quarter. Production-only 100/1,000/10,000-video estimates remain $1,596.96/$1,806.84/$4,965.60 monthly. No price/budget proposal authorizes spending; imputed labor is not a vendor bill. Human availability, rights complexity, throughput and GPU fit require later measurement.

## Commands and results

Executed from repository root:

```powershell
python tools/check_docs.py
python tools/cost_model.py --check
python -m unittest discover -s tools -p "test_*.py" -v
python tools/cost_model.py --json | Set-Content -LiteralPath "$env:TEMP/repovox-remediation-cost-results.json" -Encoding utf8
git diff --check
```

Results: schema/example/provenance/audio-frame checks PASS; all ten artifact kinds, 11 existing negative probes, stage-specific assembly/usage invariants, requirement trace IDs, exact job transition set, evaluation gate consistency, local links/anchors/tables/JSON and Git identity/trailer checks pass. Cost check reproduces production, dataset and sensitivity tables and preserves GPU busy/load/idle, capacity and economic-reference checks. Unit suite **32 PASS**: 17 Director tests plus 15 cost tests (nine preserved regression tests and six research tests). JSON output was parsed independently to inspect all three research sizes, corpus costs and recurring allocation.

Director tests cover valid Stage 10/11 chunks/final outputs, wrong-stage output/chunk rejection in both directions, missing claims in both stages, duplicate scenes/chunks, missing chunks, unsafe JSX/asset URL/FFmpeg fields, prohibited Stage 11 visuals, stable assembly under reversed delivery order without mutating sealed content, tampered manifest/storyboard digest, forged citations/status/unknown claims/topics, valid one-failure resume, excess replay calls, per-attempt duration and cumulative token/GPU caps. These are offline synthetic contract tests, not executed worker/GPU recovery tests.

Research tests cover dataset size/family scaling and capped independent-review floor, drafting-only sensitivity, independent corpus/scoring costs unchanged by training size, initial/recurring cash/labor separation, zero training/zero corpus, invalid negative/fractional/nonfinite/boolean counts, zero effort, invalid review fraction, hidden-family count and cadence. Existing cost regressions retain warm idle at zero jobs, capacity steps, busy/load/idle partition, utilization, workload units, reference exclusions and break-even feasibility.

Mermaid CLI 11.15.0 used installed Chrome via temporary Puppeteer config; SVG and PNG outputs remain outside Git. Exact render commands (run for both extensions):

```powershell
$diagramConfig = Join-Path $env:TEMP 'repovox-remediation-puppeteer.json'
@{ executablePath = 'C:\Program Files\Google\Chrome\Application\chrome.exe' } | ConvertTo-Json | Set-Content -LiteralPath $diagramConfig -Encoding ascii
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/overview.md -o "$env:TEMP/repovox-remediation-overview.svg"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/overview.md -o "$env:TEMP/repovox-remediation-overview.png"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/data-model.md -o "$env:TEMP/repovox-remediation-data.svg"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/architecture/data-model.md -o "$env:TEMP/repovox-remediation-data.png"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/ai/director-architecture.md -o "$env:TEMP/repovox-remediation-director.svg"
npx --yes --package @mermaid-js/mermaid-cli@11.15.0 mmdc -p $diagramConfig -i docs/ai/director-architecture.md -o "$env:TEMP/repovox-remediation-director.png"
```

All five diagrams rendered; PNGs inspected for readable nodes/arrows and clipping. Director assembly and optional completed-chunk relationships agree with prose; unchanged overview preserves separate self-hosted CPU/GPU/training boundaries; state diagram remains unchanged. No video render or source execution occurred.

One intermediate `git diff --check` detected trailing whitespace in `tools/check_docs.py`; corrected before submission. Windows CRLF-to-LF normalization notices were informational. No failed benchmarks/training/deployment tests are hidden: none were attempted. Link checks cover local references; no live external-price revalidation or security penetration test is claimed.

## Preservation and attribution

Compared working text against reviewed HEAD: PRD, threat model, architecture overview, deployment, reliability and AGENTS are preserved unchanged. The fourteen stages/job transition set, tenant RLS/composite FKs, evidence verification, source-execution prohibition, self-hosted Director/TTS, private inference/media delivery, security/operations/release gates and deployed multi-user goal remain requirements.

Before commit: inspected `git config --show-origin user.name`, `git config --show-origin user.email`, `git var GIT_AUTHOR_IDENT`, `git var GIT_COMMITTER_IDENT`, `git log --all --format="%H|%an|%ae|%cn|%ce%n%B"`. Configured author/committer: Stevemeg <konabharath2004@gmail.com>, unchanged global configuration. Authenticated GitHub API account and all four pre-remediation commit author/committer account associations are Stevemeg; full messages have no co-author/generated-by trailers. Commits are unsigned, not cryptographically verified. Submission SHA/push/PR state and post-commit attribution audit are reported in the final handoff and PR description. No bot or additional human Git identity is introduced.

## Outstanding risks and review boundary

Independent human reviewer remains unappointed; evaluation fixtures, annotation throughput, gold quality and rights are future gates. Base/voice/license review, GPU availability/fit/latency/cold start, region, retention, actual cash quotes, revised owner budgets and production capacity remain open decisions. Corpus preparation may dominate cost and need legal/adjudication effort beyond estimates. Schema validity/citations alone cannot prove factual entailment or model safety. Runtime RLS/recovery/inference/render/incident/restore tests remain later phases. No paid APIs, GPU procurement/provisioning, dataset collection, local benchmarks, training, application features or deployment occurred. Await independent Phase 0 re-review; stop here.
