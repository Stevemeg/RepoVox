// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  filterHistory,
  historyItems,
  isCompletedAnalysis,
  jobStatus,
  projectActivity,
  publishedVideos,
  videoJobStatus,
} from "../src/lib/job-status";
import type { Job, Project, Video, VideoJob } from "../src/lib/types";

const NOW = Date.parse("2026-11-26T12:00:00Z");
const project: Project = {
  id: "22222222-2222-4222-8222-222222222222",
  title: "Demo project",
  repository_url: "https://github.com/example/demo",
  status: "unprocessed",
  created_at: "2026-11-01T00:00:00Z",
};
const job = (overrides: Partial<Job> = {}): Job => ({
  id: "44444444-4444-4444-8444-444444444444",
  project_id: project.id,
  project_title: project.title,
  state: "failed",
  version: 3,
  synthetic: false,
  fixture: "normal",
  error_code: "phase2_pipeline_boundary",
  created_at: "2026-11-20T10:00:00Z",
  deadline: "2026-11-20T11:00:00Z",
  commit_sha: "a".repeat(40),
  repository_url: project.repository_url,
  ...overrides,
});
const video = (overrides: Partial<Video> = {}): Video => ({
  id: "55555555-5555-4555-8555-555555555555",
  category: "walkthrough",
  position: 0,
  title: "Walkthrough",
  checksum: "c".repeat(64),
  byte_count: 1000,
  metadata: {},
  published_at: "2026-11-20T10:30:00Z",
  expires_at: "2026-12-20T10:30:00Z",
  ...overrides,
});
const videoJob = (overrides: Partial<VideoJob> = {}): VideoJob => ({
  id: "66666666-6666-4666-8666-666666666666",
  project_id: project.id,
  analysis_job_id: job().id,
  state: "succeeded",
  version: 5,
  repository: "example/demo",
  commit_sha: "b".repeat(40),
  architecture: "published",
  error_code: null,
  created_at: "2026-11-21T10:00:00Z",
  deadline: "2026-11-21T11:00:00Z",
  finished_at: "2026-11-21T10:20:00Z",
  stages: [],
  videos: [video()],
  ...overrides,
});

describe("job status", () => {
  it("shows a Stage 9 analysis boundary as complete, keeping the raw record", () => {
    const status = jobStatus(job());
    expect(status).toMatchObject({
      group: "succeeded",
      label: "Analysis complete",
      tone: "succeeded",
      boundary: true,
      rawState: "failed",
      errorCode: "phase2_pipeline_boundary",
    });
    expect(isCompletedAnalysis(job())).toBe(true);
  });

  it("shows a fixture boundary as complete", () => {
    expect(
      jobStatus(job({ synthetic: true, error_code: "phase1_fixture_boundary" })),
    ).toMatchObject({ label: "Fixture complete", tone: "succeeded", boundary: true });
  });

  it("is strict about which boundary belongs to which job kind", () => {
    // A fixture code on an analysis (or the reverse) is not a normal end.
    expect(jobStatus(job({ error_code: "phase1_fixture_boundary" }))).toMatchObject({
      group: "failed",
      tone: "failed",
      boundary: false,
    });
    expect(
      jobStatus(job({ synthetic: true, error_code: "phase2_pipeline_boundary" })).boundary,
    ).toBe(false);
    expect(isCompletedAnalysis(job({ synthetic: true }))).toBe(false);
  });

  it("keeps real failures red and boundary codes on other states unchanged", () => {
    expect(jobStatus(job({ error_code: "secret_detected" }))).toMatchObject({
      label: "Failed",
      tone: "failed",
      group: "failed",
    });
    expect(jobStatus(job({ state: "cancelled" })).group).toBe("cancelled");
    expect(jobStatus(job({ state: "running", error_code: null })).group).toBe("active");
    expect(jobStatus(job({ state: "retry_wait", error_code: null })).label).toBe(
      "Waiting to retry",
    );
  });

  it("renders an unknown state as inert text without guessing a group", () => {
    expect(jobStatus(job({ state: "mystery_state", error_code: null }))).toMatchObject({
      group: "other",
      label: "mystery state",
      tone: "neutral",
    });
  });

  it("maps video job states", () => {
    expect(videoJobStatus(videoJob({ state: "awaiting_analysis" }))).toMatchObject({
      group: "active",
      label: "Awaiting analysis",
    });
    expect(videoJobStatus(videoJob({ state: "failed", error_code: "media_timeout" })).group).toBe(
      "failed",
    );
  });
});

