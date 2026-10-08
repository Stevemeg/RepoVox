# ADR-005: Self-hosted Director and speech, trusted visual templates

Status: proposed · Date: 2026-10-08

Context: quality/prices/terms change; model output cannot become executable scene code.

Decision revised: private self-hosted RepoVox Director and self-hosted TTS adapters with bounded schema/compute/operation records. Unchanged Qwen2.5-Coder-14B and Kokoro CPU speech are provisional baselines pending evaluation/licenses. Normal generation requires no paid third-party LLM/TTS API. External AI experiments require explicit owner approval, permitted data and terms. Trusted Remotion/FFmpeg only, no generated executable code or commands; Director cannot decide verified status.

Alternatives: paid APIs easier to operate but violate selected normal-production policy; SGLang/llama.cpp engines and ranked open-weight models considered; Piper speech alternative with separate license review. Generated renderer code too risky; FFmpeg-only slides less expressive. Release/quantization/adapter changes invalidate corresponding caches, never silent fallback.

Consequences: GPU idle/weights/registry/security, rights-aware dataset and comparative adapter promotion required. Baseline is not called custom-trained. Schema/entailment/speech/media/sandbox/license gates retained. Reversal requires explicit owner architecture-policy change, not economic pressure or outage convenience.

Evidence: [contracts](../architecture/pipeline.md), [cost/license](../operations/cost-model.md), [Remotion licensing](https://www.remotion.dev/docs/license/pricing).
