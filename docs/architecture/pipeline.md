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

Exactly 14 ordered stages; durable IDs below also used in [data model](data-model.md#stage-attempts-and-timeouts). Steps 6/7 may share an implementation task while committing separate stage results. Repair inside 9/11 consumes the same job budgets and is metered.

| # / Stage key | Inputs and bounded work | Persisted output / gate |
| --- | --- | --- |
| 1 `validate` | Admission URL parser, fixed GitHub repo/HEAD metadata request; API timeout 10s | Canonical locator/public visibility/full commit SHA plus configuration. Invalid/private URL rejected; archive location constructed internally. |
| 2 `acquire` | Fixed HTTPS archive at pinned SHA; stream byte/time caps | SHA-bound source manifest/object hash. Extraction rejects symlinks/hard links/devices/absolute/parent paths, duplicates/case collisions, nested archives and overflow. No git checkout/hooks/submodules/LFS. |
| 3 `filter` | Bounded file inventory, content sniffing, explicit exclude lists | Manifest files with language/status/reason/bytes/hash and eligible coverage denominator. Ignore repo `.gitignore` instructions as policy; use own allowlist. |
| 4 `structure` | Tree-sitter plus safe declarative JSON/TOML/YAML readers with safe loaders | Symbols/import/declaration graph, dependency constraints vs locked versions, parse errors. Exclude parser error spans, config readers never instantiate arbitrary YAML tags. |
| 5 `entrypoints` | Static patterns: Python `__main__`, pyproject scripts, JS package entry/bin/scripts, framework route declarations | Ranked candidates with rule IDs/evidence; package scripts are read, never run. Multiple candidates preserved, selected scope explained. |
| 6 `infer` | Import/symbol graphs and bounded sanitized snippets to LLM adapter | Candidate modules/edges/claims, uncertainty and explicit coverage. External calls/dynamic resolutions labelled inferred. No tool browsing/function execution for model. |
| 7 `knowledge` | Candidate graph/claims, deterministic normalization | Project Knowledge Model (PKM), language/component scope, purpose candidates, entry points, limitations. Schema valid; not yet publishable. |
| 8 `evidence` | Source ranges from selected snapshot | Evidence catalog maps claim IDs to file/lines/hash/SHA/symbol/rule. Reject invented paths, changed SHA/ranges or redacted secret claims. |
| 9 `verify` | PKM/catalog + bounded independent review prompt | Verification ledger: checked rule, support verdict/status/reason. One bounded repair allowed; unsupported facts excluded; fail if six topic sections lack honest coverage. |
| 10 `storyboard` | Verified/qualified PKM, trusted scene types | Six topic sections, scene/claim/citation IDs, target timings and visual data only. No executable code/URLs/assets from model. |
| 11 `narration` | Storyboard and approved claims | Sentence/scene claim mappings, plain text, captions. Reverify new prose; one repair within budgets; 450–700 words is drafting guide, not guaranteed timing. |
| 12 `tts` | Sanitized narration, voice/provider/version | Per-scene audio checksums/durations and timing manifest. ≤6k cumulative billed chars incl repair. If total outside 180–300s, one budgeted narration/tts repair under same stage attempt, otherwise fail. No unbounded stretching/re-generation. |
| 13 `render` | Validated data, immutable audio, trusted template version | Local frames/scene chunks + render manifest, 1280×720/30fps; actual audio timings converted to contiguous frames. No network in Chromium; trusted launcher/container. |
| 14 `encode` | Scene outputs/audio/captions/citation index | FFmpeg MP4 + ffprobe quality record, checksums, private object and sidecar keys; publish only after probe, size/hash checks and durable transaction. Owner delivery through API. |

Final evidence review occurs before any TTS; media timing repair cannot introduce unchecked claims. TTS receives only narration, not source. Renderer receives redacted code excerpts and scene data, not repository archives. Source files never become remote assets or file paths for FFmpeg input. Media output is generated from trusted layout functions and local bounded audio.

## Intermediate artifact schemas

Each artifact has a common envelope: `schema_version`, `kind`, `owner_id`, `snapshot_id`, `commit_sha`, `pipeline_version`, `input_digest`, `payload`. Production persistence additionally supplies immutable body checksum/object pointer, creation time, producer version and ordered upstream artifact IDs ([data model](data-model.md)). Scope all cache keys to owner/snapshot; no cross-tenant sharing.

| Kind | Required payload and relationships |
| --- | --- |
| `source_manifest` | Canonical repository, archive checksum, per-file path/hash/bytes/language/status/reason, excluded totals, coverage numerator/denominator. Paths unique and safe. |
| `structure` | Symbol ID/path/range/kind; import/dependency edges with explicit `declared`, `resolved_static`, `unresolved` classification; entry candidates/rules and parse errors. |
| `knowledge` | Project scope, stack/modules/edges/entrypoint IDs, claims, limitations; every graph edge references claims, not free-floating facts. |
| `evidence` | Catalog `id`, snapshot SHA, path, inclusive line range, file hash, evidence kind, rule and redaction flag. Resolve against acquired manifest, never model-created URLs. |
| `verification` | Claim verdict/status, evidence IDs, verifier version/rule, entailment explanation, uncertainty, conflict IDs. Unsupported claim IDs remain for audit only. |
| `storyboard` | Six sections; ordered scenes ID/topic/type/title/target seconds/claim IDs/evidence IDs/data. Scene type allowlist: title, stack, architecture, flow, code, summary. |
| `narration` | Ordered scene sentences with text, `technical` flag, claim IDs and uncertainty label; plain caption text. No SSML supplied by model; trusted adapter escapes text. |
| `audio` | Provider/model/voice/settings, per-scene object key/hash/duration/char count; request operation IDs. Timing map used for captions and rendering. |
| `render_manifest` | Template version, width/height/fps, contiguous scene frame ranges, audio checksums, output keys/hashes. |
| `video` | MP4 object/hash/byte count, codecs/dimensions/fps/duration, sidecar/caption keys, probe checks, expiry. No signed URLs stored. |

Representative synthetic JSON for PKM and downstream contracts is in [pipeline.json](examples/pipeline.json); it describes a made-up demo, not RepoVox implementation. [JSON Schema](artifact.schema.json) checks envelope, evidence/claim statuses and downstream scene/narration/audio/video shape. It is a Phase 0 representative contract, not a complete production parser schema: richer structure/manifests and strict provider input schemas must be finalized in Phase 2 before external calls. [Documentation checker](../../tools/check_docs.py) enforces cross-artifact example relationships and rejects unsupported narration claims; production additionally needs source-byte entailment/coverage validation. No claim that schema validation proves accuracy.

## Model context and reproducibility

Rank entrypoints, central imports and representative code within a fixed context budget. Deterministic selection and omission ledger precede summarization; include provider tokenizer counts before send. Same snapshot/parser/selector versions yield same evidence inventory, but LLM/TTS output need not be byte-deterministic. Store prompt-template/model/voice versions, seed where supported, actual usage and response checksum. Model adapter treats source as quoted untrusted data under fixed system policy, has no tools, cannot change claim rules/tenant/budgets. Provider-retention terms are launch blockers. [Cost reservations](../operations/cost-model.md#cost-protection) govern all attempts.
