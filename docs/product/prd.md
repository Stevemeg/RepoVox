# V1 product requirements

Proposed for independent review, 2026-10-08; owner approval pending. This describes intended behavior, not implemented features. [Architecture](../architecture/overview.md) · [Roadmap/traceability](../delivery/roadmap.md)

## Product and journey

RepoVox helps software developers understand a project's purpose, stack, architecture and important execution flow. Sign in, submit a public GitHub URL, see the pinned commit and budget, start asynchronous generation, follow stages, then watch/download an explanatory MP4. History shows status, commit, citations and expiry. Evidence appears in the dashboard and downloadable JSON sidecar; video includes concise file/line citations and commit identifier.

English narration, one approved voice and fixed visual templates. Explain static implementation evidence, not tested runtime behavior, performance, vulnerabilities or comprehensive correctness. README statements are documentation assertions until corroborated by implementation.

## Functional requirements

| ID | Requirement | Acceptance condition for implementation |
| --- | --- | --- |
| F-01 | Authentication/dashboard | Anonymous users cannot create/read jobs. Expired sessions fail closed; logout clears server session. Dashboard contains only owner's projects. |
| F-02 | URL validation and commit pinning | Only `https://github.com/owner/repo` (optional `.git`, trailing slash); reject query, fragment, credentials, port, IP, tree/blob paths and alternate protocols. Resolve default-branch HEAD once; all artifacts use its full SHA. |
| F-03 | Python/JS/TS static analysis | Manifest records parsed/skipped/failed files, coverage, languages, imports and entry points. At least one supported non-test source file parses; no submitted code execution/install. |
| F-04 | Grounded understanding | All technical claims carry evidence where supported. Unverified statements labelled inferred/documentation-only or omitted. Insufficient coverage fails before video generation. |
| F-05 | Storyboard/narration | Include purpose, stack, architecture, important flow, important code and summary. Sentence-level claim links survive captions/sidecar. Actual self-hosted speech audio duration validates timing; Director emits safe data only. |
| F-06 | Asynchronous progress | Submit returns job ID without waiting for generation. Persisted ordered stages/retries/error codes survive API, worker and Redis restarts. No fabricated time-based percentage. |
| F-07 | Downloadable output | MP4/H.264 yuv420p, AAC, fast-start, 1280×720 at 30 fps; 180–300 seconds, ≤150 MiB, no missing audio/scenes. Probe/playback tests are launch gates. |
| F-08 | Playback/download/history | Owner-only expiring signed URLs with byte ranges. Paginated history displays SHA/status/error/expiry, renews URLs after authorization; no public objects. |
| F-09 | Cancel/retry | Cancel blocks new inference/TTS work and stages and terminates overdue active work. Retry creates a new job linked to prior job and reuses eligible committed results. Terminal history immutable. |
| F-10 | Deletion | Access revoked immediately; project/account live data removed within 24 hours, backups expire under policy. Display deletion outcome/notice. |
| F-11 | Quota/usage | Atomic reservation before admission, visible per-job usage, hard token/TTS/compute limits; same owner/idempotency key returns same job. Budget exhaustion never triggers expensive fallback. |
| F-12 | RepoVox Director/self-host policy | Normal video generation completes without paid third-party LLM/TTS APIs. Director input/output pass schemas and locked evidence semantics; no executable scene code. External AI evaluation only with explicit owner approval/data terms. |
| F-13 | Model specialization and release | Baseline and trained adapter meet comparative evaluation, licensing/rights and model release gates. Base-only has null adapter/dataset metadata and is never called custom-trained; failed specialization requires owner launch decision. |

## Supported limitations

These are normative launch caps; adjust only with coordinated review of security, costs and operations.

