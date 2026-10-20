# Delivery roadmap and phase gates

Owner-authorized 2026-10-20 [independent cloud-retention preparation](../operations/cloud-retention-design.md)
adds architecture and offline synthetic tests only. It changes no EVAL-ENTRY
threshold/count, source-fact/scoring contract or accepted control-plane SQL.
Cloud deployment and real-pilot execution remain separately gated. See
[review evidence](cloud-retention-design-verification.md).

Current authority, 2026-10-12: owner accepted Phase 0 `e35d8ef8a8a53cb34e46271a9813b5332ea42c1f`
and Phase 1 `ec09b733ab3ceffe592ad96d07902b92596dfd1b`, then authorized Phase 2 static
analysis/evaluation preparation. PRs remain unmerged. The proposal below is preserved
historically; its old approval wording does not override this explicit authorization.
Phase 2 still requires independent technical validation and the actual EVAL-ENTRY
corpus freeze. The reviewer is PENDING OWNER APPOINTMENT; engineering fixtures and live
smokes do not count as gold. No merge, deployment, training or Phase 3 is authorized.

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

CP-01/CP-02 remediation is engineering-only: [ADR-0017](../adr/0017-pilot-control-plane-safety.md)
and the [control-plane verification](phase2ce-control-plane-verification.md) cover
durable execution fencing and approved source scope. Independent engineering review
and a separate owner execution decision remain prerequisites for any new real pilot.
No official EVAL-ENTRY count, acceptance threshold or Phase 3 gate changes.

Phase 2 engineering accepted at `b60ba548`; Phase 2B prepares the N-01/EVAL-ENTRY
corpus gate through [staged batches](../development/evaluation-batches.md).
[Readiness](../ai/evaluation-readiness.json) and [owner decisions](phase2b-decisions.md)
remain blocked on actual human/rights/authorship/storage prerequisites. No Phase 3
advancement, model benchmark or official freeze is implied by engineering tests.

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

Phase 2C-D is authorized additive evaluation engineering for F-02/F-03, N-01 and
N-04, stacked on accepted Phase 2C-C at `9557938`.
The [v2 evaluation contract](../development/evaluation-v2.md) and
[review handoff](phase2c-d-reviewer-handoff.md) cover independent source-only
annotations, exact matching, private custody and synthetic adversarial tests.
No new pilot, acquisition, database migration, official gate change or Phase 3
is authorized. Stop at the draft PR and independent evaluator review.

Phase 2C-C is separately authorized engineering remediation for F-02/F-03 and N-01:
[canonical contract and conservative parser/graph rules](../development/canonical-facts.md),
synthetic regressions and a draft stacked PR. Its scoped additive artifact-version
migration is owner-authorized for local synthetic tests only. Historical 2C-B
comparison results, partial references and official human-reviewed counts remain
unchanged. No new blind evaluation, corpus expansion or Phase 3 is authorized.

Phase 2C-A is a separately authorized [AI exploratory preparation](phase2c-a-verification.md)
track after accepted Phase 2B. Blind ChatGPT review is pending; no model experiment,
official dataset freeze, scaling, spending, merge or Phase 3 is authorized. The official
EVAL-ENTRY gates and Phase 2B decision register remain unchanged.

1. Approve V1 static scope, English voice/templates, evidence uncertainty/rejection limits and revised unmeasured warm p95 <=35min target. Initial requirements remain public GitHub Python/JS/TS, 3-5min narrated downloadable720pMP4 for developers.
2. Review actual base/software/voice license texts/notices and independently licensed dataset/adapter permissions; provisional Qwen2.5-Coder-14B + Kokoro are evaluation choices, not cleared deployment assets. No commercial voice rights assumed solely from model license.
3. Approve region (proposed us-east-1), GPU capacity/quote/data residency, one-host generation availability risk versus funded standby, private networking and Chromium sandbox viability.
4. Approve proposed $2,000/month pilot production reserve separately from research. Retire the prior flat $2,500 research allowance: budget the independently prepared evaluation corpus and 100/500/1,000-example dataset labor from the reproducible model before benchmarking/training. Proposed initial research reserves including imputed labor/20% contingency are $18,000/$25,000/$34,000 for those sizes; separate optional recurring research allocation. No spend authorized here. Quota global100/month/10user; actual quotes/throughput and annotation time may change budget. Decide pricing/margin before customer plans.
5. Approve retention: source24h, media/intermediates30d, history90d, usage365d, backups35d; dataset deletion/rights withdrawal and adapter retraining policy, takedown/attribution obligations.
6. Select domain, alert channel/incident contact and operational coverage; verify Remotion/FFmpeg licenses. If specialization fails, explicitly decide whether to revise launch to truthfully described base-only Director or continue research.
7. Appoint/approve independent human evaluation reviewers distinct from training-label preparation; ChatGPT is the technical validator and must not be counted as a human rater. Reviewer activity does not imply Git authorship.
8. Any external AI evaluation requires separately explicit approval, permitted data/terms and budget; not required for normal production. Authorize next phase only after independent validation; do not merge this PR without it.

These decisions do not block review of Phase 0 proposals; they block treating proposals as authority to implement, spend or launch.

The owner-authorized growing-custodian correction is tracked by
[ADR-0019](../adr/0019-growing-evaluation-custodian.md) and its
[independent-review handoff](custodian-lifecycle-verification.md). This closes an
engineering preparation gap only after review. [Official evidence requirements and
the fresh-attempt runbook](../development/phase2-official-evidence.md) preserve every
EVAL-ENTRY threshold, zero verified counts, pending human appointment and UNFROZEN
status. No real attempt, corpus freeze, merge, production or Phase 3 is implied.

The additive [execution-to-review authority](../adr/0020-post-execution-custody-authority.md)
and [offline protocol](../development/custodian-review.md) remain subject to independent
security/engineering review. Synthetic signed approvals are not real owner approvals,
source-only references or human gold. Execution closure never extends retention.

The [RV-09-01 source-cleanup correction](rv09-01-verification.md) eliminates
unregistered review scratch; final independent acceptance remains required before
any real execution. Official corpus counts and all freeze gates remain unchanged.
