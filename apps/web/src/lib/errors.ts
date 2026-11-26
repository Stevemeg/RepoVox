/*
 * Deterministic, user-actionable messages for every error the API can return and every
 * code a job can stop with. Server text is never shown: the API sends only a fixed `code`
 * (and a `request_id`), and this module turns that pair into our own sentence. The raw code
 * and request id may be shown only as muted secondary support metadata.
 *
 * Where codes come from (apps/api/repovox):
 *  - HTTP errors: `DomainError(code, status)`, SQL `RAISE EXCEPTION` codes mapped by
 *    `main.py` SAFE_DB_CODES, `RequestValidationError` -> 422 `invalid_request`, and the
 *    repository resolution done at analysis/video admission, where an `AnalysisError`
 *    becomes 429 (`github_rate_limited`), 422 (non-transient) or 503 (transient).
 *  - Job `error_code`: the worker stage that stopped (`AnalysisError` codes such as
 *    `secret_detected`, `archive_*`, `analysis_fact_limit`, and the media pipeline's
 *    `story_*`, `narration_*`, `speech_*` ... codes), plus lifecycle codes.
 */
import { ApiError } from "./api";

export type ErrorContext =
  | "general"
  | "sign-in"
  | "create-project"
  | "rename-project"
  | "delete-project"
  | "analysis"
  | "fixture"
  | "video"
  | "retry"
  | "cancel";

export type Problem = {
  /** The sentence to show. */
  message: string;
  /** The fixed API code, for secondary diagnostics only. */
  code: string;
  /** HTTP status, or 0 when the API could not be reached. */
  status: number;
  requestId?: string;
};

const URL_HELP =
  "Enter a public GitHub repository URL in the form https://github.com/owner/repository.";

