# Delivery roadmap and phase gates

Revised proposal, 2026-10-08. Sole maintainer Stevemeg; implementation assistant Codex; independent validator ChatGPT. Follow [AGENTS](../../AGENTS.md). Phase 0 remains **unapproved**. No next-phase implementation, paid experiment, training run or provisioning is authorized by these proposals. Independent validation and owner authorization required between phases.

## Implementation phases

| Phase | Scope and dependencies | PASS gate; otherwise FAIL and rework |
| --- | --- | --- |
| 0 Revised foundation (this PR) | Preserve existing Phase 0; self-hosted Director/TTS/model research/training/evaluation/security/GPU/cost contracts | Documents, examples, diagrams, cost/unit/schema/attribution checks and change-impact audit pass; independent validator accepts revision and owner resolves phase-entry decisions. Stop here. |
| 1 Local SaaS and durable job foundation | Phase 0 accepted; Next.js/FastAPI, migrations, mock auth, owner isolation, Postgres/Redis/private storage mocks, quotas/outbox | F-01/06/11 skeleton; two-tenant RLS/composite-FK and admission/concurrency/idempotency/stage tests. No real GPU/API calls. |
| 2 Secure repository intelligence and independent evaluation preparation | Phase 1; pinned acquisition, Tree-sitter graphs/PKM/verifier plus rights-reviewed evaluation corpus preparation | F-02/03/04 and SEC-A/B/C PASS: acquisition/tripwire/SSRF/secrets/coverage, SHA/range/hash/README conflict and uncertainty checks. Never execute submitted code. Before first baseline benchmark, EVAL-ENTRY: independent source-based gold approved by appointed human reviewer, 20 development/60 held-out families including >=10 hidden, >=100 reviewed variants, frozen rights/splits/hashes/access/contamination manifests. No training collection yet. |
| 3 Baseline Director evaluation and grounded storyboard engine | Phase 2 PASS **including EVAL-ENTRY corpus freeze**; owner approves baseline weights/licenses/compute budget and fixed prompt/schema/engine/hardware. Benchmark only after independent fixture preparation. | EVAL-EXIT: unchanged base on registered held-out corpus, independent blinded human scoring, applicable N-01/text/graph/structured-chunk/visual-safety gates PASS, usage/VRAM/latency reports. Gold is not model-generated. Freeze control report for Phase 5; Phase 4 starts only after independent validation/owner authorization. Actual TTS/media launch gates remain Phase 6/7. |
| 4 Training-dataset preparation | Phase 3 EVAL-EXIT PASS; separate licensed curated family pools, source verification and independent sample review; proposed 100->500->1,000-example budgets | Training records all have rights/commit/attribution/verified labels. Disjoint from both evaluation pools/hidden derivatives, frozen training/validation/test assignments before Stage C, duplicate/privacy/deletion checks. Synthetic targets reviewed; permission absent = excluded. |
| 5 Model specialization, comparative evaluation and versioning | Phase 4; owner approves isolated GPU-hours budget, PEFT trials/checkpoint recovery | F-13: candidate passes all baseline hard gates and measurable improvement threshold versus unchanged base; no unacceptable accuracy/language/safety regression. Signed hashed base/adapter/dataset/engine/prompt release with rollback. Failed specialization blocks custom-trained release; owner decides revised base-only launch scope or more research, independent validation still required. Never claim base trained from scratch. |
| 6 Self-hosted inference/TTS and trusted media SaaS | Phases 1-5 gates; approved model release on private GPU, CPU Kokoro voice licensed, Remotion/FFmpeg, real managed auth/jobs/history/quotas/delivery | F-01/05/07/08/09/10/11/12/13; normal video uses no paid AI APIs; audio samples drive 180-300s/720p scene timing; six visual checks, narration/code pronunciation, renderability, signed range-byte quota/revocation, cancel/restart/replay and deletion tests. Record actual costs/usage and no unsafe output execution. |
| 7 Staging infrastructure and reliability verification | Phase 6 stable; owner explicitly approves region/budget/accounts/domain/resources then IaC, CI staging promotion | All SEC-A-H; >=100 supported staging jobs >=95% success; bounded-load warm p95 <=35min, API/session/isolation/monitoring, GPU cold/availability/OOM/abort/rollback tests; PITR/restore RPO<=1h/RTO<=4h, migration/queue loss/cancellation failure injection, incident alert drill and cost/idle research budgets. No provisioning happened in Phase 0. |
| 8 Real multi-user production deployment | Phase 7 independent PASS; owner operational/legal/product/sign-off and release promotion | Deployed HTTPS authenticated dashboard, actual public-repo evidence pipeline, promoted Director (or explicit approved base-only exception), self-hosted TTS and trusted 720p media, progress/playback/download/history, private metered delivery, quotas/tenant isolation, logs/traces/alerts/on-call, tested backups/deletion/rollback. Live smoke tests with >=2 isolated users and monitored pilot recorded. **Final deployed-production milestone**, not a notebook/CLI/local demo. |
| Later scale/features | Observed production demand and new owner-approved phase | GPU/CPU scaling/CDN/standby/multi-region/billing/private repositories/teams/editor considered separately. 10k cost scenario is planning, not scope authorization. |

No invented schedule. Phase dependencies are sequential, though bounded implementation inside an approved phase may be organized by owner. A failed gate stops promotion. Self-audit is not validator approval. Base-only fallback decision changes product claims and roadmap approval; it does not waive evidence, safety, SaaS or deployment gates.

