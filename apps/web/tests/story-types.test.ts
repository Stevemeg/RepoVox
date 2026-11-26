import { describe, expect, it } from "vitest";
import {
  CANONICAL_STATUS_LABELS,
  claimIndex,
  normalizeNarration,
  normalizeVideoStory,
  normalizeVoice,
  OUTCOME_SCOPE,
} from "../src/lib/story-types";
import { COMMIT, DETERMINISTIC_NARRATION, SCOPE, storyResponse } from "./story-fixture";

describe("normalizeVideoStory", () => {
  it("keeps a well-formed response exactly, with no repairs", () => {
    const result = normalizeVideoStory(storyResponse())!;
    expect(result.issues).toBe(0);
    const { story } = result.view;
    expect(result.view.narration).toEqual(DETERMINISTIC_NARRATION);
    expect(story.commit_sha).toBe(COMMIT);
    expect(story.status_labels).toEqual(CANONICAL_STATUS_LABELS);
    expect(story.status_counts).toEqual({ VERIFIED: 3, INFERRED: 2, DOCUMENTATION_ONLY: 1, UNVERIFIED: 2 });
    expect(story.source_counts).toEqual({ readme: 1, source: 3, manifest: 1, test: 1 });
    expect(story.problem_statement.sufficiency).toBe("insufficient");
    expect(story.demonstrated_outcomes.scope).toBe(SCOPE);
    expect(story.mismatches.map((m) => m.kind)).toEqual(["declared_only_technology", "unstated_implementation"]);
    expect(story.instruction_like_lines).toBe(2);
    expect(story.evidence_trimmed).toBe(true);
    expect(story.implementation_approach.claims[0].evidence_refs[0]).toMatchObject({
      path: "app/main.py",
      start_line: 12,
      end_line: 12,
      quote: '@app.get("/greet")',
    });
  });

  it("matches the shipped scope literal", () => {
    expect(OUTCOME_SCOPE).toBe(SCOPE);
  });

  it.each([null, undefined, "story", 42, [], {}, { story: null }, { story: [] }, { story: "x" }])(
    "returns null for a response that is not a story: %j",
    (raw) => {
      expect(normalizeVideoStory(raw)).toBeNull();
    },
  );

  it("degrades a sparse story safely instead of throwing", () => {
    const result = normalizeVideoStory({ story: {} })!;
    expect(result.view.story.problem_statement).toEqual({ sufficiency: "unknown", claims: [] });
    expect(result.view.story.demonstrated_outcomes.scope).toBe(OUTCOME_SCOPE);
    expect(result.view.story.mismatches).toEqual([]);
    expect(result.view.story.commit_sha).toBe("");
    expect(result.view.narration).toBeNull();
    // Only the missing commit counts as a repair; absent optional lists are simply empty.
    expect(result.issues).toBe(1);
  });

  it("leaves out malformed claims, citations and mismatches and counts each", () => {
    const raw = storyResponse({
      limitations: {
        claims: [
          { id: "", text: "no id", status: "VERIFIED" },
          { id: "l-ok", text: "kept", status: "INFERRED", evidence_type: "limitation", evidence_refs: [{ path: "", start_line: 1 }, { path: "a.py", start_line: 0 }, { path: "b.py", start_line: 3, end_line: 1 }] },
          "not a claim",
        ],
      },
      mismatches: [{ id: "x", kind: "readme_only_feature" }, { id: "y", kind: "readme_only_feature", detail: "ok" }],
      unresolved_questions: { claims: "nope" },
    });
    const result = normalizeVideoStory(raw)!;
    const limitations = result.view.story.limitations.claims;
    expect(limitations.map((c) => c.id)).toEqual(["l-ok"]);
    // The citation with end before start is clamped to a one-line range, not dropped.
    expect(limitations[0].evidence_refs).toEqual([
      expect.objectContaining({ path: "b.py", start_line: 3, end_line: 3 }),
    ]);
    expect(result.view.story.mismatches.map((m) => m.id)).toEqual(["y"]);
    expect(result.view.story.unresolved_questions.claims).toEqual([]);
    // 2 bad claims + 2 bad citations + 1 bad mismatch + 1 non-list section.
    expect(result.issues).toBe(6);
  });

  it("never shows an unrecognised status as anything stronger than UNVERIFIED", () => {
    const raw = storyResponse({
      limitations: { claims: [{ id: "l-x", text: "odd", status: "TOTALLY_VERIFIED", evidence_type: "limitation" }] },
    });
    const result = normalizeVideoStory(raw)!;
    expect(result.view.story.limitations.claims[0].status).toBe("UNVERIFIED");
    expect(result.issues).toBe(1);
  });

  it("refuses relabelled statuses: a documentation claim is never badged VERIFIED", () => {
    const raw = storyResponse({
      status_labels: { ...CANONICAL_STATUS_LABELS, DOCUMENTATION_ONLY: "VERIFIED", INFERRED: "CONFIRMED" },
    });
    const result = normalizeVideoStory(raw)!;
    expect(result.view.story.status_labels).toEqual(CANONICAL_STATUS_LABELS);
    expect(result.view.story.status_labels.DOCUMENTATION_ONLY).toBe("AUTHOR-STATED / NOT VERIFIED BY CODE");
    expect(result.issues).toBe(2);
  });

  it("drops an invalid commit so no citation can be linked against it", () => {
    const result = normalizeVideoStory(storyResponse({ commit_sha: "main" }))!;
    expect(result.view.story.commit_sha).toBe("");
    expect(result.issues).toBe(1);
  });

  it("indexes every claim by id for mismatch references", () => {
    const { story } = normalizeVideoStory(storyResponse())!.view;
    const index = claimIndex(story);
    expect([...index.keys()].sort()).toEqual(
      ["i-declared", "i-inferred", "i-intended", "i-route", "l-scope", "o-test", "p-undocumented", "u-runtime"],
    );
  });
});

describe("narration records", () => {
  it("normalizes a model record and clamps impossible counts", () => {
    const record = normalizeNarration({
      ...DETERMINISTIC_NARRATION,
      refiner: "grounded-llm-refiner-1.0",
      provider: "anthropic",
      model: "claude-opus-5-5",
      scenes_total: 8,
      scenes_refined: 99,
      scenes_fallback: -1,
      rejection_reasons: { "scene-2": ["uncited_claim", 7], "scene-5": "x" },
    })!;
    expect(record.provider).toBe("anthropic");
    expect(record.model).toBe("claude-opus-5-5");
    expect(record.scenes_refined).toBe(8);
    expect(record.scenes_fallback).toBe(0);
    expect(record.rejection_reasons).toEqual({ "scene-2": ["uncited_claim"], "scene-5": [] });
  });

  it("treats a voice-only record as no narration record", () => {
    expect(normalizeNarration({ tts_provider: "kokoro_onnx" })).toBeNull();
    expect(normalizeVoice({ tts_provider: "kokoro_onnx", tts_engine: "kokoro-onnx", tts_voice: "af_heart" })).toEqual({
      tts_provider: "kokoro_onnx",
      tts_engine: "kokoro-onnx",
      tts_voice: "af_heart",
    });
    expect(normalizeVoice(undefined)).toBeNull();
    expect(normalizeVoice("kokoro")).toBeNull();
  });

  it("counts a story narration that is not a narration record", () => {
    const result = normalizeVideoStory(storyResponse({}, { provider: 5 }))!;
    expect(result.view.narration).toBeNull();
    expect(result.issues).toBe(1);
  });
});