/** Messages for codes, independent of context. */
const CODE_MESSAGES: Record<string, string> = {
  // 400
  oauth_state_rejected:
    "That sign-in attempt expired or was started in another browser. Start GitHub sign-in again.",

  // 401
  session_required: "Sign in to continue.",
  session_expired: "Your session expired. Sign in to continue.",
  unauthorized: "Your session expired. Sign in to continue.",
  invalid_development_identity:
    "That development identity is not available. Choose another identity.",
  oauth_denied: "GitHub sign-in was cancelled or not approved. Try again when you are ready.",
  oauth_rejected: "GitHub could not confirm your account. Start GitHub sign-in again.",

  // 403
  csrf_rejected:
    "This page's security token is out of date, so the request was refused. Reload the page and try again.",
  origin_rejected:
    "The request did not come from this RepoVox site, so it was refused. Reload the page and try again.",
  account_not_provisioned:
    "Your GitHub account has not been approved for RepoVox. Ask an administrator for access.",

  // 404
  not_found:
    "This record is not available. It may have been deleted, or it belongs to another account.",
  analysis_result_unavailable: "Verified analysis is not available yet, or it has expired.",
  story_not_available: "No engineering story is available for this video.",
  repository_not_found:
    "GitHub reports no public repository at that address. Check the owner and repository name.",

  // 409
  idempotency_conflict:
    "This action was already submitted with different details. Start a new submission.",
  terminal_conflict: "This job has already finished, so it can no longer be changed.",
  invalid_retry: "Only a failed or cancelled job can be retried, and only once.",
  analysis_reference_conflict:
    "This video job no longer matches its repository analysis. Start a new video job.",
  analysis_failed:
    "The repository analysis this depends on did not finish. Open the analysis job for details.",

  // 413
  request_too_large: "That request was too large. Shorten what you entered and try again.",

  // 422: input validation and repository resolution at admission
  invalid_request: "Some of the details you entered were not accepted. Check them and try again.",
  invalid_repository_url: URL_HELP,
  invalid_idempotency_key:
    "This submission could not be tracked safely. Reload the page and submit it again.",
  repository_private: "That repository is private. RepoVox analyses public repositories only.",
  repository_removed: "That repository has been removed from GitHub.",
  repository_identity_changed:
    "That repository was renamed or moved on GitHub. Update the project URL and try again.",
  github_access_denied: "GitHub refused access to that repository.",
  github_invalid_metadata: "GitHub returned repository details RepoVox could not verify.",
  github_redirect_rejected:
    "GitHub redirected the request somewhere RepoVox does not follow, so it stopped.",
  github_origin_blocked: "The repository download was refused by a network safety check.",
  github_address_blocked: "The repository download was refused by a network safety check.",

  // 422 / job codes: source safety and size limits (Stage 2 onwards)
  secret_detected:
    "Analysis stopped: the repository appears to contain a credential or secret, so RepoVox refused to process it.",
  archive_nested:
    "Analysis stopped: the repository archive contains nested archives, which RepoVox does not unpack.",
  archive_download_limit:
    "Analysis stopped: the repository download is larger than RepoVox's size limit.",
  archive_expansion_limit:
    "Analysis stopped: the repository archive expands beyond RepoVox's size limit.",
  archive_extraction_limit:
    "Analysis stopped: the repository archive is larger than RepoVox can extract.",
  archive_member_limit: "Analysis stopped: the repository contains too many files.",
  archive_unsafe_entry:
    "Analysis stopped: the repository archive contains a link or special file RepoVox does not extract.",
  archive_unsafe_path:
    "Analysis stopped: the repository archive contains an unsafe file path.",
  analysis_fact_limit:
    "Analysis stopped: the repository is too large to analyse within RepoVox's limits.",
  eligible_source_limit:
    "Analysis stopped: the repository has more source than RepoVox analyses in one job.",
  insufficient_evidence:
    "There was not enough verifiable source evidence to continue, so nothing was published.",
  source_changed:
    "The repository changed while it was being read. Start a new analysis to use the new commit.",

  // 429: quotas and rate limits
  monthly_quota: "This account has used its analysis quota for this month. It renews next month.",
  queue_quota:
    "You already have the maximum number of jobs waiting. Wait for one to finish or cancel one, then try again.",
  admission_rate: "Too many jobs were started in a short time. Wait a minute, then try again.",
  authentication_rate: "Too many sign-in attempts. Wait a minute, then try again.",
  project_quota:
    "This account has reached its project limit. Delete a project you no longer need, then try again.",
  github_rate_limited: "GitHub is limiting requests right now. Try again in a few minutes.",

  // 500
  internal_error:
    "Something went wrong on our side. Try again. If it keeps happening, share the reference below.",

  // 502
  oauth_unavailable: "GitHub sign-in is not responding. Try again in a moment.",

  // 503
  development_auth_disabled: "Development sign-in is turned off in this environment.",
  dependency_unavailable: "A required service is temporarily unavailable. Try again in a moment.",
  database_unavailable: "The database is temporarily unavailable. Try again in a moment.",
  secure_acquisition_unavailable: "That kind of job is not available in this environment.",
  video_generation_unavailable: "Narrated video generation is not enabled in this environment.",
  analysis_disabled: "Repository analysis is not enabled in this environment.",
  fixtures_disabled: "Synthetic fixtures are not enabled in this environment.",
  github_unavailable: "GitHub is not responding right now. Try again in a few minutes.",
  github_timeout: "GitHub took too long to respond. Try again in a few minutes.",
  retrieval_busy: "Too many downloads are in progress. Try again shortly.",
  object_unavailable: "A stored result is temporarily unavailable. Try again in a moment.",
  object_corrupt:
    "A stored result failed its integrity check, so RepoVox will not show it. Run the job again.",
  artifact_corrupt:
    "A stored result failed its integrity check, so RepoVox will not show it. Run the job again.",
  story_corrupt:
    "This video's engineering story failed its integrity check, so RepoVox will not show it.",

  // Client side
  connection_failed: "RepoVox could not be reached. Check your connection and try again.",
};

/** Context-specific wording for the same code, where the generic sentence would mislead. */
const CONTEXT_MESSAGES: Partial<Record<ErrorContext, Record<string, string>>> = {
  "create-project": {
    invalid_request: `Check the project name and URL. ${URL_HELP}`,
  },
  "rename-project": {
    invalid_request:
      "Enter a project name of 1 to 100 characters, without line breaks or control characters.",
    not_found:
      "This project is no longer in your workspace. It may have been deleted in another tab.",
  },
  "sign-in": {
    not_found: "That sign-in method is not available in this environment.",
  },
};

/** Fallbacks by HTTP status when a code is unknown. */
const STATUS_MESSAGES: Record<number, string> = {
  0: CODE_MESSAGES.connection_failed,
  400: "The request could not be understood. Reload the page and try again.",
  401: "Your session expired. Sign in to continue.",
  403: "That action is not allowed for this account.",
  404: CODE_MESSAGES.not_found,
  405: "That action is not available here.",
  409: "That action conflicts with the record's current state. Refresh and try again.",
  413: CODE_MESSAGES.request_too_large,
  422: "Some of the details you entered were not accepted. Check them and try again.",
  429: "A usage limit was reached. Wait a little, then try again.",
  500: CODE_MESSAGES.internal_error,
  502: "A service RepoVox depends on did not respond. Try again in a moment.",
  503: CODE_MESSAGES.dependency_unavailable,
  504: "A service RepoVox depends on took too long to respond. Try again in a moment.",
};

