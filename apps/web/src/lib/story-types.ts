/*
 * The verified engineering story and narration record served by
 * `GET /v1/video-jobs/{job_id}/videos/{video_id}/story`, mirroring the OpenAPI schemas
 * `VideoStoryView`, `StoryView`, `NarrationView`, `Claim`, `EvidenceRef` and `Mismatch`
 * (`apps/api/repovox/schemas/responses.py`, `media/story_view.py`, `media/story.py`).
 *
 * Every field is snake_case exactly as sent. The normalizers below never throw: a response
 * that is not shaped like a story yields `null`, a malformed entry inside one is left out
 * (or, for an unrecognised status, shown as UNVERIFIED), and each such repair is counted in
 * `issues` so the page can say that something was not shown. Every string stays untrusted
 * repository text: it is rendered as React text only, and a permalink reaches an `href` only
 * after `safePermalink(..., commit_sha)`.
 */

export type ClaimStatus = "VERIFIED" | "INFERRED" | "DOCUMENTATION_ONLY" | "UNVERIFIED";

export const CLAIM_STATUSES: readonly ClaimStatus[] = [
  "VERIFIED",
  "INFERRED",
  "DOCUMENTATION_ONLY",
  "UNVERIFIED",
];

/** The fixed badge text per status (`story_view.STATUS_LABELS`). */
export const CANONICAL_STATUS_LABELS: Readonly<Record<ClaimStatus, string>> = {
  VERIFIED: "VERIFIED",
  INFERRED: "INFERRED",
  DOCUMENTATION_ONLY: "AUTHOR-STATED / NOT VERIFIED BY CODE",
  UNVERIFIED: "UNVERIFIED",
};

/** Four visibly different badge treatments; status is always also stated in text. */
export type ClaimTone = "verified" | "inferred" | "author-stated" | "unverified";
export const CLAIM_TONES: Readonly<Record<ClaimStatus, ClaimTone>> = {
  VERIFIED: "verified",
  INFERRED: "inferred",
  DOCUMENTATION_ONLY: "author-stated",
  UNVERIFIED: "unverified",
};

export type EvidenceType =
  | "author_stated_problem"
  | "inferred_problem_context"
  | "intended_solution"
  | "implemented_solution"
  | "demonstrated_outcome"
  | "unverified_outcome"
  | "limitation"
  | "unresolved";

export type SourceRole = "readme" | "documentation" | "manifest" | "source" | "test" | "example";
export const SOURCE_ROLES: readonly SourceRole[] = [
  "readme",
  "documentation",
  "manifest",
  "source",
  "test",
  "example",
];

export type ProofKind = "unit_test" | "integration_test" | "benchmark" | "example";

export type MismatchKind =
  | "readme_only_feature"
  | "mention_only_technology"
  | "declared_only_technology"
  | "unstated_implementation"
  | "incomplete_implementation"
  | "unbenchmarked_performance_claim"
  | "unsupported_architecture_claim";

/** `DemonstratedOutcomes.scope`: a fixed literal in the contract, shown verbatim. */
export const OUTCOME_SCOPE =
  "Test and example assertions are read from source; RepoVox does not run them. They show behaviour the authors check, not production use or measured performance.";

/** EvidenceRef: one exact citation of a hash-pinned file at the story's commit. */
export type StoryEvidenceRef = {
  id: string;
  /** Repository-relative path at the pinned commit. Untrusted text. */
  path: string;
  file_sha256: string;
  start_line: number;
  end_line: number;
  /** The cited lines, at most 240 characters in this view. Untrusted text. */
  quote: string;
  /** Unvalidated: pass through `safePermalink(permalink, story.commit_sha)` before use. */
  permalink: string;
};

/** Claim: the atomic unit of every story section. */
export type StoryClaim = {
  id: string;
  /** Untrusted text: render as plain text only. */
  text: string;
  evidence_type: EvidenceType | (string & {});
  status: ClaimStatus;
  /** At most three in this view. */
  evidence_refs: StoryEvidenceRef[];
  /** `<path>:<line>` of the first citation. */
  source_location: string | null;
  analysis_claim_ids: string[];
  /** Implemented-solution claims that corroborate an intended solution. */
  supports: string[];
  proof: ProofKind | (string & {}) | null;
  component_ids: string[];
  connection_ids: string[];
};

/** Mismatch: a stated intention or claim that the code, tests or architecture contradict. */
export type StoryMismatch = {
  id: string;
  kind: MismatchKind | (string & {});
  /** Untrusted text. */
  detail: string;
  stated_claim_ids: string[];
  evidence_claim_ids: string[];
};

