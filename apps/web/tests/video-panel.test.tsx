import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "../src/app/api/v1/[...path]/route";
import { VideoPanel, videoRoutes } from "../src/components/video-panel";

const job = "22222222-2222-4222-8222-222222222222";
afterEach(() => vi.unstubAllGlobals());

it("plays and offers download only through same-origin owner routes", () => {
  const { container } = render(<VideoPanel jobId={job} />);
  const video = screen.getByLabelText("Narrated repository explanation");
  expect(video).toHaveAttribute("controls");
  expect(container.querySelector("source")).toHaveAttribute(
    "src",
    `/api/v1/jobs/${job}/video`,
  );
  expect(container.querySelector("track")).toHaveAttribute(
    "src",
    `/api/v1/jobs/${job}/video/captions`,
  );
  expect(screen.getByText("Download MP4")).toHaveAttribute(
    "href",
    `/api/v1/jobs/${job}/video/download`,
  );
});

it("shows an unavailable state instead of a broken player", () => {
  render(<VideoPanel jobId={job} />);
  fireEvent.error(screen.getByLabelText("Narrated repository explanation"));
  expect(screen.getByRole("status")).toHaveTextContent("not available");
  expect(
    screen.queryByLabelText("Narrated repository explanation"),
  ).not.toBeInTheDocument();
});

it.each(["../../auth/session", "javascript:alert(1)", `${job}/../x`, ""])(
  "never builds a media URL from an invalid job id %s",
  (value) => {
    expect(videoRoutes(value)).toBeNull();
    const { container } = render(<VideoPanel jobId={value} />);
    expect(container.querySelector("video")).toBeNull();
  },
);

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
  const path = `jobs/${job}/video`;
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
  ["GET", `jobs/${job}/video/captions`],
  ["GET", `jobs/${job}/video/download`],
  ["POST", "projects/11111111-1111-4111-8111-111111111111/video-jobs"],
])("allows the %s %s media route", async (method, path) => {
  const fetch = vi.fn().mockResolvedValue(new Response("ok", { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const response = await (method === "POST" ? POST : GET)(
    new NextRequest(`http://localhost:3000/api/v1/${path}`, {
      method,
      ...(method === "POST"
        ? { body: '{"processing_acknowledged":true}' }
        : {}),
    }),
    { params: Promise.resolve({ path: path.split("/") }) },
  );
  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledOnce();
});

it.each([
  `jobs/${job}/video/../analysis`,
  `jobs/${job}/video/manifest`,
  `jobs/${job}/videos`,
  `jobs/${job}/video/download?path=/etc/passwd`,
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
