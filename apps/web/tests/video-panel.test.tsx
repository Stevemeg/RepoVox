import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "../src/app/api/v1/[...path]/route";
import { VideoJobs, videoRoutes, type VideoJob } from "../src/components/video-panel";
import type { NarrationRecord } from "../src/lib/types";
import { VideoStudio } from "../src/components/video/video-studio";
import {
  DETERMINISTIC_NARRATION,
  EXPLAINER_A,
  EXPLAINER_B,
  FUTURE,
  JOB,
  PAST,
  PROJECT,
  PUBLISHED,
  WALKTHROUGH,
  respond,
  routedFetch,
  storyResponse,
  videoJob,
} from "./story-fixture";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const listUrl = `/api/v1/projects/${PROJECT}/video-jobs`;

/** jsdom has no TextTrack; give each <track> a minimal one, as a browser would. */
function withTextTracks() {
  const tracks = new WeakMap<HTMLTrackElement, { mode: TextTrackMode }>();
  Object.defineProperty(HTMLTrackElement.prototype, "track", {
    configurable: true,
    get(this: HTMLTrackElement) {
      if (!tracks.has(this)) tracks.set(this, { mode: "disabled" });
      return tracks.get(this);
    },
  });
  return () => delete (HTMLTrackElement.prototype as { track?: unknown }).track;
}

