import { describe, expect, it } from "vitest";
import { describeProvenance, describeVoice } from "../src/lib/narration";
import { DETERMINISTIC_NARRATION, KOKORO_VOICE } from "./story-fixture";

const model = (provider: string, extra: Record<string, unknown> = {}) => ({
  ...DETERMINISTIC_NARRATION,
  refiner: "grounded-llm-refiner-1.0",
  provider,
  model: "synthetic-model-1",
  blueprint_sha256: "f".repeat(64),
  scenes_total: 8,
  scenes_refined: 6,
  scenes_fallback: 2,
  refined_scene_ids: ["s1", "s2", "s3", "s4", "s5", "s6"],
  ...extra,
});

describe("describeProvenance", () => {
  it("states template wording for a deterministic record, with the recorded Kokoro voice", () => {
    const provenance = describeProvenance("walkthrough", DETERMINISTIC_NARRATION);
    expect(provenance.recorded).toBe(true);
    expect(provenance.wording).toEqual({
      kind: "template",
      refiner: "deterministic-template-1.0",
      scenesTotal: 8,
    });
    expect(provenance.voice).toMatchObject({
      recorded: true,
      provider: "kokoro_onnx",
      engine: "kokoro-onnx",
      voice: "af_heart",
    });
    expect(provenance.voice!.description).toMatch(/local neural text-to-speech voice \(Kokoro\)/);
  });

  it.each([
    ["anthropic", true, /Anthropic's hosted API/],
    ["openai_compatible", true, /OpenAI-compatible hosted API/],
    ["ollama", false, /self-hosted model server/],
  ])("names the %s provider, its model and the refined and fallback scene counts", (provider, hosted, label) => {
    const provenance = describeProvenance(
      "walkthrough",
      model(provider, { rejection_reasons: { s8: ["uncited_claim"], s7: ["unsupported_number", "uncited_claim"], s1: [] } }),
    );
    expect(provenance.wording).toMatchObject({
      kind: "model",
      provider,
      hosted,
      model: "synthetic-model-1",
      scenesTotal: 8,
      scenesRefined: 6,
      scenesFallback: 2,
      fallbackReason: null,
      // Sorted by scene; scenes with no reasons are omitted.
      rejections: [
        { scene: "s7", reasons: ["unsupported_number", "uncited_claim"] },
        { scene: "s8", reasons: ["uncited_claim"] },
      ],
    });
    expect(provenance.wording).toHaveProperty("providerLabel", expect.stringMatching(label));
  });

  it("records why no model wording was used at all", () => {
    const provenance = describeProvenance(
      "walkthrough",
      model("anthropic", { scenes_refined: 0, scenes_fallback: 8, refined_scene_ids: [], fallback_reason: "llm_timeout" }),
    );
    expect(provenance.wording).toMatchObject({ kind: "model", scenesRefined: 0, fallbackReason: "llm_timeout" });
  });

  it("treats an unrecognised provider as a hosted model, never as local or deterministic", () => {
    const provenance = describeProvenance("walkthrough", model("mystery"));
    expect(provenance.wording).toMatchObject({ kind: "model", hosted: true });
  });

  it("describes an architecture explainer from its voice-only record", () => {
    const provenance = describeProvenance("architecture", KOKORO_VOICE);
    expect(provenance).toMatchObject({ recorded: true, wording: { kind: "explainer" } });
    expect(provenance.voice).toMatchObject({ provider: "kokoro_onnx", voice: "af_heart" });
  });

  it("says nothing was recorded when metadata has no narration", () => {
    expect(describeProvenance("walkthrough", undefined)).toEqual({ recorded: false, wording: null, voice: null });
    expect(describeProvenance("walkthrough", "deterministic")).toEqual({ recorded: false, wording: null, voice: null });
  });

  it("falls back to the story API's record only when the metadata has none", () => {
    const fallback = { ...DETERMINISTIC_NARRATION, tts_provider: "deterministic" as const, tts_engine: "espeak-ng", tts_voice: "espeak-ng" };
    expect(describeProvenance("walkthrough", undefined, fallback).voice).toMatchObject({ provider: "deterministic" });
    expect(describeProvenance("walkthrough", DETERMINISTIC_NARRATION, fallback).voice).toMatchObject({ provider: "kokoro_onnx" });
  });
});

describe("describeVoice", () => {
  it.each([
    ["deterministic", /operating system's local speech synthesizer/],
    ["local", /A local speech synthesizer/],
    ["something_else", /does not recognise/],
  ])("describes the %s voice provider truthfully", (provider, description) => {
    expect(describeVoice({ tts_provider: provider, tts_engine: "e", tts_voice: "v" })!.description).toMatch(description);
  });

  it("says when a voice predates the voice record", () => {
    const voice = describeVoice({ tts_provider: null, tts_engine: null, tts_voice: null })!;
    expect(voice.recorded).toBe(false);
    expect(voice.description).toMatch(/was not recorded/);
  });
});
