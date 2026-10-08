# Delivery roadmap and phase gates

Proposed, 2026-10-08. Sole maintainer: Stevemeg; implementation assistant: Codex; independent validator: ChatGPT. Follow [AGENTS](../../AGENTS.md). Independent validation and owner authorization required between every phase. No phase implemented here beyond Phase 0 documents/checks.

## Implementation phases

| Phase | Scope and dependencies | Acceptance / exit conditions |
| --- | --- | --- |
| 0 Foundation (this PR) | Inspect/init empty repository; V1/architecture/pipeline/schemas/persistence/security/deployment/costs/roadmap | All required documents, cross-links/diagrams/examples/cost checks, attribution audit and review PR; independent validator accepts; owner signs product decisions. Stop, do not implement Phase 1. |
| 1 Local SaaS skeleton | Depends on Phase 0 accepted; Next.js/FastAPI boundaries, migrations, mock managed auth, owner authorization, local Postgres/Redis/S3 mocks | F-01, F-06/F-11 skeleton; two-tenant RLS/FK tests, durable job admission/outbox/stage state tests, no paid calls. Code/scaffold allowed only after authorization. |
| 2 Static repository intelligence | Phase 1; secure pinned acquisition, filtering, Tree-sitter/entrypoint graph, formal full artifact/provider input schemas and synthetic fixtures | F-02/03/04 static evidence groundwork; malicious repo/SSRF/resource/secret tests SEC-A/B/C, coverage/limits/execution-tripwire tests. Never run submitted code. Claims deterministic/qualified, README conflicts tested. |
| 3 Grounded AI/storytelling | Phase 2 evidence stable; provider adapters initially mocked; paid pilot evaluation only when owner authorizes credentials/budget/terms | F-04/05; sentence mapping, unsupported-claim rejection, prompt-injection tests, ≥20 fixture human accuracy audit N-01; budget/unknown-provider-outcome tests; terms/disclosure accepted. No automatic stronger model fallback. |
| 4 Narrated video and delivery | Phase 3; TTS adapter, trusted Remotion templates, FFmpeg probe, captions/sidecar, private objects and signed metered range gateway | F-07/08/09/10; real audio/media target tests, six visual checks N-08, Chromium sandbox+egress tests, grant replay/byte quota races and revocation, cancel/retry/deletion tests. Actual unit costs/timings recorded. |
| 5 Staging production hardening | Phases 1–4 stable; owner-approved AWS account/budget/domain/region then infrastructure-as-code, CI promotion, managed auth/DB/Redis/private storage | All SEC suites, ≥100 supported runs ≥95% success, p95 latency at bounded admitted load, backup/PITR/restore RPO/RTO, migration/rollback/failure injection, alerts/secret/license scans, pricing calculator and worst-case budget validation. No production claim until evidence exists. |
| 6 Controlled production launch | Phase 5 independent validation, owner operational/legal/product sign-off, real secrets and release promotion | Deployed HTTPS app with authenticated dashboard, real public-repo pipeline, approved paid model/TTS, 720p video/playback/download/history, evidence links/uncertainty, quota/metered delivery, alerts/on-call/backup/deletion/rollback. Live smoke tests and monitored pilot recorded. **Final deployed-production milestone**; only now may status say deployed, with remaining SLA/quality limits disclosed. |
| Later scale/product | Production observed demand and new approved phase | CDN/multi-region/autoscaling/private repos/teams/editor/billing considered individually with threat/cost/requirements reviews. 10k estimate is capacity planning, not authorized feature scope. |

No timelines invented; phases have dependencies and measurable exits, not calendar promises. Rework failed gate before proceeding. Separate validator decides pass; implementation self-audit is evidence, not approval.

## Requirements traceability

| Requirement | Design evidence | Implementation gate |
| --- | --- | --- |
| F-01 auth/dashboard | [Architecture](../architecture/overview.md), [ownership](../architecture/data-model.md), S-09/11 | Phase 1 isolation; Phase 5 managed-session tests |
| F-02 URL/SHA | [Pipeline 1–2](../architecture/pipeline.md#stage-contracts), S-01/04 | Phase 2 fixed-host/pinned-acquisition tests |
| F-03 supported analysis | Pipeline 3–5, [limits](../product/prd.md#supported-limitations) | Phase 2 grammars/coverage/error fixtures |
| F-04 grounding | Pipeline 6–9, [artifact examples](../architecture/examples/pipeline.json), S-06/07 | Phases 2–3 evidence/human audits |
| F-05 storyboard/narration | Pipeline 10–12 | Phase 3 sentence verification, Phase 4 audio timing |
| F-06 async/progress | [State/lease rules](../architecture/data-model.md), [recovery tests](../operations/reliability.md#recovery-acceptance-tests) | Phase 1/5 restart/Redis/duplicate tests |
| F-07 MP4 | Pipeline 12–14, N-08 | Phase 4 probe/playback/visual checks |
| F-08 history/delivery | Architecture API boundary, data model grants, S-10, [cost byte policy](../operations/cost-model.md#cost-protection) | Phase 4 byte/range/replay/expiry tests |
| F-09 cancel/retry | Data model transition table/fencing/reuse | Phase 4/5 cancel-completion race and unknown charges |
| F-10 deletion | [Retention](../operations/deployment.md#retention-and-deletion), S-14 | Phase 4 cleaner, Phase 5 restore suppression |
| F-11 quotas/usage | Cost policy + data model ledger | Phase 1 admission races, Phase 3 paid operations, Phase 4 delivery byte races |
| N-01 accuracy | Pipeline verdicts/limitations/human fixtures | Phase 3 independent accuracy sample |
| N-02 reliability | Reliability tests/alerts + data model recovery | Phase 5 ≥100 runs, success/availability instrumentation |
| N-03 latency | Data model timeouts and deployment capacity | Phase 5 bounded-load p95/queue/status measurements |
| N-04 security/privacy | [Threat controls/suite](../security/threat-model.md) | Phase 5 all suites + provider terms/disclosure |
| N-05 cost | [Reproducible model](../operations/cost-model.md) | Phase 3 metering, Phase 5 actual/worst-case validation |
| N-06 accessibility/usefulness | PRD evaluation criteria | Phase 4/5 keyboard/caption/WCAG/user trials |
| N-07 operations | Deployment and reliability runbooks | Phase 5 restore/alert/rollback drills |
| N-08 media | PRD codecs/timing/readability | Phase 4/5 media and sampled visual/audio tests |

## Owner decisions before implementation/provisioning

1. Approve proposed V1 English voice/templates, static-analysis limits, uncertainty labels, evidence sidecar and rejection behavior; these are **proposed**, not product-approved today.
2. Approve public-code provider disclosure/terms and region; exact model/voice selected after quality evaluation. If privacy/residency unsuitable, revise adapters/hosting, not bypass notice.
3. Approve $1,000/month pilot planning budget, finite allowlist/10-per-user quotas and global 100/month admission; no spend authorized by writing this estimate. Detailed infrastructure quote needed.
4. Approve 30-day video/intermediate, 90-day history, 24h raw source, 365-day minimal usage and 35-day backup retention; takedown/licensing policy and legal obligations reviewed.
5. Choose domain, incident alert channel/contact and operational coverage compatible with targets. Confirm Remotion licensing eligibility, Chromium sandbox hosting and metered-delivery UX.
6. Choose commercial pricing/cost allocation before any paid customer plan; advanced billing remains deferred. Approve later-phase implementation separately after validator acceptance.

These questions do not prevent reviewing the Phase 0 proposals. They prevent treating them as authorization for implementation/spending/production launch.