describe("published videos", () => {
  it("counts only unexpired videos of succeeded jobs", () => {
    const jobs = [
      videoJob({ videos: [video(), video({ id: "v2", expires_at: "2026-11-25T00:00:00Z" })] }),
      videoJob({ id: "j2", state: "running", videos: [video({ id: "v3" })] }),
      videoJob({ id: "j3", videos: [video({ id: "v4", expires_at: "not a date" })] }),
    ];
    expect(publishedVideos(jobs, NOW).map((item) => item.id)).toEqual([video().id]);
  });
});

describe("unified history", () => {
  const jobs = [
    job(),
    job({ id: "fixture-1", synthetic: true, error_code: "phase1_fixture_boundary", created_at: "2026-11-22T10:00:00Z", commit_sha: null }),
    job({ id: "failed-1", error_code: "secret_detected", created_at: "2026-11-19T10:00:00Z" }),
  ];
  const videos = [videoJob(), videoJob({ id: "v-failed", state: "failed", error_code: "media_timeout", videos: [], commit_sha: "d".repeat(40), created_at: "2026-11-18T10:00:00Z" })];
  const items = historyItems(jobs, videos, [project], NOW);

  it("merges every job kind newest first", () => {
    expect(items.map((item) => [item.kind, item.id])).toEqual([
      ["fixture", "fixture-1"],
      ["video", videoJob().id],
      ["analysis", job().id],
      ["analysis", "failed-1"],
      ["video", "v-failed"],
    ]);
    expect(items[1]).toMatchObject({
      projectTitle: "Demo project",
      repositoryUrl: "https://github.com/example/demo",
      videoCount: 1,
    });
  });

  it("filters by type, status and plain-text search", () => {
    const only = (filters: Parameters<typeof filterHistory>[1]) =>
      filterHistory(items, filters).map((item) => item.id);
    expect(only({ type: "video", status: "all", query: "" })).toEqual([videoJob().id, "v-failed"]);
    expect(only({ type: "all", status: "succeeded", query: "" })).toEqual([
      "fixture-1",
      videoJob().id,
      job().id,
    ]);
    expect(only({ type: "analysis", status: "failed", query: "" })).toEqual(["failed-1"]);
    expect(only({ type: "all", status: "all", query: "BBBBBBBB" })).toEqual([videoJob().id]);
    expect(only({ type: "all", status: "all", query: "  github.com/EXAMPLE " })).toHaveLength(5);
    // Regex syntax is text, never a pattern.
    expect(only({ type: "all", status: "all", query: ".*" })).toEqual([]);
    expect(only({ type: "all", status: "cancelled", query: "" })).toEqual([]);
  });
});

describe("project activity", () => {
  it("calls a project with no jobs newly registered", () => {
    expect(projectActivity([], [], NOW)).toMatchObject({ key: "new", label: "Newly registered" });
    expect(projectActivity([], null, NOW).key).toBe("new");
  });

  it("prefers work in progress, then published videos, then a completed analysis", () => {
    expect(projectActivity([job()], [videoJob({ state: "running", videos: [] })], NOW).key).toBe(
      "rendering",
    );
    expect(projectActivity([job({ state: "queued", error_code: null })], [], NOW).key).toBe(
      "analyzing",
    );
    const published = projectActivity([job()], [videoJob()], NOW);
    expect(published).toMatchObject({ key: "published", label: "Videos published" });
    expect(published.description).toContain("1 published video is available");
    expect(projectActivity([job()], [], NOW).key).toBe("analyzed");
    // Expired videos no longer count as published.
    expect(
      projectActivity([job()], [videoJob({ videos: [video({ expires_at: "2026-11-01T00:00:00Z" })] })], NOW)
        .key,
    ).toBe("analyzed");
  });

  it("is honest about stopped jobs and fixture-only projects", () => {
    expect(projectActivity([job({ error_code: "secret_detected" })], [], NOW)).toMatchObject({
      key: "stopped",
      tone: "warning",
    });
    expect(
      projectActivity([job({ synthetic: true, error_code: "phase1_fixture_boundary" })], [], NOW),
    ).toMatchObject({ key: "fixtures-only" });
  });
});
