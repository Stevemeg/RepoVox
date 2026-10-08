# Repository intelligence pipeline

Proposed, 2026-10-08. [PRD caps](../product/prd.md#supported-limitations) · [Job semantics](data-model.md) · [Threat model](../security/threat-model.md) · [Artifact examples](examples/pipeline.json)

## Invariants and evidence semantics

Never execute submitted repository code, install its dependencies, run tests, load plugins, import Python modules, transpile its TS or render its HTML. README, comments and strings are untrusted data, never instructions. The pinned snapshot is immutable per job; source evidence uses original UTF-8 line numbers (1-based inclusive), SHA-256 of original file bytes and commit SHA. Binary/invalid UTF-8 files are skipped with reasons. Redacted snippets keep original line numbers and record redaction ranges; original secret values never leave the parser boundary.

Claim statuses:

- `verified`: a narrowly phrased static fact supported by checked source/manifests. Parser evidence and deterministic rule support recorded; another model cannot upgrade unsupported text to fact.
- `inferred`: source suggests a relationship but static analysis cannot prove it (dynamic dispatch, selected architecture grouping). Supporting references and uncertainty reasons required; narration says “appears to”/“likely”, visuals show “inferred”.
- `documentation_only`: a documentation assertion with doc evidence; narration explicitly attributes it to documentation, never implementation. Cannot support runtime claims.
- `unsupported`: no adequate support, with an empty or insufficient evidence list and reason. Retained for audit but forbidden in narration/storyboard.

No confidence threshold alone confers verification. A file link is not proof: verifier checks range existence, hash, SHA, scope and whether cited content entails the narrowly worded claim. Source code presence supports “declares/imports/calls here”; it does not prove successful runtime execution or performance. Every technical sentence maps to claim IDs, including stack, diagram arrows and code explanations. Nontechnical connective text may have no claims; post-narration verification classifies sentences and rejects unmapped technical assertions. Evidence links use `https://github.com/{owner}/{repo}/blob/{sha}/{path}#Lx-Ly` with escaped path; deletion upstream can break links, so retained redacted sidecar states last verified time.

## Stage contracts

Exactly 14 ordered stages; durable IDs below also used in [data model](data-model.md#stage-attempts-and-timeouts). Steps 6/7 may share an implementation task while committing separate stage results. Repairs in 10/11 consume the same job budgets and are metered; stage 9 never delegates verification authority to Director.

| # / Stage key | Inputs and bounded work | Persisted output / gate |
| --- | --- | --- |
| 1 `validate` | Admission URL parser, fixed GitHub repo/HEAD metadata request; API timeout 10s | Canonical locator/public visibility/full commit SHA plus configuration. Invalid/private URL rejected; archive location constructed internally. |
| 2 `acquire` | Fixed HTTPS archive at pinned SHA; stream byte/time caps | SHA-bound source manifest/object hash. Extraction rejects symlinks/hard links/devices/absolute/parent paths, duplicates/case collisions, nested archives and overflow. No git checkout/hooks/submodules/LFS. |
| 3 `filter` | Bounded file inventory, content sniffing, explicit exclude lists | Manifest files with language/status/reason/bytes/hash and eligible coverage denominator. Ignore repo `.gitignore` instructions as policy; use own allowlist. |
| 4 `structure` | Tree-sitter plus safe declarative JSON/TOML/YAML readers with safe loaders | Symbols/import/declaration graph, dependency constraints vs locked versions, parse errors. Exclude parser error spans, config readers never instantiate arbitrary YAML tags. |
| 5 `entrypoints` | Static patterns: Python `__main__`, pyproject scripts, JS package entry/bin/scripts, framework route declarations | Ranked candidates with rule IDs/evidence; package scripts are read, never run. Multiple candidates preserved, selected scope explained. |
| 6 `infer` | Import/symbol graphs and deterministic static rules; no model verification authority | Candidate modules/edges/claims, uncertainty and explicit coverage. External calls/dynamic resolutions labelled inferred. No tool browsing/function execution for model. |
| 7 `knowledge` | Candidate graph/claims, deterministic normalization | Project Knowledge Model (PKM), language/component scope, purpose candidates, entry points, limitations. Schema valid; not yet publishable. |
| 8 `evidence` | Source ranges from selected snapshot | Evidence catalog maps claim IDs to file/lines/hash/SHA/symbol/rule. Reject invented paths, changed SHA/ranges or redacted secret claims. |
| 9 `verify` | PKM/catalog + independent deterministic source-evidence verification; later human audits | Verification ledger: checked rule, support verdict/status/reason. Return malformed candidates to analysis within attempt limits; unsupported facts excluded; fail if six topic sections lack honest coverage. |
| 10 `storyboard` | Locked PKM/evidence; three two-topic inputs, schema stage10_input | Calls return complete stage10_chunk objects, never narration. Validate/seal immutable chunks, deterministically assemble stage10_output, persist one storyboard payload with scenes, final visuals, scene citation bindings and assembly hashes. All six topics required. |
| 11 `narration` | Committed Stage 10 payload digest, same three topic groups and approved scene/claim subset, schema stage11_input | Calls return stage11_chunk sentence groups with claim/evidence/uncertainty. Reverify prose, assemble stage11_output, persist one narration payload with upstream storyboard digest/assembly hashes. No visual/citation-map changes. |
| 12 `tts` | Approved plain narration, pinned self-hosted Kokoro/voice/version | Sentence/scene audio checksums, exact sample durations and timing manifest. <=6k cumulative synthesis characters including retry. Total outside 180-300s fails timing gate; one bounded TTS settings/pronunciation retry within attempts permitted, no new Director text or backward stage transition. |
| 13 `render` | Validated data, immutable audio, trusted template version | Local frames/scene chunks + render manifest, 1280×720/30fps; actual audio timings converted to contiguous frames. No network in Chromium; trusted launcher/container. |
| 14 `encode` | Scene outputs/audio/captions/citation index | FFmpeg MP4 + ffprobe quality record, checksums, private object and sidecar keys; publish only after probe, size/hash checks and durable transaction. Owner delivery through API. |

Final evidence review occurs before any TTS; media timing repair cannot introduce unchecked claims. TTS receives only narration, not source. Renderer receives redacted code excerpts and scene data, not repository archives. Source files never become remote assets or file paths for FFmpeg input. Media output is generated from trusted layout functions and local bounded audio.

## Intermediate artifact schemas

Each artifact has a common envelope: `schema_version`, `kind`, `owner_id`, `snapshot_id`, `commit_sha`, `pipeline_version`, `input_digest`, `generation_metadata`, `payload`. Production persistence additionally supplies immutable body checksum/object pointer, creation time, producer version and ordered upstream artifact IDs ([data model](data-model.md)). Scope all cache keys to owner/snapshot; no cross-tenant sharing.

| Kind | Required payload and relationships |
| --- | --- |
| `source_manifest` | Canonical repository, archive checksum, per-file path/hash/bytes/language/status/reason, excluded totals, coverage numerator/denominator. Paths unique and safe. |
| `structure` | Symbol ID/path/range/kind; import/dependency edges with explicit `declared`, `resolved_static`, `unresolved` classification; entry candidates/rules and parse errors. |
| `knowledge` | Project scope, stack/modules/edges/entrypoint IDs, claims, limitations; every graph edge references claims, not free-floating facts. |
| `evidence` | Catalog `id`, snapshot SHA, path, inclusive line range, file hash, evidence kind, rule and redaction flag. Resolve against acquired manifest, never model-created URLs. |
| `verification` | Claim verdict/status, evidence IDs, verifier version/rule, entailment explanation, uncertainty, conflict IDs. Unsupported claim IDs remain for audit only. |
| `storyboard` | Stage 10 owns scenes, strict visual_instructions, citation_mappings with per-claim locked status/evidence bindings and three-chunk assembly manifest. Stage-specific model chunks are validated first; final output requires complete global coverage and one-to-one scene/visual/citation joins. |
| `narration` | Stage 11 owns ordered plain sentences with technical flag, claim IDs, evidence IDs and preserved uncertainty, exact storyboard_digest and three-chunk assembly manifest. One sentence may not mix claim statuses. No model SSML; no mutation of Stage 10. |
| `audio` | Self-hosted engine/model/voice/settings, per-scene object key/hash/duration/char count; request operation IDs. Timing map used for captions and rendering. |
| `render_manifest` | Template version, width/height/fps, contiguous scene frame ranges, audio checksums, output keys/hashes. |
| `video` | MP4 object/hash/byte count, codecs/dimensions/fps/duration, sidecar/caption keys, probe checks, expiry. No signed URLs stored. |

Representative synthetic JSON for PKM and downstream contracts is in [pipeline.json](examples/pipeline.json); it describes a made-up demo, not RepoVox implementation. [JSON Schema](artifact.schema.json) checks envelope, evidence/claim statuses and downstream scene/narration/audio/video shape. It includes strict stage-specific Director input/chunk/final-output and safe visual schemas, with separate cross-artifact semantic checks. Production must extend parser-specific rule/entailment validators before integration, retaining these safety constraints. [Director contracts](../ai/director.schema.json) define validated PKM/ledger input and storyboard/narration/visual/citation output; schema alone cannot prove source entailment. [Documentation checker](../../tools/check_docs.py) enforces example relationships and rejects unsafe instructions/unsupported claims. No claim that schema validation proves accuracy.

## Model context and reproducibility

Rank entrypoints, central imports and redacted evidence deterministically with omission records. Director receives only already verified/qualified facts; no raw archive or tools. Per request <=12,288 prompt + <=4,096 output within 16,384 total tokens; <=120k/12k aggregate per job including repair/replay. Initial typical workload 60k/6k over <=6 calls. A missing essential source range fails coverage rather than inventing a summary. Full rules in [Director architecture](../ai/director-architecture.md).

Schema-v2.1 envelopes require server-stamped generation metadata for storyboard/narration/audio; static analysis, render and video envelopes use null and retain upstream artifact pointers. Metadata: base ID/revision/license/weight source, base and served hashes, adapter/checkpoint ID+hash and dataset version (null for base-only), tokenizer digest, prompt/template/engine/quantization versions, input/output tokens, inference duration, GPU type/seconds, CPU seconds and structured validation status. Example hashes are labeled illustrative, not fetched weights or executed inference.

Model release is pinned at admission, immutable through job/retry. Cache key includes owner/SHA/upstream digests, release/base+served weight/adapter/dataset/tokenizer hashes, inference engine+quantization versions, prompt/grammar/voice/template and pipeline/config versions. Different versions never silently reuse old outputs; same committed validated result resumes downstream without inference. Seeds do not guarantee determinism. Usage ledger records complete and failed attempts, actual tokens/GPU occupancy/CPU seconds and host-level idle/load separately; research has a separate ledger and no customer prompts.

[Director assembly contract](../ai/director-architecture.md#stage-contracts-and-deterministic-assembly) fixes three two-topic chunks per stage; no whole-stage combined model response. Chunk bodies are immutable completed work, final stage pointers published only after all chunks and global validation. Resume sealed work without inference; request missing chunks only after old execution stops. Each stage has <=3 calls/attempt, <=4 calls across <=2 attempts and one quality repair across attempts, <=360s/attempt and <=180s/call. Each request independently <=12,288 prompt/4,096 output/16,384 context; all physical calls including failures/replay count against cumulative 120k/12k tokens and 1,200 GPU-seconds/job. Deterministic assembly has zero model calls. Budgets never reset on restart; insufficient budget fails safely. No paid fallback, backwards stage or partial-stage publication.

Audio sample counts drive timing, not character estimates. Trusted segmentation produces sentence IDs/captions and exact PCM duration, then contiguous 30fps scenes. TTS has no source access; optional forced alignment needs evaluation before word timestamps are claimed. [Speech strategy](../ai/speech-strategy.md) covers model/voice rights and timing repair.
