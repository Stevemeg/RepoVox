/*
 * Response types mirroring packages/contracts/openapi.json (FastAPI `repovox.schemas`).
 * Every field is snake_case exactly as sent. Literal unions narrow fields the API types as
 * plain strings; unknown values must still render safely.
 */
import type { NarrationView, VoiceView } from "./story-types";

export type AuthProviderName = "dev" | "github";

/** GET /v1/auth/session */
export type Account = {
  id: string;
  display_name: string;
  email: string;
  environment: string;
  fixtures_enabled: boolean;
  analysis_enabled: boolean;
  video_enabled: boolean;
  auth_provider: AuthProviderName;
  github_oauth_enabled: boolean;
};

/** ProjectView */
export type Project = {
  id: string;
  title: string;
  repository_url: string;
  status: string;
  created_at: string;
};

/** DELETE /v1/projects/{id} (202) */
export type ProjectDeletion = {
  deletion_id: string;
  access_revoked: boolean;
  cleanup: string;
};

/** StageView */
export type Stage = {
  id: string;
  ordinal: number;
  stage_key: string;
  state: string;
  attempt_count: number;
  error_code: string | null;
  next_attempt_at?: string | null;
};

/** AttemptView */
export type Attempt = {
  stage_id: string;
  attempt_no: number;
  started_at?: string;
  ended_at?: string | null;
  outcome: string;
  error_code: string | null;
};

/** HistoryView */
export type HistoryEntry = {
  version: number;
  state: string;
  error_code?: string | null;
  created_at: string;
};

/** UsageView */
export type UsageEntry = {
  event_type: string;
  units: number;
  measurements: Record<string, unknown>;
  created_at?: string;
};

/** JobSummary, extended by JobView (stages, attempts, history, usage, prior_job_id). */
export type Job = {
  id: string;
  project_id: string;
  project_title?: string | null;
  state: string;
  version: number;
  synthetic: boolean;
  fixture: string;
  error_code: string | null;
  created_at: string;
  finished_at?: string | null;
  deadline: string;
  commit_sha?: string | null;
  repository_url?: string | null;
  pipeline_version?: string | null;
  prior_job_id?: string | null;
  stages?: Stage[];
  attempts?: Attempt[];
  history?: HistoryEntry[];
  usage?: UsageEntry[];
};

export type VideoJobState =
  | "awaiting_analysis"
  | "queued"
  | "running"
  | "retry_wait"
  | "succeeded"
  | "failed"
  | "cancelled";

export type ArchitectureOutcome =
  | "published"
  | "unsupported"
  | "extraction_failed"
  | "rendering_failed"
  | "not_completed";

/** Which voice spoke a video (ADR-0027); defined with the story contract. */
export type VoiceRecord = VoiceView;

/** NarrationView: how a walkthrough was worded (ADR-0026) and voiced. */
export type NarrationRecord = NarrationView;

/** VideoView.metadata is an open object in the contract; known keys are typed here. */
export type VideoMetadata = {
  duration_seconds?: number;
  media?: { duration_seconds?: number; [key: string]: unknown };
  narration?: NarrationRecord | VoiceRecord;
  [key: string]: unknown;
};

/** VideoView */
export type Video = {
  id: string;
  category: "walkthrough" | "architecture" | (string & {});
  position: number;
  title: string;
  checksum: string;
  byte_count: number;
  metadata: VideoMetadata;
  published_at: string;
  expires_at: string;
};

/** MediaStageView */
export type VideoStage = {
  ordinal: number;
  stage_key: string;
  state: string;
  attempt_count: number;
  error_code: string | null;
};

/** MediaJobView */
export type VideoJob = {
  id: string;
  project_id: string;
  analysis_job_id: string;
  state: VideoJobState | (string & {});
  version: number;
  repository: string | null;
  commit_sha: string | null;
  architecture: ArchitectureOutcome | (string & {}) | null;
  error_code: string | null;
  created_at: string;
  deadline: string;
  finished_at: string | null;
  stages: VideoStage[];
  videos: Video[];
};
