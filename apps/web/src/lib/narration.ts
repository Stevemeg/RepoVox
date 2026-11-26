/*
 * How a video's narration was worded and voiced, stated only from its recorded provenance
 * (`metadata.narration`, ADR-0026 and ADR-0027; frontend handoff section 3, rule 5).
 *
 * Nothing here is assumed. A deterministic record says the template wording was used; a model
 * record names the provider and model and how many scenes kept the model's wording; a missing
 * record says provenance was not recorded. The voice is described from its own fields: a
 * Kokoro voice is a local neural voice, which is itself a model, so no sentence here ever
 * claims that no model of any kind was involved.
 */
import {
  normalizeNarration,
  normalizeVoice,
  type NarrationView,
  type VoiceView,
} from "./story-types";

export type WordingProvenance =
  | {
      kind: "template";
      refiner: string;
      scenesTotal: number;
    }
  | {
      kind: "model";
      refiner: string;
      provider: string;
      providerLabel: string;
      /** Hosted providers are third-party services the operator configured. */
      hosted: boolean;
      model: string | null;
      scenesTotal: number;
      scenesRefined: number;
      scenesFallback: number;
      fallbackReason: string | null;
      rejections: { scene: string; reasons: string[] }[];
    }
  | {
      /** An architecture explainer: voice-only record; explainers are never model-worded. */
      kind: "explainer";
    };

export type VoiceProvenance = {
  recorded: boolean;
  provider: string | null;
  engine: string | null;
  voice: string | null;
  /** A plain description of the provider, never a guess. */
  description: string;
};

export type Provenance = {
  /** False when the video carries no narration record at all. */
  recorded: boolean;
  wording: WordingProvenance | null;
  voice: VoiceProvenance | null;
};

const PROVIDERS: Record<string, { label: string; hosted: boolean }> = {
  ollama: { label: "Ollama, a self-hosted model server", hosted: false },
  openai_compatible: { label: "an OpenAI-compatible hosted API", hosted: true },
  anthropic: { label: "Anthropic's hosted API", hosted: true },
};

export function describeVoice(voice: VoiceView | null): VoiceProvenance | null {
  if (!voice) return null;
  const { tts_provider: provider, tts_engine: engine, tts_voice: name } = voice;
  const recorded = provider !== null || engine !== null || name !== null;
  let description: string;
  if (!recorded)
    description =
      "The voice was not recorded for this video: its speech was produced before RepoVox recorded which voice spoke.";
  else if (provider === "kokoro_onnx")
    description = "A local neural text-to-speech voice (Kokoro) running on the RepoVox host.";
  else if (provider === "deterministic")
    description = "The operating system's local speech synthesizer on the RepoVox host.";
  else if (provider === "local")
    description = "A local speech synthesizer on the RepoVox host.";
  else description = "A voice provider this version of RepoVox does not recognise.";
  return { recorded, provider, engine, voice: name, description };
}

function describeWording(record: NarrationView): WordingProvenance {
  if (record.provider === "deterministic")
    return { kind: "template", refiner: record.refiner, scenesTotal: record.scenes_total };
  const known = PROVIDERS[record.provider];
  return {
    kind: "model",
    refiner: record.refiner,
    provider: record.provider,
    providerLabel: known?.label ?? "a model provider this version of RepoVox does not recognise",
    // An unrecognised provider is treated like a hosted one: nothing is assumed to be local.
    hosted: known?.hosted ?? true,
    model: record.model,
    scenesTotal: record.scenes_total,
    scenesRefined: record.scenes_refined,
    scenesFallback: record.scenes_fallback,
    fallbackReason: record.fallback_reason,
    rejections: Object.entries(record.rejection_reasons)
      .filter(([, reasons]) => reasons.length > 0)
      .map(([scene, reasons]) => ({ scene, reasons }))
      .sort((a, b) => a.scene.localeCompare(b.scene)),
  };
}

/**
 * The provenance of one video. `fallback` is another record of the same video (the story
 * API's `narration`), used only when the video metadata has none.
 */
export function describeProvenance(
  category: string,
  metadataNarration: unknown,
  fallback?: NarrationView | null,
): Provenance {
  const narration = normalizeNarration(metadataNarration) ?? fallback ?? null;
  if (narration)
    return {
      recorded: true,
      wording: describeWording(narration),
      voice: describeVoice(normalizeVoice(narration)),
    };
  const voice = normalizeVoice(metadataNarration);
  if (voice)
    return {
      recorded: true,
      wording: category === "architecture" ? { kind: "explainer" } : null,
      voice: describeVoice(voice),
    };
  return { recorded: false, wording: null, voice: null };
}

/** "3 scenes", "1 scene". */
export const scenes = (value: number) => `${value} ${value === 1 ? "scene" : "scenes"}`;
