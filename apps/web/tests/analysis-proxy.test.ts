import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "../src/app/api/v1/[...path]/route";

afterEach(() => vi.unstubAllGlobals());

it.each([
  [
    "POST",
    "development/projects/11111111-1111-4111-8111-111111111111/analysis-jobs",
  ],
  ["GET", "development/jobs/22222222-2222-4222-8222-222222222222/analysis"],
  [
    "GET",
    "video-jobs/33333333-3333-4333-8333-333333333333/videos/44444444-4444-4444-8444-444444444444/story",
  ],
])("forwards the authenticated %s route %s", async (method, path) => {
  const fetch = vi.fn().mockResolvedValue(
    new Response('{"kind":"verify"}', {
      status: method === "POST" ? 202 : 200,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetch);
  const request = new NextRequest(`http://localhost:3000/api/v1/${path}`, {
    method,
    headers: {
      cookie: "rv_session=opaque",
      "x-csrf-token": "synthetic-csrf",
      "idempotency-key": "analysis-proxy-fixture",
    },
    ...(method === "POST" ? { body: '{"processing_acknowledged":true}' } : {}),
  });
  const response = await (method === "POST" ? POST : GET)(request, {
    params: Promise.resolve({ path: path.split("/") }),
  });
  expect(response.status).toBe(method === "POST" ? 202 : 200);
  const [url, options] = fetch.mock.calls[0];
  expect(url).toMatch(new RegExp(`/v1/${path}$`));
  expect(options.redirect).toBe("error");
  expect(options.headers.get("cookie")).toBe("rv_session=opaque");
  expect(options.headers.get("x-csrf-token")).toBe("synthetic-csrf");
  expect(response.headers.get("cache-control")).toBe("no-store");
});

it.each([
  "development/jobs/22222222-2222-4222-8222-222222222222/gold",
  "development/jobs/22222222-2222-4222-8222-222222222222/analysis?token=untrusted",
  "video-jobs/33333333-3333-4333-8333-333333333333/videos/44444444-4444-4444-8444-444444444444/story/raw",
  "video-jobs/33333333-3333-4333-8333-333333333333/story",
])("rejects an unapproved path or query %s without fetching", async (path) => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const request = new NextRequest(`http://localhost:3000/api/v1/${path}`);
  const response = await GET(request, {
    params: Promise.resolve({ path: path.split("?")[0].split("/") }),
  });
  expect(response.status).toBe(404);
  expect(fetch).not.toHaveBeenCalled();
});