export type ProblemSufficiency = "documented" | "insufficient";

export type StoryArchitecture = {
  ir_version: string | null;
  report_sha256: string | null;
  explanation: "supported" | "unsupported" | "unavailable" | (string & {});
  unavailable_reason: string | null;
  architecture_ids: string[];
  primary: string | null;
  view: string | null;
  claims: StoryClaim[];
  workflow: StoryClaim[];
};

export type StoryClaims = { claims: StoryClaim[] };

/** StoryView: the bounded public view of one verified engineering story. */
export type StoryView = {
  view_version: string;
  schema_version: string;
  extractor_version: string;
  repository: string;
  /** 40 lowercase hex characters, or "" when the response did not carry a valid one. */
  commit_sha: string;
  analysis_sha256: string;
  source_counts: Partial<Record<SourceRole, number>>;
  status_counts: Record<ClaimStatus, number>;
  /** Always the canonical badge text; see `normalizeLabels`. */
  status_labels: Record<ClaimStatus, string>;
  problem_statement: { sufficiency: ProblemSufficiency | "unknown"; claims: StoryClaim[] };
  problem_context: StoryClaims;
  intended_solution: StoryClaims;
  implementation_approach: { claims: StoryClaim[]; decisions: StoryClaim[] };
  architecture: StoryArchitecture;
  implementation_evidence: StoryClaims;
  demonstrated_outcomes: { scope: string; claims: StoryClaim[] };
  limitations: StoryClaims;
  unresolved_questions: StoryClaims;
  mismatches: StoryMismatch[];
  /** README lines that addressed a model; counted, never used. */
  instruction_like_lines: number;
  /** True when citations or quotes were shortened for this view. */
  evidence_trimmed: boolean;
};

export type TtsProvider = "deterministic" | "kokoro_onnx" | "local";

/** Which voice spoke a video (ADR-0027). All null on videos that predate the record. */
export type VoiceView = {
  tts_provider: TtsProvider | (string & {}) | null;
  tts_engine: string | null;
  tts_voice: string | null;
};

export type NarrationProvider = "deterministic" | "ollama" | "openai_compatible" | "anthropic";

/** NarrationView: how a walkthrough was worded (ADR-0026) and voiced (ADR-0027). */
export type NarrationView = VoiceView & {
  refiner: "deterministic-template-1.0" | "grounded-llm-refiner-1.0" | (string & {});
  provider: NarrationProvider | (string & {});
  /** Null exactly when `provider` is "deterministic". */
  model: string | null;
  blueprint_sha256: string | null;
  scenes_total: number;
  /** Scenes whose model wording passed the grounding check. */
  scenes_refined: number;
  /** Scenes that kept the template wording. */
  scenes_fallback: number;
  refined_scene_ids: string[];
  /** Set when no model wording was used at all. */
  fallback_reason: string | null;
  /** Scene id -> fixed reason codes. */
  rejection_reasons: Record<string, string[]>;
};

/** VideoStoryView: the response of `GET .../videos/{video_id}/story`. */
export type VideoStoryView = {
  video_id: string;
  job_id: string;
  category: string;
  narration: NarrationView | null;
  story: StoryView;
};

/** A normalized response plus how many malformed entries were repaired or left out. */
export type NormalizedStory = { view: VideoStoryView; issues: number };

/* Normalizers ------------------------------------------------------------- */

type Bag = Record<string, unknown>;

const SHA1 = /^[a-f0-9]{40}$/;
const SHA256 = /^[a-f0-9]{64}$/;
/** Generous client-side caps; the API's own limits are lower. */
const LIST_LIMIT = 64;
const REF_LIMIT = 8;
const ID_LIMIT = 32;

const isBag = (value: unknown): value is Bag =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const bag = (value: unknown): Bag => (isBag(value) ? value : {});
const text = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;
const optionalText = (value: unknown): string | null =>
  typeof value === "string" && value !== "" ? value : null;
const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
const strings = (value: unknown, limit = ID_LIMIT): string[] =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string").slice(0, limit)
    : [];
const isStatus = (value: unknown): value is ClaimStatus =>
  typeof value === "string" && (CLAIM_STATUSES as readonly string[]).includes(value);
const positiveLine = (value: unknown): number | null =>
  typeof value === "number" && Number.isInteger(value) && value >= 1 ? value : null;

/** Collects repairs while one response is normalized. */
class Tally {
  issues = 0;
  note() {
    this.issues += 1;
  }
}

