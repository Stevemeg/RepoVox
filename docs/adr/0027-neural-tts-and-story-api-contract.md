# ADR-0027: Local neural voice, hosted-model sampling and the story API contract

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-20. Branch `feat/neural-tts-and-frontend-handoff`, stacked on
`feat/grounded-llm-narration` at `dbf4d9b`. Milestone 3 of the problem-to-solution track.
Related:

- [ADR-0025 engineering story](0025-problem-to-solution-engineering-story.md)
- [ADR-0026 grounded narration](0026-grounded-llm-narration-refiner.md)
- [ADR-0005 provider and render boundaries](0005-provider-and-render-boundaries.md)
- [frontend handoff](../development/frontend-handoff.md)
- [deployment guide](../operations/deployment-guide.md#optional-local-neural-voice)

Core migrations stay at `0004` (`rv.job_guard` and `rv.video_disabled` unchanged). The media
database stays at `m001`. Stages 1–9, `Settings.fail_closed`, `AGENTS.md` and `docs/ai/` are
unchanged. No model weights are downloaded anywhere. CI never installs the neural voice
package: it is an optional extra, and its tests use a stand-in module that returns synthetic
samples.

## Context

Milestone 2 left three gaps:

- **Temperature.** Hosted adapters always sent `temperature: 0`, which current Claude models
  (Opus 4.7 and later, Sonnet 5 and later) and OpenAI reasoning models reject with HTTP 400.
  Narration from those models always fell back.
- **Voice.** Narration could only use the operating-system voice (espeak-ng or Windows SAPI),
  although `narration.Synthesizer` was designed as a seam for a local neural voice.
- **Frontend contract.** The frontend had no typed way to read the verified story behind a
  walkthrough. Video metadata did not say which voice spoke, and it named the model refiner
  only when one ran.

## Decision

### 1. Sampling is sent only when configured

`REPOVOX_LLM_TEMPERATURE` (`0.0` to `1.0`, default unset) is added:

| Adapter | Temperature unset | Temperature set |
| --- | --- | --- |
| OpenAI-compatible, Anthropic | no `temperature` field in the request | that value |
| Ollama | `options.temperature: 0` | that value |

Ollama always pins sampling because a local model there has no reason to reject it.

### 2. Optional local neural voice (`repovox.media.speech`)

New settings, checked by a separate `tts_fail_closed` validator:

| Variable | Default | Rule |
| --- | --- | --- |
| `REPOVOX_TTS_PROVIDER` | `auto` | `auto`, `deterministic` or `kokoro_onnx` |
| `REPOVOX_TTS_MODEL_PATH` | unset | Absolute `.onnx` path; no `..`, NUL or control character |
| `REPOVOX_TTS_VOICES_PATH` | unset | Absolute `.bin` path; same rules |
| `REPOVOX_TTS_VOICE` | `af_heart` | `^[a-z0-9_-]{2,32}$` |
| `REPOVOX_TTS_SPEED` | `1.0` | `0.5` to `2.0` |

Setting only one path is refused, and `kokoro_onnx` without both paths is refused.

`KokoroOnnxSynthesizer` implements `narration.Synthesizer`:

- **Loading.** It imports `kokoro_onnx` only when it first speaks. The package is in the
  `neural-tts` extra, which CI, the images and a default `uv sync` do not install. It loads
  the model once per worker.
- **Converting.** The model's float samples are mixed to one channel, linearly resampled to
  exactly 24 000 Hz, clipped and stored as 16-bit PCM.
- **Checking.** Non-finite, non-numeric or empty samples fail with `speech_corrupt`. A
  sample rate outside 8–48 kHz fails with `speech_format_unsupported`. A segment over 120
  seconds fails with `speech_too_long`. The operating-system voices' checks still apply:
  silence and segments under 0.2 seconds fail with `speech_silent`.
- **Missing pieces.** Fixed `SpeechError` codes: `neural_tts_unavailable` (package),
  `neural_tts_files_missing`, `neural_tts_load_failed` and `neural_speech_failed`.

`voice_from_settings` chooses the voice when a stage first needs one:

| Provider | Voice used |
| --- | --- |
| `deterministic` | The operating-system voice |
| `auto` | The neural voice if its package and files load here; otherwise the operating-system voice |
| `kokoro_onnx` | The neural voice, or a `SpeechError` that fails the speech stage with that permanent code. It never quietly becomes another voice. |

Only Stages 12 and 15 ask for a voice. A voice that cannot load is not remembered, so a
fixed installation is picked up on the next attempt.

### 3. The voice is recorded by name

Stage 12 adds `voice.json` to its bundle: `tts_provider` (`deterministic`, `kokoro_onnx` or
`local`), `tts_engine` and `tts_voice`. These are names only, checked against
`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`, never a path. Stage 13 and 14 bundle validation accept
exactly that one optional member, so bundles written earlier still validate.

### 4. Video metadata and the story API (no migration)

- **Stage 14 metadata.** The walkthrough's `metadata.narration` is now always a
  `NarrationView`: refiner, provider, model, blueprint digest, scene counts, refined ids,
  fallback reason, rejection reasons and the three voice fields. For deterministic
  narration, provider is `deterministic`, model is null and no scene is refined. Architecture
  explainers get `metadata.narration` with the voice fields only.
- **Stored story.** `metadata.story` holds the bounded public `StoryView` of a story
  storyboard, in the existing `media_videos.metadata` jsonb column written by `mv.finish`.
- **`StoryView` (`repovox.media.story_view`).** It reuses the verifier's own artifact,
  claim, citation and mismatch models, so statuses and evidence types are exactly the
  verifier's. It replaces the source list with counts per role, keeps at most three
  citations per claim and clips quotes to 240 characters (`evidence_trimmed` says so), and
  carries fixed `status_labels`. A view over 512 KiB is withheld rather than truncated
  further.
- **Listings.** `MediaJobs._load` selects `metadata - 'story'`, so job listings are
  unchanged in shape and stay small.
- **New route.** `GET /v1/video-jobs/{job_id}/videos/{video_id}/story` returns
  `VideoStoryView` (`video_id`, `job_id`, `category`, `narration`, `story`). It uses the same
  tenant scope and visibility rules as the video route:

  | Request | Answer |
  | --- | --- |
  | Not signed in | `401` |
  | Another owner's or a missing video | `404 not_found` |
  | A video without a story | `404 story_not_available` |
  | A stored record that fails validation | `503 story_corrupt` |

- **Proxy.** The web proxy allowlist forwards the new route, and nothing else changed in
  `apps/web`.
- **Contract.** `packages/contracts/openapi.json` was regenerated. Every existing path and
  schema is byte-identical; one path and fifteen schemas are added.

## Consequences

- **Security.** No new network path: the neural voice runs in the media worker on
  operator-supplied files, and the story view carries only repository-relative paths,
  hashes, public permalinks and verified claim text. The route is read-only and
  owner-scoped. Repository strings in the view remain untrusted text, and the
  [frontend handoff](../development/frontend-handoff.md#3-ui-design-and-truthfulness-rules-non-negotiable)
  requires plain-text rendering.
- **Dependencies.** `uv.lock` gains the optional `neural-tts` resolution (kokoro-onnx 0.6.1,
  onnxruntime, numpy, phonemizer and their dependencies) as additions only. No existing
  package version changed. Installing the extra is an operator choice and is not audited by
  CI's `pip-audit`, which checks the installed default environment.
- **Rollback.** Revert the branch. Videos published by this branch keep `metadata.narration`
  and `metadata.story`, which older code ignores, and an older Stage 13 or 14 would refuse an
  in-flight speech bundle with `voice.json` explicitly. `REPOVOX_TTS_PROVIDER=deterministic`
  turns the neural voice off without a deploy.
- **Cost.** No paid service. Kokoro runs on the worker's CPU; its speed on a given host has
  not been measured here.
- **Limits.**
  - The neural voice has not been run against real Kokoro weights in this repository; the
    tests prove the integration contract, not voice quality.
  - Linear resampling is adequate for speech, not high fidelity.
  - Stories larger than the view limit are not served.
  - Voice-record names are only as descriptive as the engine allows.

## Evidence

`tests/unit/test_neural_tts_and_story_api.py` covers:

- **Settings:** fail-closed and voice-name validation.
- **Neural voice:** PCM conversion, resampling and channel mixing; corrupt, silent and
  oversized audio; a missing package, files or model; and voice selection for every
  provider, including that a demanded voice never falls back.
- **Pipeline:** names-only voice records through Stages 12–14, and a speech stage that
  fails permanently when a demanded voice is absent.
- **Story view:** statuses and citations preserved, trimming and the size limit.
- **API:** the story route's success, cross-tenant, unauthenticated, missing, no-story and
  corrupt cases; the listing query without the story; and parity between the application
  and the frozen OpenAPI contract.

`tests/unit/test_llm_refiner.py` asserts that hosted adapters omit `temperature` by default
and send it when configured. `tests/integration/test_media_jobs.py` checks the real
pipeline's walkthrough narration metadata, the story route and cross-tenant refusal.
`apps/web/tests/analysis-proxy.test.ts` checks that the proxy forwards the story route and
refuses look-alikes.
