import { describe, expect, it } from "vitest";
import { ApiError } from "../src/lib/api";
import { describeError, describeJobOutcome, toProblem } from "../src/lib/errors";

describe("describeError", () => {
  it.each([
    // Auth and CSRF
    [401, "session_expired", /session expired.*sign in/i],
    [401, "session_required", /^Sign in to continue\.$/],
    [403, "csrf_rejected", /security token.*reload the page/i],
    [403, "origin_rejected", /did not come from this RepoVox site/i],
    [403, "account_not_provisioned", /not been approved.*administrator/i],
    [400, "oauth_state_rejected", /start GitHub sign-in again/i],
    // Size
    [413, "request_too_large", /too large/i],
    // 422 validation versus source-safety refusals: each has its own sentence
    [422, "invalid_repository_url", /https:\/\/github\.com\/owner\/repository/],
    [422, "invalid_idempotency_key", /could not be tracked safely/i],
    [422, "secret_detected", /credential or secret/i],
    [422, "archive_nested", /nested archives/i],
    [422, "archive_download_limit", /download is larger/i],
    [422, "analysis_fact_limit", /too large to analyse/i],
    [422, "repository_not_found", /no public repository/i],
    [422, "repository_private", /private/i],
    // Quotas and rate limits
    [429, "monthly_quota", /quota for this month/i],
    [429, "queue_quota", /maximum number of jobs waiting/i],
    [429, "admission_rate", /too many jobs were started/i],
    [429, "authentication_rate", /too many sign-in attempts/i],
    [429, "project_quota", /project limit/i],
    [429, "github_rate_limited", /GitHub is limiting requests/i],
    // Other statuses
    [404, "not_found", /not available.*another account/i],
    [409, "idempotency_conflict", /already submitted/i],
    [409, "terminal_conflict", /already finished/i],
    [500, "internal_error", /went wrong on our side/i],
    [502, "oauth_unavailable", /GitHub sign-in is not responding/i],
    [503, "development_auth_disabled", /development sign-in is turned off/i],
    [503, "dependency_unavailable", /temporarily unavailable/i],
    [503, "secure_acquisition_unavailable", /not available in this environment/i],
    [503, "video_generation_unavailable", /video generation is not enabled/i],
  ])("%i %s has its own actionable sentence", (status, code, expected) => {
    expect(describeError(status, code)).toMatch(expected);
  });

  it("keeps the quota, rate and security messages distinct from one another", () => {
    const messages = [
      ["monthly_quota", 429],
      ["project_quota", 429],
      ["authentication_rate", 429],
      ["invalid_repository_url", 422],
      ["secret_detected", 422],
      ["archive_nested", 422],
      ["analysis_fact_limit", 422],
    ].map(([code, status]) => describeError(status as number, code as string));
    expect(new Set(messages).size).toBe(messages.length);
  });

  it("explains invalid project input as a URL problem only when creating a project", () => {
    expect(describeError(422, "invalid_request", "create-project")).toMatch(
      /project name and URL.*https:\/\/github\.com\/owner\/repository/,
    );
    expect(describeError(422, "invalid_request", "video")).not.toMatch(/github\.com/);
  });

  it("falls back by status for unknown codes, and never echoes the code", () => {
    expect(describeError(429, "brand_new_limit")).toMatch(/usage limit/i);
    expect(describeError(503, "new_dependency")).toMatch(/temporarily unavailable/i);
    expect(describeError(418, "teapot")).toBe("We could not complete that request. Try again.");
    expect(describeError(599, "x")).toMatch(/our side/i);
    for (const status of [400, 401, 403, 404, 409, 413, 422, 429, 500, 502, 503])
      expect(describeError(status, "unknown_code_xyz")).not.toContain("unknown_code_xyz");
  });
});

describe("toProblem", () => {
  it("keeps the code and request id as secondary metadata", () => {
    expect(toProblem(new ApiError("project_quota", 429, "req-7"))).toEqual({
      message: describeError(429, "project_quota"),
      code: "project_quota",
      status: 429,
      requestId: "req-7",
    });
  });
  it("never surfaces a non-API exception's own message", () => {
    const problem = toProblem(new Error("SELECT * FROM users; stack at db.py:12"));
    expect(problem.message).toBe("We could not complete that request. Try again.");
    expect(JSON.stringify(problem)).not.toContain("SELECT");
  });
});

describe("describeJobOutcome", () => {
  it.each([
    ["phase1_fixture_boundary", /The fixture finished its infrastructure demonstration\./],
    ["phase2_pipeline_boundary", /stages 1–9 finished/],
    ["secret_detected", /credential or secret/],
    ["archive_unsafe_path", /unsafe file path/],
    ["archive_multiple_roots", /archive failed a safety check/],
    ["github_truncated_response", /GitHub could not provide/],
    ["story_problem_fabricated", /could not be grounded/],
    ["narration_not_grounded", /narration could not be verified/],
    ["neural_tts_unavailable", /Speech synthesis failed/],
    ["llm_timeout", /language model/],
    ["media_duration", /Encoding or verifying/],
    ["caption_overflow", /did not fit/],
    ["lease_expired", /worker stopped responding/],
    ["job_deadline", /past its deadline/],
    ["something_new", /stopped before it finished/],
  ])("%s", (code, expected) => {
    expect(describeJobOutcome(code)).toMatch(expected);
  });
  it("returns null when a job has no error code", () => {
    expect(describeJobOutcome(null)).toBeNull();
    expect(describeJobOutcome(undefined)).toBeNull();
    expect(describeJobOutcome("")).toBeNull();
  });
  it("never mentions phases in user-facing outcomes", () => {
    for (const code of ["phase1_fixture_boundary", "phase2_pipeline_boundary"])
      expect(describeJobOutcome(code)).not.toMatch(/phase/i);
  });
});