const GENERIC = "We could not complete that request. Try again.";

/** The message for an HTTP error, keyed by status and code (and optional context). */
export function describeError(
  status: number,
  code: string,
  context: ErrorContext = "general",
): string {
  return (
    CONTEXT_MESSAGES[context]?.[code] ??
    CODE_MESSAGES[code] ??
    STATUS_MESSAGES[status] ??
    (status >= 500 ? CODE_MESSAGES.internal_error : GENERIC)
  );
}

/** Turn any thrown value into a displayable problem. */
export function toProblem(cause: unknown, context: ErrorContext = "general"): Problem {
  if (cause instanceof ApiError)
    return {
      message: describeError(cause.status, cause.code, context),
      code: cause.code,
      status: cause.status,
      requestId: cause.requestId,
    };
  return { message: GENERIC, code: "client_error", status: 0 };
}

export const isUnauthorized = (cause: unknown): cause is ApiError =>
  cause instanceof ApiError && cause.status === 401;

/* Job outcomes ------------------------------------------------------------ */

/** Lifecycle and boundary codes a job can finish with. */
const JOB_MESSAGES: Record<string, string> = {
  phase1_fixture_boundary:
    "The fixture finished its infrastructure demonstration. Synthetic fixtures never analyze repositories or produce videos.",
  phase2_pipeline_boundary:
    "Static analysis is complete: stages 1–9 finished and their verified results are below. This job does not produce videos; narrated videos are created as video jobs from the project page.",
  fixture_transient: "The synthetic fixture simulated a temporary failure.",
  fixture_failure: "The synthetic fixture simulated a permanent failure.",
  owner_cancelled: "This job was cancelled.",
  job_deadline: "This job ran past its deadline and was stopped.",
  lease_expired: "A worker stopped responding while running this job, so the job was stopped.",
  analysis_timeout: "The repository analysis took too long and was stopped.",
  analysis_wait_timeout:
    "Waiting for the repository analysis took too long, so this video job was stopped.",
  parser_isolation_or_analysis_failed:
    "Source parsing could not run in its isolated sandbox, so the analysis stopped.",
  parser_timeout: "Parsing the source took too long, so the analysis stopped.",
  parser_resource_limit: "Parsing the source hit a resource limit, so the analysis stopped.",
  parser_isolation_unavailable:
    "Source parsing could not run in its isolated sandbox, so the analysis stopped.",
  analysis_failure: "The analysis stopped unexpectedly. Retry it, or start a new analysis.",
  narrator_unsupported: "The configured narrator is not supported by this RepoVox version.",
};

/** Families of related stage codes, matched by prefix after exact codes. */
const JOB_FAMILIES: [RegExp, string][] = [
  [/^archive_/, "Analysis stopped: the repository archive failed a safety check."],
  [/^github_/, "GitHub could not provide the repository snapshot."],
  [/^parser_/, "Parsing the source stopped at a safety or resource limit."],
  [/^(local_git|invalid_local|scratch_)/, "The local source workspace could not be prepared."],
  [
    /^(story_|unverified_claim|unsupported_|uncited_|uncitable_|false_citation|explanation_mismatch|excerpt_mismatch|analysis_mismatch|source_mismatch)/,
    "The engineering story could not be grounded in verified source evidence, so it was not published.",
  ],
  [
    /^(narration_|invalid_storyboard|storyboard_|duplicate_scene|grounding)/,
    "The narration could not be verified against its source citations, so it was not used.",
  ],
  [/^llm_/, "The narration language model did not return usable wording."],
  [/^(speech_|neural_tts_|neural_speech_)/, "Speech synthesis failed for this video."],
  [/^media_/, "Encoding or verifying the video file failed."],
  [/_overflow$/, "Text did not fit a frame's layout, so rendering stopped."],
  [/^(architecture_|duplicate_architecture|duplicate_element)/, "The architecture stage failed."],
];

/**
 * The sentence for a job's `error_code`, or null when there is none. HTTP-level codes that a
 * stage can also stop with (for example `secret_detected`) share their message.
 */
export function describeJobOutcome(code: string | null | undefined): string | null {
  if (!code) return null;
  if (JOB_MESSAGES[code]) return JOB_MESSAGES[code];
  if (CODE_MESSAGES[code]) return CODE_MESSAGES[code];
  for (const [pattern, message] of JOB_FAMILIES) if (pattern.test(code)) return message;
  return "This job stopped before it finished.";
}

/** Boundary codes that end a job normally rather than as a failure. */
export const BOUNDARY_CODES = new Set(["phase1_fixture_boundary", "phase2_pipeline_boundary"]);
