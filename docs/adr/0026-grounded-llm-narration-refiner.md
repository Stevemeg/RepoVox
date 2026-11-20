# ADR-0026: Grounded language-model narration refiner

Status: proposed; implementation output, not independently reviewed or accepted. Date:
2026-11-20. Branch `feat/grounded-llm-narration`, stacked on `feat/problem-to-solution-story`
at `f059157`. Milestone 2 of the problem-to-solution track. Related:
[ADR-0025 engineering story](0025-problem-to-solution-engineering-story.md),
[ADR-0005 provider and render boundaries](0005-provider-and-render-boundaries.md),
[ADR-0011 parser isolation](0011-parser-process-isolation.md),
[threat model](../security/threat-model.md),
[deployment guide](../operations/deployment-guide.md#optional-grounded-narration-model).

Core migrations stay at `0004` (`rv.job_guard` and `rv.video_disabled` unchanged). The media
database stays at `m001`. Stages 1–9, `Settings.fail_closed`, `AGENTS.md` and `docs/ai/` are
unchanged. The default narration is still the deterministic template. With the default
setting no HTTP client is created, and CI makes no network call: every provider test uses
`httpx.MockTransport`.

## Context

Milestone 1 narrates each storyboard sentence in fixed template wording, such as "The README
states the problem: …". The wording is exact and reproducible, but it reads like a report. A
language model could make it sound natural, but a model can also invent a technology, a file,
a benchmark or a problem, or turn an author's promise into a fact. ADR-0025 left a
`NarrativeRefiner` seam for this, and Stage 11 refused every narrator except the template
until wording could be checked claim by claim.

## Decision

### 1. Optional, fail-closed settings (`repovox.core.config`)

`Settings` gains five optional fields, validated by a separate `llm_fail_closed` validator so
`fail_closed` is untouched:

| Variable | Default | Rule |
| --- | --- | --- |
| `REPOVOX_LLM_PROVIDER` | `deterministic` | `deterministic`, `ollama`, `openai_compatible` or `anthropic` |
| `REPOVOX_LLM_MODEL` | unset | Required for every model provider; `[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}` |
| `REPOVOX_LLM_BASE_URL` | per provider | `https://`; `http://` only on `127.0.0.1`, `localhost` or `host.docker.internal`; no user info, query, fragment, wildcard or whitespace |
| `REPOVOX_LLM_API_KEY` | unset | `SecretStr`; required for `openai_compatible` and `anthropic`, never sent to Ollama |
| `REPOVOX_LLM_TIMEOUT_SECONDS` | `20` | `1` to `120` |

The default endpoints are `http://127.0.0.1:11434` (Ollama), `https://api.openai.com` and
`https://api.anthropic.com`. A base URL is validated even when the provider is
`deterministic`, so a mistyped value is refused rather than kept for later.

### 2. Provider adapters (`repovox.media.llm_provider`)

Each adapter makes one `httpx` request per storyboard with temperature 0 and no retries:

- `OllamaProvider`: `POST /api/chat` with `stream: false`, `format: "json"`.
- `OpenAICompatibleProvider`: `POST /v1/chat/completions` with `response_format:
  {"type": "json_object"}`.
- `AnthropicProvider`: `POST /v1/messages` with `anthropic-version: 2023-06-01`. It reads
  only `text` blocks and requires `stop_reason` `end_turn` or `stop_sequence`.

Every request has the same bounds:

- Redirects are refused, and proxy, certificate and netrc environment variables are ignored.
- TLS uses the default system context.
- Connect time is bounded at 5 seconds, and read and total time by the configured timeout.
- Responses over 1 MiB are refused.

Timeouts, transport errors, non-2xx statuses, oversized or malformed bodies and incomplete
answers all raise `LLMProviderError` with a fixed code (`llm_timeout`, `llm_http_status`,
`llm_malformed_json`, …). The key is read only while one header is built. It never appears
in a repr, an error, a log, a stage summary or an artifact.

### 3. What the model sees: the verified blueprint only (`repovox.media.refiner`)

The refiner runs in the media worker at Stage 10, after `verify_story`. The parser sandbox is
unchanged and still has no network. The model receives one canonical JSON blueprint with:

- the repository, the 12-character commit and the problem sufficiency;
- per scene: its id, kind, title and character limit;
- per planned sentence: its draft wording and the verified claims it cites (id, text,
  evidence type, status, source location, file paths, proof kind).

Evidence quotes, source files, README bytes and the archive are never sent. The system prompt
says the blueprint is data and never instructions. It asks the model to add no fact, keep
every attribution and caveat, never say a test ran, and state an undocumented problem as
undocumented. It requires `{"scenes": {"<scene_id>": ["<sentence>", …]}}` with exactly one
string per planned sentence. The answer is per sentence, not one paragraph per scene,
because claims, evidence ids and uncertainty labels are attached to each sentence and must
stay aligned with the wording.

### 4. Claim-by-claim grounding check (`verify_refined_scene`)

The check is deterministic. Each refined sentence is compared only with its own draft, the
claims it cites, and the repository name and commit. A scene is refused when any sentence
fails one of these checks:

| Check | Refused when | Reason codes |
| --- | --- | --- |
| Entities | a file path, backticked or code-shaped symbol, number (digits, number words, `3x`, `%`), URL, technology (the extractor's list plus a wider list such as Kubernetes, Docker, AWS and GraphQL) or mid-sentence proper noun is absent from that evidence | `unsupported_path`, `unsupported_symbol`, `unsupported_number`, `unsupported_url`, `unsupported_technology`, `unsupported_entity` |
| Attribution | a `DOCUMENTATION_ONLY` or author-stated sentence has no attribution or uncertainty wording; an `UNVERIFIED` sentence has no uncertainty, negation or attribution | `missing_attribution` |
| Caveats | a caveat class in the draft (attribution, uncertainty, not-run, static) disappears, or the number of negations drops | `caveat_dropped` |
| Upgrades | new proof, guarantee, production or superlative wording; new "implemented", "verified" or "works" on a claim that is not `VERIFIED`; new speculation; new performance wording | `unsupported_assertion`, `epistemic_upgrade`, `speculation`, `unsupported_metric` |
| Tests | a sentence about tests or examples gains passed, ran, executed or succeeded wording | `test_execution_claimed` |
| Problem | the problem statement is insufficient and the problem scene drops the "does not document" statement, or any scene gains purpose wording, or the problem scene adds any new content word | `problem_statement_dropped`, `problem_invented` |
| Novelty | more than max(3, 30 %) new content words in a sentence | `novel_content` |
| Safety | control characters, non-ASCII after typographic normalisation, Markdown or code fences, prompt-injection echoes, empty text | `control_characters`, `non_ascii`, `markdown`, `prompt_injection`, `empty_text` |
| Pacing | a sentence outside 0.4–2× its draft's words, a scene outside 0.6–1.5×, longer than the caption limit, or the wrong sentence count | `length_out_of_bounds`, `too_long`, `sentence_count_mismatch`, `not_text` |

Phrases that the draft or cited claims already use are always allowed, so the deterministic
wording passes its own check. The tests confirm this on every scene of three repository
shapes.

### 5. Fail-closed fallback and provenance

The fallback is applied at three levels:

1. **Provider error or timeout.** Every scene keeps its deterministic wording, and
   `fallback_reason` records the code.
2. **Malformed answer.** Non-JSON, a wrong shape or an unknown scene id is treated the same
   way, with `response_malformed_json`, `response_schema` or `response_unknown_scene`.
3. **Refused or missing scene.** Only that scene keeps its deterministic wording, and
   `rejection_reasons[scene_id]` lists the exact sorted codes.

The storyboard stores `NarrationProvenance` in `story.narration` with these fields:

- `refiner`, `provider`, `model` and `blueprint_sha256`;
- `scenes_total`, `scenes_refined`, `scenes_fallback` and `refined_scene_ids`;
- `fallback_reason` and `rejection_reasons`.

Its validator rejects inconsistent counts. The narrator name is `grounded-llm-refiner-1.0`.
The provenance is recorded in four places:

- the storyboard artifact itself, which Stage 11 re-checks;
- the Stage 10 summary and a structured `media_story_narration` log line;
- the published video's `metadata.narration` at Stage 14, which the video API returns
  (the `m001` schema stores stage summaries only for Stages 14 and 15);
- the local render manifest, with `model_inference: grounded-narration-refinement`.

A fallback is therefore never silent. The provenance never records secrets, model text or
repository text.

A deterministic storyboard has no `narration` key and serializes byte for byte as before.

### 6. Stage 11 re-verification without a model

Stage 11 still re-extracts the archive, re-verifies the story and every citation, and checks
the analysis digest, scene order, evidence ids, labels and speech text. For a story
storyboard, it then checks the narrator:

| Narrator | Stage 11 requires |
| --- | --- |
| Deterministic | no provenance and exact reproducibility, as before |
| Grounded | provenance whose blueprint digest and scene count match a re-planned story; each refined scene passes `verify_refined_scene` again; rebuilding with `RecordedNarration` (stored wording for refined scenes, template wording elsewhere) gives exactly the stored storyboard |
| Any other | refused with `narrator_unsupported` |

A grounded storyboard fails with these codes:

- `narration_not_grounded` for wording that fails the check;
- `storyboard_not_reproducible` for any change to a fallback scene, a claim, a row or an id;
- `narration_provenance_invalid` for forged provenance.

Stages 12–14 speak and caption only the script that Stage 11 approved, as before.

### 7. Worker placement

`MediaWorker` takes a `refiner`, and `main()` builds it with `refiner_from_settings`. The
provider call runs in a helper thread. The worker thread keeps calling the lease checkpoint
every half second, so the 60-second media lease survives a 120-second timeout. A lost lease
raises `Lost` at once, and the abandoned request ends at its own timeout.

## Consequences

- **Security.** Untrusted repository text still reaches a model only as verified,
  display-sanitized claim text in a blueprint, and only outside the sandbox. A model's answer
  is data: it is parsed as JSON and refused unless every scene passes the check. It cannot set
  a status, claim, label, scene or diagram element. Hosted providers send the blueprint to a
  third party, so an operator must choose them deliberately and accept that provider's terms
  ([AGENTS.md model policy](../../AGENTS.md#model-policy)). The self-hosted Ollama path keeps
  the blueprint on the host.
- **Migrations and rollback.** No schema change. `story.narration` is an optional field, so
  storyboards written before this change still validate. If this branch is reverted, a stored
  grounded storyboard is refused by the Milestone 1 Stage 11 with `invalid_storyboard`, and
  the job ends with an explicit error, never a silent publication. Setting
  `REPOVOX_LLM_PROVIDER=deterministic` turns the feature off without a deploy.
- **Cost.** At most one model request per video job. Ollama has no per-call cost. Hosted
  providers bill the operator's account per request. The blueprint for the strong synthetic
  story is 8.1 kB plus a 1.7 kB system prompt, roughly 2.5 k input tokens, and its drafts are
  2.1 kB. The largest storyboards (eleven scenes of six sentences) stay below about 10 k input
  and 3 k output tokens, before any reasoning tokens a model adds. The deterministic default
  stays free.
- **Limits.**
  - The check is lexical and conservative. It refuses many acceptable paraphrases, which
    then keep the template wording.
  - It cannot prove that a fluent rewording made only of common English words keeps the
    exact meaning. The novelty budget and the caveat, negation and attribution rules narrow
    that gap but do not close it.
  - Proper nouns are checked only mid-sentence.
  - Current Claude models (Opus 4.7 and later, Sonnet 5 and later) and OpenAI reasoning models
    reject `temperature` with HTTP 400. That is recorded as `llm_http_status` and falls back,
    so those models need the sampling parameter removed before they can be used.
  - The command-line producer (`python -m repovox.media`) stays deterministic.

## Evidence

`tests/unit/test_llm_refiner.py` covers:

- **Settings:** fail-closed validation for every provider, endpoint scheme and timeout rule,
  and confirmation that the key never appears in a repr, a dump or an error.
- **Providers:** the documented request of each of the three adapters, and the fixed code for
  every failure class (timeout, connection, HTTP 500, redirect, malformed JSON, oversized,
  incomplete, wrong shape).
- **Fallback:** full fallback on provider errors and malformed answers; per-scene fallback
  with exact reasons.
- **Verifier:** adversarial rewrites (invented technologies, paths, functions, benchmarks,
  URLs and names; upgraded author statements; invented problems; claimed test runs; injection
  echoes; Markdown; pacing). Faithful rewrites and the deterministic baseline are accepted.
- **End to end:** a grounded rewording through Stages 10–13 for each provider, unchanged claim
  ids and labels, and Stage 11 refusing forged wording and provenance without a model.
- **Isolation:** the request carries only the blueprint, deterministic storyboards are
  byte-identical and open no HTTP client, and a lost lease stops while waiting.
- **Worker:** Stage 10 records provenance, Stage 11 accepts it, and Stage 14 keeps it with
  the published video's metadata.

Milestone 3 (local neural speech) plugs into `narration.Synthesizer` and is unaffected.
