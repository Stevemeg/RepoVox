import { describe, expect, it } from "vitest";
import {
  formatBytes,
  formatDuration,
  formatRemaining,
  formatTimestamp,
  lifecycle,
  sortVideos,
  storyPath,
  videoRoutes,
} from "../src/lib/video-media";
import { EXPLAINER_A, EXPLAINER_B, JOB, WALKTHROUGH, videoJob } from "./story-fixture";

describe("media routes", () => {
  it("builds only same-origin owner routes from valid ids", () => {
    const base = `/api/v1/video-jobs/${JOB}/videos/${WALKTHROUGH}`;
    expect(videoRoutes(JOB, WALKTHROUGH)).toEqual({
      video: base,
      captions: `${base}/captions`,
      download: `${base}/download`,
      story: `${base}/story`,
    });
    expect(storyPath(JOB, WALKTHROUGH)).toBe(`/video-jobs/${JOB}/videos/${WALKTHROUGH}/story`);
  });

  it.each(["../../auth/session", "javascript:alert(1)", `${JOB}/../x`, "", "ABCDEF12-3456-4789-8ABC-DEF012345678"])(
    "never builds a media or story URL from an invalid id %s",
    (value) => {
      expect(videoRoutes(value, WALKTHROUGH)).toBeNull();
      expect(videoRoutes(JOB, value)).toBeNull();
      expect(storyPath(value, WALKTHROUGH)).toBeNull();
      expect(storyPath(JOB, value)).toBeNull();
    },
  );
});

describe("playlist order and lifecycle", () => {
  it("orders videos by position, then id, without changing the input", () => {
    const videos = videoJob().videos;
    expect(sortVideos(videos).map((video) => video.id)).toEqual([WALKTHROUGH, EXPLAINER_A, EXPLAINER_B]);
    expect(videos[0].id).toBe(EXPLAINER_B);
    const tied = [
      { ...videos[0], id: "b", position: 1 },
      { ...videos[0], id: "a", position: 1 },
      { ...videos[0], id: "c", position: Number.NaN },
    ];
    expect(sortVideos(tied).map((video) => video.id)).toEqual(["a", "b", "c"]);
  });

  it("treats a passed or unreadable expiry as expired", () => {
    const now = Date.parse("2026-11-26T12:00:00Z");
    expect(lifecycle({ expires_at: "2026-11-27T03:55:24Z" }, now)).toEqual({
      expired: false,
      remaining: Date.parse("2026-11-27T03:55:24Z") - now,
    });
    expect(lifecycle({ expires_at: "2026-11-26T12:00:00Z" }, now)).toEqual({ expired: true, remaining: 0 });
    expect(lifecycle({ expires_at: "not a date" }, now)).toEqual({ expired: true, remaining: 0 });
  });
});

describe("formatting", () => {
  it.each([
    [30_000, "less than a minute"],
    [45 * 60_000, "45 min"],
    [3 * 3_600_000, "3 h"],
    [15 * 3_600_000 + 55 * 60_000 + 30_000, "15 h 55 min"],
  ])("formats %d ms remaining as %s", (ms, text) => {
    expect(formatRemaining(ms)).toBe(text);
  });

  it.each([
    [999, "999 bytes"],
    [1, "1 byte"],
    [5_120, "5.1 kB"],
    [512_000, "512 kB"],
    [8_395_958, "8.4 MB"],
    [2_500_000_000, "2.50 GB"],
    [-1, "Unknown size"],
  ])("formats %d bytes as %s", (bytes, text) => {
    expect(formatBytes(bytes)).toBe(text);
  });

  it.each([
    [91.9, "1 min 32 s"],
    [45, "45 s"],
    [120, "2 min"],
    [0, null],
    [undefined, null],
    ["90", null],
  ])("formats a duration of %s as %s", (seconds, text) => {
    expect(formatDuration(seconds)).toBe(text);
  });

  it("formats exact timestamps with seconds, and unreadable ones honestly", () => {
    expect(formatTimestamp("2026-11-26T03:59:07Z")).toMatch(/2026/);
    expect(formatTimestamp("2026-11-26T03:59:07Z")).toMatch(/\d{2}:\d{2}:\d{2}/);
    expect(formatTimestamp("nope")).toBe("Unknown time");
  });
});