function evidenceRef(raw: unknown, tally: Tally): StoryEvidenceRef | null {
  const ref = bag(raw);
  const path = text(ref.path);
  const start = positiveLine(ref.start_line);
  const end = positiveLine(ref.end_line);
  if (!path || start === null) {
    tally.note();
    return null;
  }
  return {
    id: text(ref.id),
    path,
    file_sha256: text(ref.file_sha256),
    start_line: start,
    end_line: end !== null && end >= start ? end : start,
    quote: text(ref.quote),
    permalink: text(ref.permalink),
  };
}

function claim(raw: unknown, tally: Tally): StoryClaim | null {
  const item = bag(raw);
  const id = text(item.id);
  const body = text(item.text);
  if (!id || !body) {
    tally.note();
    return null;
  }
  let status: ClaimStatus;
  if (isStatus(item.status)) status = item.status;
  else {
    // Never shown as anything stronger than the contract allows: unknown means unsupported.
    status = "UNVERIFIED";
    tally.note();
  }
  const refs = Array.isArray(item.evidence_refs) ? item.evidence_refs.slice(0, REF_LIMIT) : [];
  return {
    id,
    text: body,
    evidence_type: text(item.evidence_type, "unresolved"),
    status,
    evidence_refs: refs
      .map((ref) => evidenceRef(ref, tally))
      .filter((ref): ref is StoryEvidenceRef => ref !== null),
    source_location: optionalText(item.source_location),
    analysis_claim_ids: strings(item.analysis_claim_ids),
    supports: strings(item.supports),
    proof: optionalText(item.proof),
    component_ids: strings(item.component_ids),
    connection_ids: strings(item.connection_ids),
  };
}

function claims(raw: unknown, tally: Tally): StoryClaim[] {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw)) {
    tally.note();
    return [];
  }
  if (raw.length > LIST_LIMIT) tally.note();
  return raw
    .slice(0, LIST_LIMIT)
    .map((item) => claim(item, tally))
    .filter((item): item is StoryClaim => item !== null);
}

function mismatch(raw: unknown, tally: Tally): StoryMismatch | null {
  const item = bag(raw);
  const id = text(item.id);
  const detail = text(item.detail);
  if (!id || !detail) {
    tally.note();
    return null;
  }
  return {
    id,
    kind: text(item.kind, "unknown"),
    detail,
    stated_claim_ids: strings(item.stated_claim_ids),
    evidence_claim_ids: strings(item.evidence_claim_ids),
  };
}

/**
 * The badge text per status. The labels are fixed by the contract (`StoryView.labelled`
 * refuses any other), so a response carrying different wording is malformed: the canonical
 * text is shown instead, and a documentation claim can never be relabelled as verified.
 */
function normalizeLabels(raw: unknown, tally: Tally): Record<ClaimStatus, string> {
  const labels = bag(raw);
  const result = { ...CANONICAL_STATUS_LABELS };
  for (const status of CLAIM_STATUSES)
    if (labels[status] !== undefined && labels[status] !== CANONICAL_STATUS_LABELS[status])
      tally.note();
  return result;
}

function normalizeStory(raw: unknown, tally: Tally): StoryView {
  const story = bag(raw);
  const problem = bag(story.problem_statement);
  const approach = bag(story.implementation_approach);
  const architecture = bag(story.architecture);
  const outcomes = bag(story.demonstrated_outcomes);
  const commit = text(story.commit_sha);
  if (!SHA1.test(commit)) tally.note();
  const analysis = text(story.analysis_sha256);
  const sufficiency = problem.sufficiency;
  const statusCounts = bag(story.status_counts);
  const sourceCounts = bag(story.source_counts);
  const mismatches = Array.isArray(story.mismatches) ? story.mismatches.slice(0, LIST_LIMIT) : [];
  return {
    view_version: text(story.view_version, "unknown"),
    schema_version: text(story.schema_version, "unknown"),
    extractor_version: text(story.extractor_version, "unknown"),
    repository: text(story.repository),
    commit_sha: SHA1.test(commit) ? commit : "",
    analysis_sha256: SHA256.test(analysis) ? analysis : "",
    source_counts: Object.fromEntries(
      SOURCE_ROLES.filter((role) => sourceCounts[role] !== undefined).map((role) => [
        role,
        count(sourceCounts[role]),
      ]),
    ),
    status_counts: Object.fromEntries(
      CLAIM_STATUSES.map((status) => [status, count(statusCounts[status])]),
    ) as Record<ClaimStatus, number>,
    status_labels: normalizeLabels(story.status_labels, tally),
    problem_statement: {
      sufficiency:
        sufficiency === "documented" || sufficiency === "insufficient" ? sufficiency : "unknown",
      claims: claims(problem.claims, tally),
    },
    problem_context: { claims: claims(bag(story.problem_context).claims, tally) },
    intended_solution: { claims: claims(bag(story.intended_solution).claims, tally) },
    implementation_approach: {
      claims: claims(approach.claims, tally),
      decisions: claims(approach.decisions, tally),
    },
    architecture: {
      ir_version: optionalText(architecture.ir_version),
      report_sha256: optionalText(architecture.report_sha256),
      explanation: text(architecture.explanation, "unavailable"),
      unavailable_reason: optionalText(architecture.unavailable_reason),
      architecture_ids: strings(architecture.architecture_ids, 8),
      primary: optionalText(architecture.primary),
      view: optionalText(architecture.view),
      claims: claims(architecture.claims, tally),
      workflow: claims(architecture.workflow, tally),
    },
    implementation_evidence: { claims: claims(bag(story.implementation_evidence).claims, tally) },
    demonstrated_outcomes: {
      // A fixed literal in the contract; the same sentence is shown if it is ever missing.
      scope: text(outcomes.scope) || OUTCOME_SCOPE,
      claims: claims(outcomes.claims, tally),
    },
    limitations: { claims: claims(bag(story.limitations).claims, tally) },
    unresolved_questions: { claims: claims(bag(story.unresolved_questions).claims, tally) },
    mismatches: mismatches
      .map((item) => mismatch(item, tally))
      .filter((item): item is StoryMismatch => item !== null),
    instruction_like_lines: count(story.instruction_like_lines),
    evidence_trimmed: story.evidence_trimmed === true,
  };
}

