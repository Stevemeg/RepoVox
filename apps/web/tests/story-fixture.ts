// Synthetic Video Studio and story fixtures. Nothing here comes from a real repository.
import type { VideoJob } from "../src/lib/types";

export const PROJECT = "11111111-1111-4111-8111-111111111111";
export const JOB = "22222222-2222-4222-8222-222222222222";
export const WALKTHROUGH = "33333333-3333-4333-8333-333333333333";
export const EXPLAINER_A = "44444444-4444-4444-8444-444444444444";
export const EXPLAINER_B = "66666666-6666-4666-8666-666666666666";
export const COMMIT = "a".repeat(40);
export const OTHER_COMMIT = "b".repeat(40);

export const PUBLISHED = "2026-11-14T00:10:00Z";
/** Far in the future, so the synthetic videos are never expired while tests run. */
export const FUTURE = "2099-01-01T00:00:00Z";
export const PAST = "2020-01-01T00:00:00Z";

export const STATUS_LABELS = {
  VERIFIED: "VERIFIED",
  INFERRED: "INFERRED",
  DOCUMENTATION_ONLY: "AUTHOR-STATED / NOT VERIFIED BY CODE",
  UNVERIFIED: "UNVERIFIED",
};

export const SCOPE =
  "Test and example assertions are read from source; RepoVox does not run them. They show behaviour the authors check, not production use or measured performance.";

export const permalink = (path: string, line: number, commit = COMMIT) =>
  `https://github.com/example/demo/blob/${commit}/${path}#L${line}-L${line}`;

export const ref = (id: string, path: string, line: number, quote: string, link?: string) => ({
  id,
  path,
  file_sha256: "c".repeat(64),
  start_line: line,
  end_line: line,
  quote,
  permalink: link ?? permalink(path, line),
});

type ClaimInput = {
  id: string;
  text: string;
  status: string;
  evidence_type: string;
  refs?: ReturnType<typeof ref>[];
  supports?: string[];
  proof?: string | null;
};

export const claim = ({ id, text, status, evidence_type, refs = [], supports = [], proof = null }: ClaimInput) => ({
  id,
  text,
  evidence_type,
  status,
  evidence_refs: refs,
  source_location: refs[0] ? `${refs[0].path}:${refs[0].start_line}` : null,
  analysis_claim_ids: [],
  supports,
  proof,
  component_ids: [],
  connection_ids: [],
});

export const DETERMINISTIC_NARRATION = {
  refiner: "deterministic-template-1.0",
  provider: "deterministic",
  model: null,
  blueprint_sha256: null,
  scenes_total: 8,
  scenes_refined: 0,
  scenes_fallback: 0,
  refined_scene_ids: [],
  fallback_reason: null,
  rejection_reasons: {},
  tts_provider: "kokoro_onnx",
  tts_engine: "kokoro-onnx",
  tts_voice: "af_heart",
};

export const KOKORO_VOICE = {
  tts_provider: "kokoro_onnx",
  tts_engine: "kokoro-onnx",
  tts_voice: "af_heart",
};