| Dimension | V1 behavior |
| --- | --- |
| Repository | Public GitHub, default branch only; no uploads, user refs, LFS payloads or submodules. Recheck visibility on new acquisitions. Distinct missing/private/rate-limit errors. |
| Acquisition | ≤100 MiB compressed, ≤250 MiB extracted, ≤10,000 regular files. Streaming bounds before extraction; overflow rejects rather than silently truncating. |
| Source | ≤1 MiB/file; ≤5,000 eligible supported source files; ≤100 MiB eligible source bytes. Oversized files skipped/disclosed; eligible total overflow rejects. Generated/vendor/minified/build/binary files excluded. |
| Coverage | ≥90% eligible supported source bytes parsed; error regions excluded from evidence. Below threshold `insufficient_evidence`. Unsupported-language coverage disclosed. At least one supported non-test source file. |
| Complexity | Monorepo dominant component may be selected with explicit scope disclosure. Reflection/dynamic dispatch/runtime imports/external services remain uncertain. No test execution or runtime traces. |
| Context | Aggregate ceilings 120k input / 12k output LLM tokens including attempts; no unbounded chunk summarization. Base estimate 60k/6k. ≤6,000 TTS characters including one repair pass. |
| Video | Six topics, 3–5 minutes, 720p/30fps, one English voice/template set. No repository remote assets/HTML/JS. Narrow scope visibly or fail if meaningful coverage cannot fit. |
| Admission | One active and ten queued jobs/user; two submissions/minute/user; global launch two analysis, two TTS, two render jobs and one active Director sequence per GPU (one GPU initially). Daily/monthly quotas in [cost policy](../operations/cost-model.md#cost-protection). |

Explicitly defer private repositories, arbitrary documents, AI avatars, team administration, custom editing and advanced billing. Also defer higher resolutions, multilingual voices, branch selection, web crawling, automatic benchmarks, native GitHub app/editor integrations. V1 has operator-assigned quotas/usage records, no subscriptions/payment integration.

## Nonfunctional requirements and success metrics

Targets are unmeasured proposals. Supported admitted-job cohort excludes deliberate rejection, owner cancellation and upstream repository removal; report excluded rates separately. No achieved SLA/benchmark claims.

| ID | Target | Measurement / acceptance |
| --- | --- | --- |
| N-01 | Technical trust | 100% technical narration sentences map to claims; 100% verified claims resolve SHA/path/range/hash. Independent audit of ≥20 diverse fixtures: ≥95% sampled claims correct, zero severe invented architecture/runtime assertions. |
| N-02 | Reliability | ≥95% supported jobs succeed across ≥100 staging runs; rolling 30-day production tracking. API objective 99.5% monthly. Recovery tests for duplicates, worker death and DB/Redis outages. |
| N-03 | Latency | Core API p95 <500 ms excluding auth/remote validation/signing; committed status visible <=5s. Warm generation p95 <=35 minutes including queue at bounded admitted load; 45-minute absolute deadline. Cold starts disclosed separately. Unmeasured proposal requiring owner approval. |
| N-04 | Security/privacy | Pass [security suite](../security/threat-model.md#security-acceptance-suite); zero cross-tenant reads, submitted-code execution or secrets in fixture payloads/logs/video. Processing/privacy notice before generation; no default external AI disclosure or customer-training reuse. |
| N-05 | Cost | Normal self-hosted videos fit approved monthly infrastructure and per-job token/GPU/CPU reservations. Meter failures, idle capacity and research separately; validate allocated economics before pricing. No requirement that GPU inference be cheaper than paid APIs, and no paid fallback. |
| N-06 | Usability/accessibility | Keyboard usable critical flows; WCAG 2.2 AA assessment, captions/sidecar. ≥80% of ten developer evaluators rate usefulness ≥4/5; identifiers in captions match narration. |
| N-07 | Operations/durability | Redacted structured logs/traces; restore drill DB RPO ≤1 hour, RTO ≤4 hours; retention/deletion/alerts tested. Redis rebuild loses no durable jobs. |
| N-08 | Video quality | Every successful fixture meets F-07; six representative videos visually checked for readable code/citations and unclipped text; intelligible narration. ≥95% history-to-playback action success in user trials. |

Model design, rights and evaluation: [Director](../ai/director-architecture.md), [training](../ai/training-strategy.md), [evaluation](../ai/evaluation-plan.md), [speech](../ai/speech-strategy.md). The revised 35-minute warm latency target reflects assumed local inference/render workload; it is unmeasured, requires owner approval and bounded-load admission, and includes queue time. Cold start separately disclosed within 45-minute deadline.

Pilot learning metrics (not launch guarantees): ≥60% admitted users finish a first video, ≥30% create a second within 30 days, measured after consented analytics launch. The [roadmap](../delivery/roadmap.md) defines gates and owner questions.