/** The voice fields of any narration record, or null when none is recorded at all. */
export function normalizeVoice(raw: unknown): VoiceView | null {
  if (!isBag(raw)) return null;
  return {
    tts_provider: optionalText(raw.tts_provider),
    tts_engine: optionalText(raw.tts_engine),
    tts_voice: optionalText(raw.tts_voice),
  };
}

/**
 * A walkthrough's narration record, or null when the value is not one. A record without a
 * `provider` is a voice-only record (architecture explainers): use `normalizeVoice`.
 */
export function normalizeNarration(raw: unknown): NarrationView | null {
  if (!isBag(raw) || typeof raw.provider !== "string" || raw.provider === "") return null;
  const reasons = bag(raw.rejection_reasons);
  const total = count(raw.scenes_total);
  return {
    ...normalizeVoice(raw)!,
    refiner: text(raw.refiner, "unknown"),
    provider: raw.provider,
    model: optionalText(raw.model),
    blueprint_sha256: optionalText(raw.blueprint_sha256),
    scenes_total: total,
    scenes_refined: Math.min(count(raw.scenes_refined), total),
    scenes_fallback: Math.min(count(raw.scenes_fallback), total),
    refined_scene_ids: strings(raw.refined_scene_ids, 24),
    fallback_reason: optionalText(raw.fallback_reason),
    rejection_reasons: Object.fromEntries(
      Object.entries(reasons)
        .slice(0, 24)
        .map(([scene, codes]) => [scene, strings(codes, 16)]),
    ),
  };
}

/**
 * The story response, normalized, or null when it is not shaped like one (not an object, or
 * without a `story` object). Never throws.
 */
export function normalizeVideoStory(raw: unknown): NormalizedStory | null {
  if (!isBag(raw) || !isBag(raw.story)) return null;
  const tally = new Tally();
  const story = normalizeStory(raw.story, tally);
  const narration =
    raw.narration === null || raw.narration === undefined
      ? null
      : normalizeNarration(raw.narration);
  if (raw.narration !== null && raw.narration !== undefined && narration === null) tally.note();
  return {
    view: {
      video_id: text(raw.video_id),
      job_id: text(raw.job_id),
      category: text(raw.category, "walkthrough"),
      narration,
      story,
    },
    issues: tally.issues,
  };
}

/** Every claim in the story by id, for resolving mismatch and `supports` references. */
export function claimIndex(story: StoryView): Map<string, StoryClaim> {
  const index = new Map<string, StoryClaim>();
  const groups = [
    story.problem_statement.claims,
    story.problem_context.claims,
    story.intended_solution.claims,
    story.implementation_approach.claims,
    story.implementation_approach.decisions,
    story.architecture.claims,
    story.architecture.workflow,
    story.implementation_evidence.claims,
    story.demonstrated_outcomes.claims,
    story.limitations.claims,
    story.unresolved_questions.claims,
  ];
  for (const group of groups) for (const item of group) if (!index.has(item.id)) index.set(item.id, item);
  return index;
}