/** A complete synthetic story response; `overrides` replaces top-level story fields. */
export function storyResponse(overrides: Record<string, unknown> = {}, narration: unknown = DETERMINISTIC_NARRATION) {
  const intended = claim({
    id: "i-intended",
    text: "The demo serves a synthetic greeting service.",
    status: "DOCUMENTATION_ONLY",
    evidence_type: "intended_solution",
    refs: [ref("e-readme", "README.md", 3, "A synthetic greeting service.")],
  });
  const implemented = claim({
    id: "i-route",
    text: "app/main.py registers a framework route on line 12.",
    status: "VERIFIED",
    evidence_type: "implemented_solution",
    refs: [ref("e-route", "app/main.py", 12, '@app.get("/greet")')],
  });
  const inferred = claim({
    id: "i-inferred",
    text: "A web client calls the greeting route.",
    status: "INFERRED",
    evidence_type: "intended_solution",
    refs: [ref("e-client", "web/api.ts", 4, 'fetch("/greet")')],
    supports: ["i-route"],
  });
  const declared = claim({
    id: "i-declared",
    text: "SyntheticDB is declared as a dependency.",
    status: "VERIFIED",
    evidence_type: "implemented_solution",
    refs: [ref("e-manifest", "pyproject.toml", 8, '"syntheticdb>=1"')],
  });
  const outcome = claim({
    id: "o-test",
    text: "tests/test_greet.py checks the greeting text.",
    status: "VERIFIED",
    evidence_type: "demonstrated_outcome",
    refs: [ref("e-test", "tests/test_greet.py", 5, 'assert greet() == "hi"')],
    proof: "unit_test",
  });
  const open = claim({
    id: "u-runtime",
    text: "Runtime behaviour was not observed; RepoVox reads the source without running it.",
    status: "UNVERIFIED",
    evidence_type: "unresolved",
  });
  const problem = claim({
    id: "p-undocumented",
    text: "The repository does not document the problem it solves, so no problem statement is given and none is inferred from its name.",
    status: "UNVERIFIED",
    evidence_type: "unresolved",
  });
  const limitation = claim({
    id: "l-scope",
    text: "Only the greeting route is described.",
    status: "INFERRED",
    evidence_type: "limitation",
    refs: [ref("e-limit", "README.md", 9, "Only greetings for now.")],
  });
  return {
    video_id: WALKTHROUGH,
    job_id: JOB,
    category: "walkthrough",
    narration,
    story: {
      view_version: "engineering-story-view-1.0",
      schema_version: "problem-to-solution-1.0",
      extractor_version: "problem-to-solution-extractor-1.0",
      repository: "example/demo",
      commit_sha: COMMIT,
      analysis_sha256: "d".repeat(64),
      source_counts: { readme: 1, source: 3, manifest: 1, test: 1 },
      status_counts: { VERIFIED: 3, INFERRED: 2, DOCUMENTATION_ONLY: 1, UNVERIFIED: 2 },
      status_labels: STATUS_LABELS,
      problem_statement: { sufficiency: "insufficient", claims: [problem] },
      problem_context: { claims: [] },
      intended_solution: { claims: [intended, inferred] },
      implementation_approach: { claims: [implemented, declared], decisions: [] },
      architecture: {
        ir_version: "architecture-ir-1.0",
        report_sha256: "e".repeat(64),
        explanation: "supported",
        unavailable_reason: null,
        architecture_ids: ["system-architecture"],
        primary: "system-architecture",
        view: "overview",
        claims: [],
        workflow: [],
      },
      implementation_evidence: { claims: [] },
      demonstrated_outcomes: { scope: SCOPE, claims: [outcome] },
      limitations: { claims: [limitation] },
      unresolved_questions: { claims: [open] },
      mismatches: [
        {
          id: "x-declared",
          kind: "declared_only_technology",
          detail: "SyntheticDB is declared as a dependency, but no analysed source file imports it.",
          stated_claim_ids: ["i-intended"],
          evidence_claim_ids: ["i-declared"],
        },
        {
          id: "x-unstated",
          kind: "unstated_implementation",
          detail: "The code imports a web framework, which the documentation does not name.",
          stated_claim_ids: [],
          evidence_claim_ids: ["i-route"],
        },
      ],
      instruction_like_lines: 2,
      evidence_trimmed: true,
      ...overrides,
    },
  };
}

export function videoJob(overrides: Partial<VideoJob> = {}): VideoJob {
  return {
    id: JOB,
    project_id: PROJECT,
    analysis_job_id: "55555555-5555-4555-8555-555555555555",
    state: "succeeded",
    version: 9,
    repository: "example/demo",
    commit_sha: COMMIT,
    architecture: "published",
    error_code: null,
    created_at: "2026-11-14T00:00:00Z",
    deadline: "2026-11-14T01:00:00Z",
    finished_at: PUBLISHED,
    stages: ["storyboard", "narration", "tts", "render", "encode", "architecture"].map(
      (stage_key, index) => ({
        ordinal: index + 1,
        stage_key,
        state: "succeeded",
        attempt_count: 1,
        error_code: null,
      }),
    ),
    // Deliberately out of `position` order: the studio must sort them.
    videos: [
      {
        id: EXPLAINER_B,
        category: "architecture",
        position: 2,
        title: "HTTP service in app/main.py",
        byte_count: 5_277_206,
        checksum: "9".repeat(64),
        metadata: { media: { duration_seconds: 100.5 }, narration: KOKORO_VOICE },
        published_at: PUBLISHED,
        expires_at: FUTURE,
      },
      {
        id: WALKTHROUGH,
        category: "walkthrough",
        position: 0,
        title: "Repository walkthrough",
        byte_count: 8_395_958,
        checksum: "b".repeat(64),
        metadata: { duration_seconds: 91.9, narration: DETERMINISTIC_NARRATION },
        published_at: PUBLISHED,
        expires_at: FUTURE,
      },
      {
        id: EXPLAINER_A,
        category: "architecture",
        position: 1,
        title: "System architecture across 2 tiers",
        byte_count: 7_457_350,
        checksum: "8".repeat(64),
        metadata: { media: { duration_seconds: 64 }, narration: KOKORO_VOICE },
        published_at: PUBLISHED,
        expires_at: FUTURE,
      },
    ],
    ...overrides,
  };
}

export const respond = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

/** A fetch stub that routes by URL suffix; unknown URLs fail the test loudly. */
export function routedFetch(routes: Record<string, () => Response | Promise<Response>>) {
  return async (input: RequestInfo | URL): Promise<Response> => {
    const url = String(input);
    for (const [suffix, handler] of Object.entries(routes)) if (url.endsWith(suffix)) return handler();
    throw new Error(`unexpected fetch ${url}`);
  };
}