## Requirements traceability

| Requirement | Design evidence | Implementation gate |
| --- | --- | --- |
| F-01 auth/dashboard | [Overview](../architecture/overview.md), [ownership](../architecture/data-model.md), S-09/11 | Phase 1 isolation; Phase 6/7 real sessions |
| F-02 URL/SHA | [Pipeline 1-2](../architecture/pipeline.md#stage-contracts), S-01/04 | Phase 2 pinned/host-bound acquisition |
| F-03 supported analysis | Pipeline 3-5, [PRD limits](../product/prd.md#supported-limitations) | Phase 2 grammar/coverage/error fixtures |
| F-04 grounding | Pipeline 6-9, [contracts](../architecture/artifact.schema.json), [evaluation](../ai/evaluation-plan.md) | Phases 2/3 independent entailment and human audits |
| F-05 storyboard/narration | [Director](../ai/director-architecture.md), [speech](../ai/speech-strategy.md) | Phase 3 schema/claim engine; Phase 6 actual speech timings |
| F-06 async/progress | Data model state/lease/outbox, [recovery](../operations/reliability.md#recovery-acceptance-tests) | Phases 1/6/7 duplicates/worker/Redis restarts |
| F-07 MP4 | Pipeline 12-14, N-08 | Phase 6/7 audio/probe/playback/renderability |
| F-08 history/delivery | Overview API boundary, grants, S-10, [cost byte policy](../operations/cost-model.md#cost-protection) | Phase 6/7 range/replay/quota/revocation |
| F-09 cancel/retry | Data model transitions/fences/replay | Phase 6/7 old inference stop/cancel-completion races |
| F-10 deletion | [Retention](../operations/deployment.md#retention-and-deletion), S-14/21 | Phase 4 training lineage; Phase 6/7 live cleaner/restore suppression |
| F-11 quotas/usage | Cost policy, model/job/infrastructure ledgers | Phase 1 admission; Phase 3/6 tokens/GPU; Phase 7 forecasts |
| F-12 self-hosted Director | Director/private gateway, [deployment](../operations/deployment.md), S-18/19 | Phase 3 baseline; Phase 6 normal generation without paid AI |
| F-13 specialization | [Training](../ai/training-strategy.md), [selection](../ai/model-selection.md), [ADR-007](../adr/0007-model-promotion.md) | Phases 4/5 provenance, base comparison and promotion |
| N-01 trust | Pipeline/verifier + evaluation thresholds | Phase 2 independent corpus/gold freeze; Phase 3 unchanged base; Phase 5 candidate; Phase 7 media/independent sample |
| N-02 reliability | State/recovery/alerts | Phase 7 >=100 runs; Phase 8 measured availability |
| N-03 latency | Director caps, deployment/warm capacity | Phase 3 measures; Phase 7 admitted-load p95/queue/cold start |
| N-04 security/privacy | [Threat model SEC-A-H](../security/threat-model.md#security-acceptance-suite) | Phase 7 all suites; training rights Phase 4/5 |
| N-05 costs | [Reproducible model](../operations/cost-model.md) | Phase 3 actual inference usage; Phase 7 quotes/idle/failed-job limits |
| N-06 accessibility/usefulness | PRD criteria | Phase 6/7 captions/keyboard/WCAG/developer trials |
| N-07 operations | Deployment/reliability runbooks | Phase 7 restore/incident/alerts/migration/model rollback |
| N-08 media | PRD F-07, speech alignment and trusted scenes | Phase 6/7 probes and six independent visual/audio samples |

## Owner decisions before implementation/provisioning

1. Approve V1 static scope, English voice/templates, evidence uncertainty/rejection limits and revised unmeasured warm p95 <=35min target. Initial requirements remain public GitHub Python/JS/TS, 3-5min narrated downloadable720pMP4 for developers.
2. Review actual base/software/voice license texts/notices and independently licensed dataset/adapter permissions; provisional Qwen2.5-Coder-14B + Kokoro are evaluation choices, not cleared deployment assets. No commercial voice rights assumed solely from model license.
3. Approve region (proposed us-east-1), GPU capacity/quote/data residency, one-host generation availability risk versus funded standby, private networking and Chromium sandbox viability.
4. Approve proposed $2,000/month pilot production reserve separately from research. Retire the prior flat $2,500 research allowance: budget the independently prepared evaluation corpus and 100/500/1,000-example dataset labor from the reproducible model before benchmarking/training. Proposed initial research reserves including imputed labor/20% contingency are $18,000/$25,000/$34,000 for those sizes; separate optional recurring research allocation. No spend authorized here. Quota global100/month/10user; actual quotes/throughput and annotation time may change budget. Decide pricing/margin before customer plans.
5. Approve retention: source24h, media/intermediates30d, history90d, usage365d, backups35d; dataset deletion/rights withdrawal and adapter retraining policy, takedown/attribution obligations.
6. Select domain, alert channel/incident contact and operational coverage; verify Remotion/FFmpeg licenses. If specialization fails, explicitly decide whether to revise launch to truthfully described base-only Director or continue research.
7. Appoint/approve independent human evaluation reviewers distinct from training-label preparation; ChatGPT is the technical validator and must not be counted as a human rater. Reviewer activity does not imply Git authorship.
8. Any external AI evaluation requires separately explicit approval, permitted data/terms and budget; not required for normal production. Authorize next phase only after independent validation; do not merge this PR without it.

These decisions do not block review of Phase 0 proposals; they block treating proposals as authority to implement, spend or launch.
