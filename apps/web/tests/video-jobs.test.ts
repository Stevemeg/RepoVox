import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/lib/api";
import { fetchVideoJobs, mapBounded, VIDEO_JOB_CONCURRENCY } from "../src/lib/video-jobs";

const ids = Array.from(
  { length: 9 },
  (_, index) => `22222222-2222-4222-8222-${String(index).padStart(12, "0")}`,
);
const respond = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
afterEach(() => vi.unstubAllGlobals());

describe("mapBounded", () => {
  it("never runs more than the limit at once and keeps input order", async () => {
    let running = 0;
    let peak = 0;
    const result = await mapBounded([5, 1, 4, 2, 3, 0], 2, async (value) => {
      running += 1;
      peak = Math.max(peak, running);
      await new Promise((resolve) => setTimeout(resolve, value));
      running -= 1;
      return value * 10;
    });
    expect(result).toEqual([50, 10, 40, 20, 30, 0]);
    expect(peak).toBe(2);
  });

  it("stops taking new work and rejects once aborted", async () => {
    const controller = new AbortController();
    const seen: number[] = [];
    const run = mapBounded(
      [1, 2, 3, 4, 5],
      1,
      async (value) => {
        seen.push(value);
        if (value === 2) controller.abort();
        return value;
      },
      controller.signal,
    );
    await expect(run).rejects.toBeDefined();
    expect(seen).toEqual([1, 2]);
  });

  it("handles an empty list", async () => {
    expect(await mapBounded([], 4, async () => 1)).toEqual([]);
  });
});

describe("fetchVideoJobs", () => {
  it("loads each project through its own route with bounded concurrency and no CSRF header", async () => {
    let running = 0;
    let peak = 0;
    const fetcher = vi.fn(async (url: string, init: RequestInit) => {
      running += 1;
      peak = Math.max(peak, running);
      await new Promise((resolve) => setTimeout(resolve, 2));
      running -= 1;
      expect(new Headers(init.headers).get("x-csrf-token")).toBeNull();
      expect(init.method).toBe("GET");
      return respond([{ id: `job-for-${url.split("/")[4]}` }]);
    });
    vi.stubGlobal("fetch", fetcher);
    const results = await fetchVideoJobs(ids);
    expect(peak).toBeLessThanOrEqual(VIDEO_JOB_CONCURRENCY);
    expect(fetcher).toHaveBeenCalledTimes(ids.length);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(
      ids.map((id) => `/api/v1/projects/${id}/video-jobs`),
    );
    expect(results.every((result) => result.ok)).toBe(true);
  });

  it("reports one project's failure without failing the others", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.includes(ids[1])
          ? respond({ error: { code: "dependency_unavailable", request_id: "req-7" } }, 503)
          : url.includes(ids[2])
            ? respond({ error: { code: "not_found" } }, 404)
            : respond([]),
      ),
    );
    const results = await fetchVideoJobs(ids.slice(0, 4));
    expect(results.map((result) => [result.projectId, result.ok])).toEqual([
      [ids[0], true],
      [ids[1], false],
      // A deleted project has no reachable video jobs: empty, not a failure.
      [ids[2], true],
      [ids[3], true],
    ]);
    const failed = results[1];
    expect(!failed.ok && failed.error).toBeInstanceOf(ApiError);
    expect(!failed.ok && (failed.error as ApiError).requestId).toBe("req-7");
  });

  it("never puts a malformed id into a URL", async () => {
    const fetcher = vi.fn(async () => respond([]));
    vi.stubGlobal("fetch", fetcher);
    const upper = "abcdef12-3456-4789-8abc-def012345678".toUpperCase();
    const results = await fetchVideoJobs(["../auth/session", "not-a-uuid", upper, `${ids[0]}/x`, ids[0]]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(results.map((result) => result.projectId)).toEqual([ids[0]]);
  });

  it("rejects on abort instead of reporting failures", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_, reject) =>
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            ),
          ),
      ),
    );
    const run = fetchVideoJobs(ids, { signal: controller.signal });
    controller.abort();
    await expect(run).rejects.toBeDefined();
  });
});
