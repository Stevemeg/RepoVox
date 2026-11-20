# ADR-0031: Neural voice, technical pronunciation and animated architecture video

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-20. Branch `feat/neural-voice-and-visual-architecture`, stacked on
`fix/github-sha-and-ml-weights` at `d9ce469`. Related:

- [ADR-0025 problem-to-solution story](0025-problem-to-solution-engineering-story.md)
- [ADR-0027 neural voice and story API](0027-neural-tts-and-story-api-contract.md)
- [deployment guide: optional local neural voice](../operations/deployment-guide.md#optional-local-neural-voice)
- [model policy](../../AGENTS.md#model-policy)

The following are unchanged:

- Stages 1–9 and the analysis artifact contract (`schema_version` `2.3`).
- Core migrations (`0004`) and the media database (`m001`), including every media stage
  deadline (speech 240 s, encode 180 s, architecture 600 s).
- `Settings.fail_closed`, `AGENTS.md` and `docs/ai/`.
- The storyboard and story schemas, Stage 11 grounding checks, captions and citations.

CI downloads no model and installs no neural package.

## Context

A 9-minute walkthrough of `Stevemeg/Synthetic-Data` showed three problems.

**Visuals.** The Architecture and Workflow scenes drew boxes in plain columns:
- a blocky 5×7 bitmap font;
- no grouping by system layer and no role or status marking;
- a 10-pixel white square for a workflow step;
- title paths cut off mid-word.

**Encoding.** The video failed `media_timeout` on the media worker's 1 CPU, because encoding
was given a fixed 170 s FFmpeg limit inside the 180 s encode deadline. Measured on a 9-minute
mix of 49 stills and 200 animated images at 720p30, on one thread:

| Preset | Encode | Verify (decode) | Size |
| --- | --- | --- | --- |
| `veryfast` | 224.0 s | 57.3 s | 1.5 MB |
| `superfast` | 173.4 s | 53.3 s | 1.8 MB |
| `ultrafast` | 87.6 s | 19.5 s | 2.6 MB |

At 4 threads `ultrafast` took 31.5 s to encode and 10.5 s to decode. Verification also decoded
the whole file twice: once to count frames and once to check it decodes.

**Speech.** The speech text read paths aloud as "frontend slash src slash …". Kokoro-82M v1.0
fp32 on this host's CPU ran at 1.2–1.8× realtime; int8 measured 1.5×, and parallel sentences
did not help. A 9-minute story therefore needs about 300–450 s of synthesis, more than the
frozen 240 s speech deadline allows on its own.

## Decision

### 1. Technical pronunciation, for speech input only (`media.pronunciation`)

`pronounce` is pure and deterministic and outputs printable ASCII only. What it says:

- **Acronyms** are spelled letter by letter: `API`, `SQL`, `UUID`, `HTTPS`, `GAN`, `VAE`,
  `MRI`, `LLM`, `UI`, `UX`, `CI/CD`.
- **Library names** get their usual spoken form: `PostgreSQL` → "Postgres Q L", `SQLite` →
  "S Q Lite", `PyTorch` → "Pie Torch", `NumPy` → "Num Pie", `README` → "Read me",
  `JSON` → "Jason", `YAML` → "Yammel", `OAuth` → "Oh Auth".
- **Identifiers** are read as words: `snake_case`, `camelCase` and `PascalCase`, and acronyms
  inside them (`getApiUrl`).
- **Versions** are read as numbers: `v0.6.0` → "version 0 point 6 point 0".
- **Paths** are read as words: `backend/app/services/inputs.py` → "inputs dot pie in backend
  app services". `file:line` adds ", line N".
- **Not read aloud:** commit hashes and links.
- **Punctuation** becomes clause breaks.

The letter A is written "Eh". espeak-ng, which is both the operating-system voice and Kokoro's
phonemizer, reads a lone "A" as the article: "Fast A P I" became /fæst ɐ piː aɪ/. "Eh" measured
/eɪ/ in every position. Bare capitals are not passed through as they are, because espeak reads
some as words: `VAE` → /viː/, `GAN` → /ɡæn/, `CLI` → /klaɪ/.

`speech.audio_text` feeds every voice: the deterministic, operating-system and Kokoro voices.
- **Source text.** It pronounces the caption when the approved spoken form is the caption's
  plain rewrite (`speakable`), so a path is read from the whole path. Otherwise it pronounces
  the spoken form, which carries the IR's role names.
- **Fallback.** It falls back to the approved spoken form when the result would exceed the
  600-character bound.

The storyboard, the Stage 11 script and its checks, captions, burned-in subtitles and every
citation keep the exact text.

### 2. Kokoro-82M setup, separate from CI

- **Download script.** `scripts/setup_kokoro_voice.sh` downloads `kokoro-v1.0.onnx` and
  `voices-v1.0.bin` from the official `thewh1teagle/kokoro-onnx` release `model-files-v1.0`
  into the git-ignored `.models/kokoro/`.
  - It checks the exact size the release publishes, plus a SHA-256 recorded from that
    release on 2026-11-20. The release publishes no digests.
  - It checks that the voices file is an `.npz` (ZIP) archive.
  - It is idempotent, and `--check` downloads nothing.
- **Licences.** kokoro-onnx is MIT and the weights are Apache-2.0. These upstream weights are
  used as published; RepoVox trains nothing.
- **Build argument.** `api.Dockerfile` gains `ARG INSTALL_NEURAL_TTS=false`, applied to both
  `uv sync` calls. `media-worker` builds from that same file, so no separate
  `media-worker.Dockerfile` is needed. With the default value every image builds as before.
- **Overlay.** `infrastructure/local/docker-compose.neural-tts.yml` changes only
  `media-worker`:
  - builds it with the extra;
  - mounts `.models/kokoro` read-only at `/models/kokoro`;
  - sets `REPOVOX_TTS_PROVIDER=kokoro_onnx`, the two paths, `af_heart`, speed `1.0` and
    `REPOVOX_TTS_THREADS=4`;
  - allocates 4 CPUs and 3 GiB;
  - inherits every other limit: read-only root, tmpfs, `pids_limit`, dropped capabilities,
    `no-new-privileges`.
- **Threads.** `KokoroOnnxSynthesizer.threads` opens one ONNX Runtime CPU session with that
  many intra-op threads, because the default counts every host core.

### 3. Speech within the frozen deadlines: a bounded cache and speaking ahead

`speech.SpeechCache` is an in-memory store of synthesized sentences, keyed by voice identity and
exact text:
- bounded in bytes (96 MiB) and least-recently-used first out;
- thread-safe and never persisted;
- a voice says the same text the same way, so a cached sentence is what the voice would say
  again.

The narration stage runs first, after its own Stage 11 checks have approved the script. Within
its own lease and its 360 s deadline, it speaks the approved sentences ahead into the worker's
cache for at most `REPOVOX_MEDIA_SPEECH_PREWARM_SECONDS` (240 s by default, at most 300 s).
- It does this only for a voice that is not the operating-system engine.
- A voice error stops the warm-up and leaves the error for the speech stage to report.

The speech stage and the architecture stage then reuse cached sentences. Every stage stays
bounded by its own lease and deadline; no deadline is extended. A deployment with several
media workers may run Stage 11 and Stage 12 in different processes, which only loses the
warm-up.

### 4. Layered, animated architecture frames (`media.diagram`, `media.raster`)

**Tiers.** A component's tier comes from what the IR already records: its kind, role and
declaring or cited path. There are four tiers, drawn top to bottom: client/frontend,
API/routes, core services, and ML/workers/data/external. Each card gets a role badge (`UI`,
`API`, `SVC`, `ML`, `DATA`, `EXT`). Tiers order the drawing only. A box still exists only for
an IR component and a line only for an IR connection.

**Layout.**
- Each boundary (source file or folder) is a labelled container inside its tier band.
- Cards follow the relationship direction and use the largest size that fits.
- Container labels sit on plates above the edges, so a line never crosses a name.
- When the bands do not fit, the existing `automatic` column layout is used, unchanged. The IR's
  own drawability check calls `automatic`, so discovery output does not change.
- The two reviewed fixed layouts are unchanged.

**Drawing.**
- Glyphs are smoothed with Scale2x at even scales.
- Rounded cards, rings and discs are anti-aliased by pixel coverage.
- Translucency uses per-channel lookup tables over strided byte slices, so a frame stays pure
  Python and deterministic on every host.
- Borders are solid for `VERIFIED` and dashed otherwise. A footer legend says so.

**Motion.**
- **Architecture overview.** The overview sentence reveals the tiers one by one.
- **Component sentences.** A spotlight glow rises on the narrated components while others
  dim, with a callout pill naming the role and the cited file and line.
- **Workflow steps.** Each relationship is drawn from source to target, then a glowing packet
  with a trail travels along it. A step bar (`STEP 2 OF 5 Source -> Target`) and a cited
  `file:line` badge accompany it.
- **Dedicated explainer.** It uses the same frames. Before, every line was animated, even
  lines where nothing moved. Now only relationship lines move. Component lines spotlight and
  hold, and other lines are one still image, capped at `EXPLAINER_LIMIT` animated images.

**Holding the last image.** A sentence's last image holds until the sentence ends, so an intro
costs a few images, not a sequence. `stages.sequence_entries` refuses gaps, extra images and
sequences longer than the sentence.

### 5. Encoding

- **Preset.** libx264 `ultrafast` at CRF 20. A 9-minute video then fits the 180 s encode
  deadline even on 1 CPU.
- **Pixel format.** Each unique image is converted to `yuv420p` before frame-rate duplication.
- **Verification.** The streams are read without decoding (`-count_packets`). One full decode,
  with `-progress`, then both proves the file decodes and counts its frames exactly.
- **Time limit.** Each FFmpeg and ffprobe call gets `encode_timeout(seconds)`, which is 170 s
  plus 30 s per minute of video, capped at 900 s. The three values are `Settings`
  (`REPOVOX_MEDIA_ENCODE_*`). The stage deadline still bounds the whole stage, so no DoS limit
  is weakened.

## Security and truthfulness

| Concern | Effect |
| --- | --- |
| Captions and citations | Unchanged. Only synthesis input is rewritten, and the tests prove that captions and the Stage 11 script are byte-identical. |
| Invented facts | None. Pronunciation only re-reads words already in the text. Tiers and badges come from IR fields and add no node or edge. |
| Model supply | No runtime download. The weights must match the recorded size and digest, are mounted read-only, and never enter Git or an image. |
| Resource limits | Stage deadlines, lease fencing, pids, read-only root and dropped capabilities are unchanged. Only the opt-in overlay raises `media-worker` CPU and memory. |
| Speech cache | Process memory only, bounded, keyed by voice and text. It holds already-approved narration and is never served or stored. |

## Consequences

- **Stage timing.** Long stories can be voiced by Kokoro: Stage 11 speaks ahead and Stage 12
  finishes the rest. A deployment slow enough that both together exceed their budgets still
  fails the speech stage with a fixed code, as before.
- **Encoding.** `ultrafast` files are about 1.7× larger (2.6 MB for 9 minutes) and are
  Constrained Baseline H.264, which every browser decodes.
- **The letter A.** The spoken form of an acronym containing A uses "Eh", which is never shown
  to the viewer.

## Rollback

Revert the commits. No migration, schema or stored artifact changes. Published videos stay
valid; new videos return to the previous frames, encoder and voice input. Remove the overlay
and `.models/` to drop the neural voice.

## Tests

`tests/unit/test_pronunciation_and_visual_arch.py` covers:

- every listed acronym and library;
- paths, identifiers, versions, hashes, links and pacing;
- ASCII-only, deterministic output;
- a recording neural voice that hears the pronunciation, while the Stage 11 script, captions
  and citations stay exact;
- one bounded ONNX Runtime session per thread setting;
- speaking ahead, with the speech stage reusing the cache and producing byte-identical output;
- tier classification;
- non-overlapping cards inside their containers and bands;
- reveal, spotlight and flow frames that actually differ;
- the animation budget;
- diagram scenes never drawn as text slides;
- sequence holding and gap refusal;
- encode-limit scaling and capping, and the Settings bounds;
- frame counting from a single decode;
- a real FFmpeg encode and decode of an animated sequence, skipped where FFmpeg is absent.
