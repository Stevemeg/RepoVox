import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "../src/app/api/v1/[...path]/route";
import {
  VideoJobs,
  VideoPlayer,
  videoRoutes,
  type VideoJob,
} from "../src/components/video-panel";

const project = "11111111-1111-4111-8111-111111111111";
const job = "22222222-2222-4222-8222-222222222222";
const walkthrough = "33333333-3333-4333-8333-333333333333";
const explainer = "44444444-4444-4444-8444-444444444444";
afterEach(() => vi.unstubAllGlobals());

const succeeded: VideoJob = {
  id: job,
  project_id: project,
  state: "succeeded",
  repository: "example/demo",
  commit_sha: "a".repeat(40),
  architecture: "supported",
  error_code: null,
  created_at: "2026-11-14T00:00:00Z",
  stages: [],
  videos: [
    {
      id: walkthrough,
      category: "walkthrough",
      title: "Repository walkthrough",
      byte_count: 10,
      checksum: "b".repeat(64),
      metadata: { duration_seconds: 91.9 },
    },
    {
      id: explainer,
      category: "architecture",
      title: "cycle() in cycle.py",
      byte_count: 10,
      checksum: "c".repeat(64),
      metadata: { media: { duration_seconds: 100.5 } },
    },
  ],
};

const respond = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

it("plays and offers download only through same-origin owner routes", () => {
  const { container } = render(
    <VideoPlayer jobId={job} video={succeeded.videos[0]} />,
  );
  expect(screen.getByLabelText("Repository walkthrough")).toHaveAttribute(
    "controls",
  );
  const base = `/api/v1/video-jobs/${job}/videos/${walkthrough}`;
  expect(container.querySelector("source")).toHaveAttribute("src", base);
  expect(container.querySelector("track")).toHaveAttribute(
    "src",
    `${base}/captions`,
  );
  expect(screen.getByText("Download MP4")).toHaveAttribute(
    "href",
    `${base}/download`,
  );
});

it("shows an unavailable state instead of a broken player", () => {
  render(<VideoPlayer jobId={job} video={succeeded.videos[0]} />);
  fireEvent.error(screen.getByLabelText("Repository walkthrough"));
  expect(screen.getByRole("status")).toHaveTextContent("not available");
});

it.each(["../../auth/session", "javascript:alert(1)", `${job}/../x`, ""])(
  "never builds a media URL from an invalid id %s",
  (value) => {
    expect(videoRoutes(value, walkthrough)).toBeNull();
    expect(videoRoutes(job, value)).toBeNull();
  },
);

it("lists both video categories for a succeeded job", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond([succeeded])));
  render(<VideoJobs projectId={project} />);
  expect(await screen.findByLabelText("Repository walkthrough")).toBeVisible();
  expect(screen.getByLabelText("cycle() in cycle.py")).toBeVisible();
  expect(screen.getByText(/Architecture explainer · 101 s/)).toBeVisible();
  expect(
    screen.getByText(/generated from verified source relationships/),
  ).toBeVisible();
  expect(screen.getAllByText("Download MP4")).toHaveLength(2);
});

it("offers no player before a job has succeeded and reports unsupported architecture", async () => {
  const waiting = { ...succeeded, state: "awaiting_analysis", videos: [] };
  const fetch = vi.fn().mockResolvedValue(respond([waiting]));
  vi.stubGlobal("fetch", fetch);
  const { container, unmount } = render(<VideoJobs projectId={project} />);
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Waiting for verified static analysis",
  );
  expect(container.querySelector("video")).toBeNull();
  expect(screen.getByText("Create narrated videos")).toBeDisabled();
  unmount();
  const plain = {
    ...succeeded,
    architecture: "unsupported",
    videos: succeeded.videos.slice(0, 1),
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond([plain])));
  render(<VideoJobs projectId={project} />);
  expect(await screen.findByText(/evidence was not sufficient/)).toBeVisible();
  expect(screen.getAllByText("Download MP4")).toHaveLength(1);
});

it("submits a video job only after acknowledgement, with an idempotency key", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(respond([]))
    .mockResolvedValueOnce(respond(succeeded, 202))
    .mockResolvedValue(respond([succeeded]));
  vi.stubGlobal("fetch", fetch);
  render(<VideoJobs projectId={project} />);
  const button = screen.getByText("Create narrated videos");
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByLabelText("Repository walkthrough");
  const [url, options] = fetch.mock.calls[1];
  expect(url).toBe(`/api/v1/projects/${project}/video-jobs`);
  expect(options.method).toBe("POST");
  expect(options.headers["Idempotency-Key"]).toMatch(/^[a-f0-9-]{36}$/);
  expect(JSON.parse(options.body)).toEqual({ processing_acknowledged: true });
});

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
  const path = `video-jobs/${job}/videos/${walkthrough}`;
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
  ["GET", `video-jobs/${job}`],
  ["POST", `video-jobs/${job}/cancel`],
  ["GET", `video-jobs/${job}/videos/${walkthrough}/captions`],
  ["GET", `video-jobs/${job}/videos/${walkthrough}/download`],
  ["GET", `projects/${project}/video-jobs`],
  ["POST", `projects/${project}/video-jobs`],
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
  `video-jobs/${job}/videos/${walkthrough}/../../../auth/session`,
  `video-jobs/${job}/videos/${walkthrough}/manifest`,
  `video-jobs/${job}/videos`,
  `video-jobs/${job}/videos/${walkthrough}/download?path=/etc/passwd`,
  `jobs/${job}/video`,
  `video-jobs`,
])("rejects an unapproved media path %s without fetching", async (path) => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const response = await GET(
    new NextRequest(`http://localhost:3000/api/v1/${path}`),
    { params: Promise.resolve({ path: path.split("?")[0].split("/") }) },
  );
  expect(response.status).toBe(404);
  expect(fetch).not.toHaveBeenCalled();
});