function stubStudio(job: VideoJob = videoJob(), story: () => Response = () => respond(storyResponse())) {
  const fetch = vi.fn(
    routedFetch({
      "/story": story,
      [listUrl]: () => respond([job]),
    }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const storyCalls = (fetch: ReturnType<typeof vi.fn>) =>
  fetch.mock.calls.filter(([url]) => String(url).endsWith("/story"));

const playlist = () => screen.getByRole("list", { name: /Videos in this job/ });
const entries = () => within(playlist()).getAllByRole("button");

describe("Video Studio stage and playlist", () => {
  it("shows one player and a playlist sorted by position, with the first video active", async () => {
    stubStudio();
    const { container } = render(<VideoStudio job={videoJob()} />);
    expect(container.querySelectorAll("video")).toHaveLength(1);
    const items = entries();
    expect(items.map((item) => item.getAttribute("data-video-id"))).toEqual([WALKTHROUGH, EXPLAINER_A, EXPLAINER_B]);
    expect(items.map((item) => item.getAttribute("aria-pressed"))).toEqual(["true", "false", "false"]);
    expect(within(items[0]).getByText("Walkthrough")).toBeVisible();
    expect(within(items[1]).getByText("Architecture")).toBeVisible();
    expect(within(items[0]).getByText("Repository walkthrough")).toBeVisible();
    expect(within(items[0]).getByText("1 min 32 s · 8.4 MB")).toBeVisible();
    expect(within(items[2]).getByText("1 min 41 s · 5.3 MB")).toBeVisible();
    expect(screen.getByLabelText("Repository walkthrough")).toHaveAttribute("controls");
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("switches videos through the playlist, keeping every URL same-origin and id-validated", async () => {
    const fetch = stubStudio();
    const { container } = render(<VideoStudio job={videoJob()} />);
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
    fireEvent.click(entries()[1]);
    expect(entries().map((item) => item.getAttribute("aria-pressed"))).toEqual(["false", "true", "false"]);
    const base = `/api/v1/video-jobs/${JOB}/videos/${EXPLAINER_A}`;
    expect(container.querySelectorAll("video")).toHaveLength(1);
    expect(container.querySelector("video")).toHaveAttribute("aria-label", "System architecture across 2 tiers");
    expect(container.querySelector("video")).toHaveAttribute("preload", "metadata");
    expect(container.querySelector("source")).toHaveAttribute("src", base);
    expect(container.querySelector("source")).toHaveAttribute("type", "video/mp4");
    expect(container.querySelector("track")).toHaveAttribute("src", `${base}/captions`);
    expect(screen.getByRole("link", { name: "Download MP4" })).toHaveAttribute("href", `${base}/download`);
    expect(screen.getByRole("link", { name: "Download MP4" })).toHaveAttribute("download");
    for (const element of container.querySelectorAll("[src], [href]")) {
      const url = element.getAttribute("src") ?? element.getAttribute("href")!;
      expect(url.startsWith("/api/v1/video-jobs/") || url.startsWith("https://github.com/")).toBe(true);
    }
    // Architecture explainers never carry a story, so none is requested for them.
    expect(storyCalls(fetch)).toHaveLength(1);
    expect(container.querySelector("video")?.getAttribute("style")).toBeNull();
  });

  it("loads every track hidden, without `default`, and keeps a viewer's own choice", async () => {
    const restore = withTextTracks();
    try {
      stubStudio();
      const job = videoJob();
      const { container, rerender } = render(<VideoStudio job={job} />);
      const element = container.querySelector("track") as HTMLTrackElement;
      expect(element).toHaveAttribute("kind", "captions");
      expect(element).toHaveAttribute("srclang", "en");
      expect(element).toHaveAttribute("label", "English captions");
      // `default` would start the track "showing", drawing a second caption box.
      expect(element).not.toHaveAttribute("default");
      expect(element.track.mode).toBe("hidden");
      element.track.mode = "showing";
      rerender(<VideoStudio job={job} />);
      expect(container.querySelector("track")).toBe(element);
      expect(element.track.mode).toBe("showing");
      // A newly selected video mounts a new track, also hidden.
      fireEvent.click(entries()[2]);
      const next = container.querySelector("track") as HTMLTrackElement;
      expect(next).not.toBe(element);
      expect(next).not.toHaveAttribute("default");
      expect(next.track.mode).toBe("hidden");
      expect(screen.getByText(/Captions are burned into every frame/)).toBeVisible();
      await screen.findByText(/This video carries no problem-to-solution story/);
    } finally {
      restore();
    }
  });

  it("shows the exact published and expiry times with a countdown", async () => {
    stubStudio();
    const { container } = render(<VideoStudio job={videoJob()} />);
    const published = container.querySelector(`time[datetime="${PUBLISHED}"]`);
    const expires = container.querySelector(`dd[data-expires-at="${FUTURE}"] time`);
    expect(published).toHaveTextContent(/2026/);
    expect(expires).toHaveAttribute("datetime", FUTURE);
    expect(container.querySelector('.expiry[data-expired="false"]')).toHaveTextContent(/^· in \d+ h/);
    expect(screen.getByText("b".repeat(64))).toBeVisible();
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("replaces an expired video's player with an expired state and requests no story", () => {
    const fetch = stubStudio();
    const expired = videoJob({
      videos: videoJob().videos.map((video) => ({ ...video, expires_at: PAST })),
    });
    const { container } = render(<VideoStudio job={expired} />);
    expect(container.querySelector("video")).toBeNull();
    expect(screen.queryByRole("link", { name: "Download MP4" })).toBeNull();
    expect(screen.getAllByText("This video has expired.")[0]).toBeVisible();
    expect(container.querySelector('.expiry[data-expired="true"]')).toHaveTextContent("Expired");
    expect(entries().every((item) => /Expired/.test(item.textContent ?? ""))).toBe(true);
    expect(screen.getByText(/its story is no longer available/)).toBeVisible();
    expect(storyCalls(fetch)).toHaveLength(0);
  });

  it("turns a video expired while the page stays open", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, toFake: ["setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(Date.parse("2026-11-26T12:00:00Z"));
    stubStudio();
    const job = videoJob({
      videos: videoJob().videos.map((video) => ({ ...video, expires_at: "2026-11-26T12:00:20Z" })),
    });
    const { container } = render(<VideoStudio job={job} />);
    expect(container.querySelector("video")).not.toBeNull();
    await act(async () => {
      vi.setSystemTime(Date.parse("2026-11-26T12:00:31Z"));
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(container.querySelector("video")).toBeNull();
    expect(screen.getAllByText("This video has expired.")[0]).toBeVisible();
  });

  it("shows an unavailable state instead of a broken player when media fails", async () => {
    stubStudio();
    render(<VideoStudio job={videoJob()} />);
    fireEvent.error(screen.getByLabelText("Repository walkthrough"));
    expect(screen.getByText(/this video is not available/)).toBeVisible();
    expect(screen.queryByLabelText("Repository walkthrough")).toBeNull();
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("offers no playlist for a single video", async () => {
    stubStudio();
    const job = videoJob({ architecture: "unsupported", videos: [videoJob().videos[1]] });
    const { container } = render(<VideoStudio job={job} />);
    expect(screen.queryByRole("list", { name: /Videos in this job/ })).toBeNull();
    expect(container.querySelectorAll("video")).toHaveLength(1);
    expect(screen.queryByText(/^Architecture explainer/)).toBeNull();
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });
});

describe("narration and voice provenance", () => {
  // Metadata is untrusted JSON: any shape may arrive, so the fixture is typed loosely.
  const withNarration = (narration: Record<string, unknown>) =>
    videoJob({
      videos: [
        {
          ...videoJob().videos[1],
          metadata: { duration_seconds: 91.9, narration: narration as unknown as NarrationRecord },
        },
      ],
    });

  it("states deterministic template wording and the exact Kokoro voice, never 'no AI model'", async () => {
    stubStudio();
    render(<VideoStudio job={videoJob()} />);
    const panel = screen.getByRole("region", { name: "Narration and voice" });
    expect(within(panel).getByText(/Deterministic template narration/)).toBeVisible();
    expect(within(panel).getByText(/No language model wrote or reworded it: all 8 scenes use/)).toBeVisible();
    expect(within(panel).getByText(/local neural text-to-speech voice \(Kokoro\)/)).toBeVisible();
    expect(within(panel).getByText("kokoro_onnx")).toBeVisible();
    expect(within(panel).getByText("kokoro-onnx")).toBeVisible();
    expect(within(panel).getByText("af_heart")).toBeVisible();
    expect(screen.queryByText(/No AI model|no paid service/i)).toBeNull();
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it.each([
    ["anthropic", /Anthropic's hosted API/, /hosted third-party service/],
    ["openai_compatible", /OpenAI-compatible hosted API/, /hosted third-party service/],
    ["ollama", /Ollama, a self-hosted model server/, /self-hosted model server run by the operator/],
  ])("names the %s provider, model and refined/fallback scene counts", async (provider, label, hosting) => {
    stubStudio();
    render(
      <VideoStudio
        job={withNarration({
          ...DETERMINISTIC_NARRATION,
          refiner: "grounded-llm-refiner-1.0",
          provider,
          model: "synthetic-model-1",
          scenes_total: 8,
          scenes_refined: 6,
          scenes_fallback: 2,
          refined_scene_ids: ["s1", "s2", "s3", "s4", "s5", "s6"],
          rejection_reasons: { s7: ["uncited_claim"], s8: ["unsupported_number"] },
        })}
      />,
    );
    const panel = screen.getByRole("region", { name: "Narration and voice" });
    expect(within(panel).getByText(/A language model reworded this narration/)).toHaveTextContent(label);
    expect(within(panel).getByText("synthetic-model-1")).toBeVisible();
    expect(within(panel).getByText(provider)).toBeVisible();
    expect(within(panel).getByText(/6 of 8 scenes use the model's wording/)).toHaveTextContent(
      "The other 2 scenes kept the deterministic template wording.",
    );
    expect(within(panel).getByText("uncited_claim")).toBeVisible();
    expect(within(panel).getByText("unsupported_number")).toBeVisible();
    expect(within(panel).getByText(hosting)).toBeVisible();
    expect(within(panel).queryByText(/Deterministic template narration/)).toBeNull();
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("states the fallback reason when no model wording was used at all", async () => {
    stubStudio();
    render(
      <VideoStudio
        job={withNarration({
          ...DETERMINISTIC_NARRATION,
          refiner: "grounded-llm-refiner-1.0",
          provider: "anthropic",
          model: "synthetic-model-1",
          scenes_refined: 0,
          scenes_fallback: 8,
          fallback_reason: "llm_timeout",
        })}
      />,
    );
    const panel = screen.getByRole("region", { name: "Narration and voice" });
    expect(within(panel).getByText(/0 of 8 scenes use the model's wording/)).toBeVisible();
    expect(within(panel).getByText("llm_timeout")).toBeVisible();
    expect(within(panel).getByText(/No model wording was used at all/)).toBeVisible();
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("describes an explainer's voice-only record and an unrecorded record honestly", async () => {
    stubStudio();
    render(<VideoStudio job={videoJob()} />);
    fireEvent.click(entries()[1]);
    const panel = screen.getByRole("region", { name: "Narration and voice" });
    expect(within(panel).getByText(/Not worded by a language model/)).toBeVisible();
    expect(within(panel).getByText("af_heart")).toBeVisible();

    const bare = videoJob({ videos: [{ ...videoJob().videos[1], metadata: { duration_seconds: 10 } }] });
    stubStudio(bare, () => respond({ error: { code: "story_not_available" } }, 404));
    render(<VideoStudio job={bare} />);
    expect(await screen.findByText(/Narration provenance was not recorded for this video/)).toBeVisible();
  });
});

describe("video jobs", () => {
  it("heads each job with a capitalized status badge that keeps the raw state", async () => {
    stubStudio();
    render(<VideoJobs projectId={PROJECT} />);
    const card = await screen.findByRole("article", { name: `Video job ${JOB.slice(0, 8)}` });
    const heading = within(card).getByRole("heading", { name: /^Video job / });
    expect(heading).toHaveTextContent("Succeeded");
    expect(heading.querySelector('[data-state="succeeded"]')).not.toBeNull();
    expect(within(card).getByText(/generated from verified source relationships/)).toHaveAttribute(
      "data-architecture",
      "published",
    );
    expect(within(card).getByText("Production stages: 6 of 6 succeeded")).toBeVisible();
    expect(card.querySelectorAll("video")).toHaveLength(1);
    expect(within(card).getAllByRole("link", { name: "Download MP4" })).toHaveLength(1);
    await within(card).findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("shows stage progress and a cancel action while a job is running, and polls", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const running = videoJob({
      state: "running",
      architecture: null,
      videos: [],
      stages: videoJob().stages.map((stage, index) => ({
        ...stage,
        state: index < 3 ? "succeeded" : index === 3 ? "running" : "pending",
      })),
    });
    const fetch = stubStudio(running);
    render(<VideoJobs projectId={PROJECT} />);
    const card = await screen.findByRole("article", { name: `Video job ${JOB.slice(0, 8)}` });
    expect(within(card).getByRole("heading", { name: /^Video job / })).toHaveTextContent("Running");
    expect(within(card).getByRole("status")).toHaveTextContent("Working: Rendering (stage 4 of 6).");
    expect(within(card).getByRole("progressbar")).toHaveAttribute("value", "3");
    expect(within(card).getByRole("button", { name: "Cancel video job" })).toBeEnabled();
    expect(card.querySelector("video")).toBeNull();
    const lists = () => fetch.mock.calls.filter(([url]) => String(url) === listUrl).length;
    expect(lists()).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    await waitFor(() => expect(lists()).toBe(2));
  });

  it("does not poll once every job is terminal", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetch = stubStudio();
    render(<VideoJobs projectId={PROJECT} />);
    await screen.findByRole("article", { name: `Video job ${JOB.slice(0, 8)}` });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fetch.mock.calls.filter(([url]) => String(url) === listUrl)).toHaveLength(1);
  });

  it("explains a failed video job in our own words, with remediation and the failed stage", async () => {
    const failed = videoJob({
      state: "failed",
      architecture: null,
      error_code: "narration_not_grounded",
      videos: [],
      stages: videoJob().stages.map((stage, index) => ({
        ...stage,
        state: index === 0 ? "succeeded" : index === 1 ? "failed" : "cancelled",
        error_code: index === 1 ? "narration_not_grounded" : null,
      })),
    });
    stubStudio(failed);
    render(<VideoJobs projectId={PROJECT} />);
    const card = await screen.findByRole("article", { name: `Video job ${JOB.slice(0, 8)}` });
    expect(within(card).getByRole("heading", { name: /^Video job / })).toHaveTextContent("Failed");
    expect(within(card).getByText(/narration could not be verified/)).toBeVisible();
    expect(within(card).getAllByText("Reference: narration_not_grounded").length).toBeGreaterThan(0);
    expect(card.querySelector('[data-stage="narration"][data-state="failed"]')).not.toBeNull();
    expect(screen.queryByText(/Status code/)).toBeNull();
  });

  it("says when a succeeded job's videos are no longer listed", async () => {
    stubStudio(videoJob({ videos: [] }));
    render(<VideoJobs projectId={PROJECT} />);
    expect(await screen.findByText(/No videos are listed for this job/)).toBeVisible();
  });

  it.each([
    ["extraction_failed", /architecture extraction failed/],
    ["rendering_failed", /rendering it failed/],
    ["not_completed", /did not complete/],
    ["unsupported", /evidence was not sufficient/],
  ])("reports architecture outcome %s without implying an explainer was published", async (architecture, message) => {
    stubStudio(videoJob({ architecture, videos: [videoJob().videos[1]] }));
    render(<VideoJobs projectId={PROJECT} />);
    const note = await screen.findByText(message);
    expect(note).toHaveAttribute("data-architecture", architecture);
    expect(screen.queryByText(/explainers were generated/)).toBeNull();
    expect(screen.getAllByRole("link", { name: "Download MP4" })).toHaveLength(1);
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("offers no player before a job has succeeded", async () => {
    stubStudio(videoJob({ state: "awaiting_analysis", architecture: null, videos: [] }));
    const { container } = render(<VideoJobs projectId={PROJECT} />);
    expect(await screen.findByRole("status")).toHaveTextContent("Waiting for verified static analysis");
    expect(container.querySelector("video")).toBeNull();
    expect(screen.getByText("Create narrated videos")).toBeDisabled();
  });

  it("submits a video job only after acknowledgement, with an idempotency key", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(respond([]))
      .mockResolvedValueOnce(respond(videoJob(), 202))
      .mockImplementation(routedFetch({ "/story": () => respond(storyResponse()), [listUrl]: () => respond([videoJob()]) }));
    vi.stubGlobal("fetch", fetch);
    render(<VideoJobs projectId={PROJECT} />);
    const button = screen.getByText("Create narrated videos");
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await screen.findByLabelText("Repository walkthrough");
    const [url, options] = fetch.mock.calls[1];
    expect(url).toBe(listUrl);
    expect(options.method).toBe("POST");
    expect(new Headers(options.headers).get("Idempotency-Key")).toMatch(/^[a-f0-9-]{36}$/);
    expect(JSON.parse(options.body)).toEqual({ processing_acknowledged: true });
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("retries a failed submission with the same idempotency key", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(respond([]))
      .mockResolvedValueOnce(respond({ error: { code: "admission_rate" } }, 429))
      .mockResolvedValueOnce(respond(videoJob(), 202))
      .mockImplementation(routedFetch({ "/story": () => respond(storyResponse()), [listUrl]: () => respond([videoJob()]) }));
    vi.stubGlobal("fetch", fetch);
    render(<VideoJobs projectId={PROJECT} />);
    fireEvent.click(screen.getByRole("checkbox"));
    const button = screen.getByText("Create narrated videos");
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Too many jobs were started/);
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await screen.findByLabelText("Repository walkthrough");
    const posts = fetch.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(2);
    const [first, second] = posts.map(([, init]) => new Headers(init.headers).get("Idempotency-Key"));
    expect(first).toMatch(/^[a-f0-9-]{36}$/);
    expect(second).toBe(first);
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
  });

  it("makes no claim about which narrator or voice was used before any video exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond([])));
    render(<VideoJobs projectId={PROJECT} />);
    await screen.findByRole("heading", { name: "Narrated videos" });
    expect(screen.queryByText(/No AI model|no paid service/i)).toBeNull();
  });

  it.each(["../../auth/session", "javascript:alert(1)", `${JOB}/../x`, ""])(
    "never builds a media URL from an invalid id %s (re-exported routes)",
    (value) => {
      expect(videoRoutes(value, WALKTHROUGH)).toBeNull();
      expect(videoRoutes(JOB, value)).toBeNull();
    },
  );
});

describe("media proxy", () => {
  it("forwards a byte range and returns partial video content", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([1, 2, 3, 4]), {
        status: 206,
        headers: {
          "content-type": "video/mp4",
          "content-range": "bytes 0-3/10",
          "accept-ranges": "bytes",
          "content-length": "4",
          "x-internal": "must-not-leak",
        },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const path = `video-jobs/${JOB}/videos/${WALKTHROUGH}`;
    const response = await GET(
      new NextRequest(`http://localhost:3000/api/v1/${path}`, {
        headers: { cookie: "rv_session=opaque", range: "bytes=0-3" },
      }),
      { params: Promise.resolve({ path: path.split("/") }) },
    );
    expect(response.status).toBe(206);
    expect(response.headers.get("content-range")).toBe("bytes 0-3/10");
    expect(response.headers.get("accept-ranges")).toBe("bytes");
    expect(response.headers.get("content-type")).toBe("video/mp4");
    expect(response.headers.get("x-internal")).toBeNull();
    expect(response.headers.get("cache-control")).toBe("no-store");
    const [url, options] = fetch.mock.calls[0];
    expect(url).toMatch(new RegExp(`/v1/${path}$`));
    expect(options.headers.get("range")).toBe("bytes=0-3");
    expect(options.headers.get("cookie")).toBe("rv_session=opaque");
  });

  it.each([
    ["GET", `video-jobs/${JOB}`],
    ["POST", `video-jobs/${JOB}/cancel`],
    ["GET", `video-jobs/${JOB}/videos/${WALKTHROUGH}/captions`],
    ["GET", `video-jobs/${JOB}/videos/${WALKTHROUGH}/download`],
    ["GET", `video-jobs/${JOB}/videos/${WALKTHROUGH}/story`],
    ["GET", `projects/${PROJECT}/video-jobs`],
    ["POST", `projects/${PROJECT}/video-jobs`],
  ])("allows the %s %s media route", async (method, path) => {
    const fetch = vi.fn().mockResolvedValue(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const response = await (method === "POST" ? POST : GET)(
      new NextRequest(`http://localhost:3000/api/v1/${path}`, {
        method,
        ...(method === "POST" ? { body: "{}" } : {}),
      }),
      { params: Promise.resolve({ path: path.split("/") }) },
    );
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledOnce();
  });

  it.each([
    `video-jobs/${JOB}/videos/${WALKTHROUGH}/../../../auth/session`,
    `video-jobs/${JOB}/videos/${WALKTHROUGH}/manifest`,
    `video-jobs/${JOB}/videos`,
    `video-jobs/${JOB}/videos/${WALKTHROUGH}/download?path=/etc/passwd`,
    `video-jobs/${JOB}/story`,
    `jobs/${JOB}/video`,
    `video-jobs`,
  ])("rejects an unapproved media path %s without fetching", async (path) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const response = await GET(new NextRequest(`http://localhost:3000/api/v1/${path}`), {
      params: Promise.resolve({ path: path.split("?")[0].split("/") }),
    });
    expect(response.status).toBe(404);
    expect(fetch).not.toHaveBeenCalled();
  });
});

