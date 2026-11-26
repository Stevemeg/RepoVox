// @vitest-environment node
// Contract tests for the same-origin BFF proxy, src/app/api/v1/[...path]/route.ts, which is
// frozen: these tests pin what it forwards, what it refuses before any upstream request, and
// which headers cross it in each direction. Most cases stub `fetch` (so "never fetched" is
// observable); the redirect and wire-level header cases run against a real loopback HTTP
// server, so they exercise Node's actual fetch rather than a simulation of it.
import { createServer, type IncomingHttpHeaders, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { DELETE, GET, PATCH, POST } from "../src/app/api/v1/[...path]/route";

const HANDLERS = { GET, POST, PATCH, DELETE };
type Method = keyof typeof HANDLERS;
const PROJECT = "11111111-1111-4111-8111-111111111111";
const JOB = "22222222-2222-4222-8222-222222222222";
const VIDEO_JOB = "33333333-3333-4333-8333-333333333333";
const VIDEO = "44444444-4444-4444-8444-444444444444";
const ORIGIN = "http://localhost:3000";
const UPSTREAM = "http://upstream.test";
const NOT_FOUND = { error: { code: "not_found" } };

type Call = {
  search?: string;
  headers?: Record<string, string>;
  body?: BodyInit;
  /** The `[...path]` params; defaults to the route split on "/". */
  segments?: string[];
};
type NextRequestInit = NonNullable<ConstructorParameters<typeof NextRequest>[1]>;
function call(method: Method, route: string, init: Call = {}) {
  const request = new NextRequest(`${ORIGIN}/api/v1/${route}${init.search ?? ""}`, {
    method,
    headers: init.headers,
    body: init.body,
    // A streamed request body must declare half-duplex.
    ...(init.body instanceof ReadableStream ? { duplex: "half" } : {}),
  } as NextRequestInit);
  return HANDLERS[method](request, {
    params: Promise.resolve({ path: init.segments ?? route.split("/") }),
  });
}

function stubUpstream(respond: () => Response = () => Response.json({ ok: true })) {
  const fetch = vi.fn(async (input: string | URL | Request, options?: RequestInit) => {
    void input;
    void options;
    return respond();
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
const sent = (fetch: ReturnType<typeof stubUpstream>, index = 0) => {
  const [url, options] = fetch.mock.calls[index];
  return { url: String(url), options: options as Omit<RequestInit, "headers"> & { headers: Headers } };
};

beforeEach(() => {
  vi.stubEnv("REPOVOX_API_URL", UPSTREAM);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

// [method, route, query]: one entry per allowlisted route family and method the UI uses.
const FAMILIES: [Method, string, string?][] = [
  ["GET", "auth/config"],
  ["GET", "auth/session"],
  ["POST", "auth/sign-out"],
  ["POST", "auth/development/sign-in"],
  ["GET", "auth/github/login"],
  ["GET", "auth/github/callback", "?code=synthetic-code&state=synthetic-state"],
  ["GET", "projects"],
  ["POST", "projects"],
  ["GET", `projects/${PROJECT}`],
  ["PATCH", `projects/${PROJECT}`],
  ["DELETE", `projects/${PROJECT}`],
  ["GET", `projects/${PROJECT}/jobs`],
  ["POST", `projects/${PROJECT}/jobs`],
  ["GET", `projects/${PROJECT}/video-jobs`],
  ["POST", `projects/${PROJECT}/video-jobs`],
  ["GET", "jobs"],
  ["GET", `jobs/${JOB}`],
  ["POST", `jobs/${JOB}/cancel`],
  ["GET", `video-jobs/${VIDEO_JOB}`],
  ["POST", `video-jobs/${VIDEO_JOB}/cancel`],
  ["GET", `video-jobs/${VIDEO_JOB}/videos/${VIDEO}`],
  ["GET", `video-jobs/${VIDEO_JOB}/videos/${VIDEO}/captions`],
  ["GET", `video-jobs/${VIDEO_JOB}/videos/${VIDEO}/download`],
  ["GET", `video-jobs/${VIDEO_JOB}/videos/${VIDEO}/story`],
  ["POST", `development/projects/${PROJECT}/fixture-jobs`],
  ["POST", `development/projects/${PROJECT}/analysis-jobs`],
  ["POST", `development/jobs/${JOB}/retry`],
  ["GET", `development/jobs/${JOB}/analysis`],
];
const OAUTH = new Set(["auth/github/login", "auth/github/callback"]);

describe("allowlisted routes", () => {
  it.each(FAMILIES)("forwards %s %s to the same upstream path", async (method, route, search = "") => {
    const fetch = stubUpstream(() => Response.json({ ok: true }, { status: 200 }));
    const mutating = method !== "GET";
    const response = await call(method, route, {
      search,
      ...(mutating ? { body: '{"synthetic":true}', headers: { "content-type": "application/json" } } : {}),
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ ok: true });
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetch).toHaveBeenCalledTimes(1);
    const { url, options } = sent(fetch);
    expect(url).toBe(`${UPSTREAM}/v1/${route}${search}`);
    expect(options.method).toBe(method);
    expect(options.cache).toBe("no-store");
    expect(options.redirect).toBe(OAUTH.has(route) ? "manual" : "error");
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(options.signal?.aborted).toBe(false);
    expect(options.body).toBe(mutating ? '{"synthetic":true}' : undefined);
  });

  it("covers every route family named in the BFF contract", () => {
    const families = new Set(
      FAMILIES.map(([, route]) =>
        route
          .replaceAll(PROJECT, "{id}")
          .replaceAll(JOB, "{id}")
          .replaceAll(VIDEO_JOB, "{id}")
          .replaceAll(VIDEO, "{vid}"),
      ),
    );
    expect([...families].sort()).toEqual(
      [
        "auth/config",
        "auth/session",
        "auth/sign-out",
        "auth/development/sign-in",
        "auth/github/login",
        "auth/github/callback",
        "projects",
        "projects/{id}",
        "projects/{id}/jobs",
        "projects/{id}/video-jobs",
        "jobs",
        "jobs/{id}",
        "jobs/{id}/cancel",
        "video-jobs/{id}",
        "video-jobs/{id}/cancel",
        "video-jobs/{id}/videos/{vid}",
        "video-jobs/{id}/videos/{vid}/captions",
        "video-jobs/{id}/videos/{vid}/download",
        "video-jobs/{id}/videos/{vid}/story",
        "development/projects/{id}/fixture-jobs",
        "development/projects/{id}/analysis-jobs",
        "development/jobs/{id}/retry",
        "development/jobs/{id}/analysis",
      ].sort(),
    );
  });
});

describe("refused before any upstream request", () => {
  async function expectRefused(response: Response, fetch: ReturnType<typeof stubUpstream>) {
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual(NOT_FOUND);
    expect(fetch).not.toHaveBeenCalled();
  }

  it.each([
    [["projects", "..", "jobs"]],
    [["..", "..", "etc", "passwd"]],
    [["projects", PROJECT, "..", "..", "admin"]],
    [["projects", "%2e%2e", "jobs"]],
    [["projects", "%2E%2E", "%2E%2E", "admin"]],
    [["jobs", "%2e%2e%2fadmin"]],
    [["jobs", "..%2f..%2fadmin"]],
    [["projects", ".", "jobs"]],
    [["projects", "", "jobs"]],
    [["projects\\..\\jobs"]],
    [["projects", "http:", "", "evil.test"]],
    [["projects", `${PROJECT}%00`]],
    [["projects", "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee".toUpperCase()]],
    [["Projects"]],
    [[]],
  ])("rejects the traversal or malformed path %j", async (segments) => {
    for (const method of ["GET", "POST"] as const) {
      const fetch = stubUpstream();
      await expectRefused(await call(method, "probe", { segments }), fetch);
      vi.unstubAllGlobals();
    }
  });

  it.each([
    "admin",
    "internal/metrics",
    "health",
    "auth",
    "auth/development/sign-in/extra",
    "auth/github/logout",
    `projects/${PROJECT}/secrets`,
    `projects/${PROJECT}/jobs/${JOB}`,
    "video-jobs",
    `video-jobs/${VIDEO_JOB}/videos`,
    `video-jobs/${VIDEO_JOB}/story`,
    `video-jobs/${VIDEO_JOB}/videos/${VIDEO}/story/raw`,
    `video-jobs/${VIDEO_JOB}/videos/${VIDEO}/thumbnail`,
    `jobs/${JOB}/cancel/now`,
    `jobs/${JOB}/analysis`,
    "development/projects",
    `development/projects/${PROJECT}/gold`,
    `development/jobs/${JOB}/reveal`,
    "private/gold",
  ])("rejects the unknown route %s", async (route) => {
    const fetch = stubUpstream();
    await expectRefused(await call("GET", route), fetch);
  });

  it.each(FAMILIES.filter(([, route]) => route !== "auth/github/callback"))(
    "rejects a query string on %s %s",
    async (method, route) => {
      for (const search of ["?x=1", "?target=https://example.test", "?redirect=%2F%2Fevil.test"]) {
        const fetch = stubUpstream();
        await expectRefused(await call(method, route, { search }), fetch);
        vi.unstubAllGlobals();
      }
    },
  );

  it("accepts a GitHub callback query up to 2048 characters and refuses a longer one", async () => {
    // `search` includes the leading "?", so the limit is "?" plus 2047 characters.
    const atLimit = `?code=${"c".repeat(2048 - "?code=".length)}`;
    expect(atLimit).toHaveLength(2048);
    const fetch = stubUpstream(() => new Response(null, { status: 302, headers: { location: "/" } }));
    const accepted = await call("GET", "auth/github/callback", { search: atLimit });
    expect(accepted.status).toBe(302);
    expect(sent(fetch).url).toBe(`${UPSTREAM}/v1/auth/github/callback${atLimit}`);
    vi.unstubAllGlobals();

    const refused = stubUpstream();
    await expectRefused(await call("GET", "auth/github/callback", { search: `${atLimit}c` }), refused);
  });

  it.each(["auth/github/login", "auth/github/callback"])(
    "allows only GET on the OAuth redirect hop %s",
    async (route) => {
      for (const method of ["POST", "PATCH", "DELETE"] as const) {
        const fetch = stubUpstream();
        await expectRefused(await call(method, route, { body: "{}" }), fetch);
        vi.unstubAllGlobals();
      }
    },
  );
});

describe("request body cap", () => {
  const limit = 16384;

  it("forwards a body of exactly 16,384 bytes unchanged", async () => {
    const fetch = stubUpstream(() => Response.json({ id: PROJECT }, { status: 201 }));
    const body = "x".repeat(limit);
    const response = await call("POST", "projects", { body });
    expect(response.status).toBe(201);
    expect(sent(fetch).options.body).toBe(body);
  });

  it.each(["POST", "PATCH", "DELETE"] as const)(
    "answers 413 request_too_large for a %s body of 16,385 bytes without fetching",
    async (method) => {
      const fetch = stubUpstream();
      const response = await call(method, method === "POST" ? "projects" : `projects/${PROJECT}`, {
        body: "x".repeat(limit + 1),
      });
      expect(response.status).toBe(413);
      expect(await response.json()).toEqual({ error: { code: "request_too_large" } });
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("counts bytes, not characters", async () => {
    const fits = stubUpstream();
    // "é" is two bytes in UTF-8: 8,192 of them are exactly 16,384 bytes.
    expect((await call("POST", "projects", { body: "é".repeat(8192) })).status).toBe(200);
    expect(sent(fits).options.body).toBe("é".repeat(8192));
    vi.unstubAllGlobals();

    const over = stubUpstream();
    expect((await call("POST", "projects", { body: "é".repeat(8193) })).status).toBe(413);
    expect(over).not.toHaveBeenCalled();
  });

  it("caps the running total of a streamed body", async () => {
    const fetch = stubUpstream();
    const chunk = new Uint8Array(4096).fill(120);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let index = 0; index < 4; index += 1) controller.enqueue(chunk);
        controller.enqueue(new Uint8Array([120]));
        controller.close();
      },
    });
    const response = await call("POST", "projects", { body });
    expect(response.status).toBe(413);
    expect(fetch).not.toHaveBeenCalled();
  });
});

const FORWARDED = {
  cookie: "rv_session=opaque-session; rv_csrf=synthetic-csrf",
  origin: ORIGIN,
  "content-type": "application/json",
  "x-csrf-token": "synthetic-csrf",
  "idempotency-key": "proxy-security-fixture",
  "x-request-id": "req-proxy-security-1",
  range: "bytes=0-99",
};
const DROPPED = {
  authorization: "Bearer stolen-token",
  "proxy-authorization": "Basic c3RvbGVu",
  "x-api-key": "stolen-key",
  "x-forwarded-for": "203.0.113.7",
  "x-forwarded-host": "evil.test",
  "x-forwarded-proto": "http",
  "x-real-ip": "203.0.113.7",
  forwarded: "for=203.0.113.7;host=evil.test",
  host: "evil.test",
  "user-agent": "hostile-agent/1.0",
  "x-middleware-subrequest": "middleware",
};

describe("header hygiene", () => {
  it("forwards only the allowlisted request headers", async () => {
    const fetch = stubUpstream();
    await call("POST", "projects", { headers: { ...FORWARDED, ...DROPPED }, body: "{}" });
    const { headers } = sent(fetch).options;
    expect([...headers.keys()].sort()).toEqual(Object.keys(FORWARDED).sort());
    for (const [name, value] of Object.entries(FORWARDED)) expect(headers.get(name), name).toBe(value);
    for (const name of Object.keys(DROPPED)) expect(headers.get(name), name).toBeNull();
  });

  function hostileUpstream(status = 200) {
    const headers = new Headers({
      "content-type": "application/json",
      "x-request-id": "req-upstream-1",
      "cache-control": "public, max-age=31536000",
      server: "uvicorn",
      "x-powered-by": "upstream",
      location: "https://evil.test/",
      "content-range": "bytes 0-99/1000",
      "accept-ranges": "bytes",
      "content-length": "2",
      "content-disposition": 'attachment; filename="walkthrough.mp4"',
      "access-control-allow-origin": "*",
      etag: '"upstream"',
    });
    headers.append("set-cookie", "rv_session=rotated; Path=/; HttpOnly; SameSite=Lax");
    headers.append("set-cookie", "rv_csrf=rotated; Path=/; SameSite=Lax");
    return () => new Response(status === 302 ? null : "{}", { status, headers });
  }
  const CROSSES_ALWAYS = ["content-type", "x-request-id"];
  const MEDIA_ONLY = ["content-range", "accept-ranges", "content-length", "content-disposition"];
  const NEVER = ["server", "x-powered-by", "access-control-allow-origin", "etag"];

  it("returns only safe response headers on a JSON route and forces no-store", async () => {
    stubUpstream(hostileUpstream());
    const response = await call("GET", "projects");
    for (const name of CROSSES_ALWAYS) expect(response.headers.get(name), name).not.toBeNull();
    expect(response.headers.getSetCookie()).toEqual([
      "rv_session=rotated; Path=/; HttpOnly; SameSite=Lax",
      "rv_csrf=rotated; Path=/; SameSite=Lax",
    ]);
    expect(response.headers.get("cache-control")).toBe("no-store");
    for (const name of [...NEVER, ...MEDIA_ONLY, "location"]) expect(response.headers.get(name), name).toBeNull();
  });

  it("adds byte-range and download headers only on video media routes", async () => {
    for (const route of [
      `video-jobs/${VIDEO_JOB}/videos/${VIDEO}`,
      `video-jobs/${VIDEO_JOB}/videos/${VIDEO}/captions`,
      `video-jobs/${VIDEO_JOB}/videos/${VIDEO}/download`,
    ]) {
      stubUpstream(hostileUpstream(206));
      const response = await call("GET", route, { headers: { range: "bytes=0-99" } });
      expect(response.status, route).toBe(206);
      for (const name of [...CROSSES_ALWAYS, ...MEDIA_ONLY]) expect(response.headers.get(name), `${route} ${name}`).not.toBeNull();
      expect(response.headers.get("cache-control"), route).toBe("no-store");
      for (const name of [...NEVER, "location"]) expect(response.headers.get(name), `${route} ${name}`).toBeNull();
      vi.unstubAllGlobals();
    }
    // The story is JSON, not media: no range headers cross for it.
    stubUpstream(hostileUpstream());
    const story = await call("GET", `video-jobs/${VIDEO_JOB}/videos/${VIDEO}/story`);
    for (const name of MEDIA_ONLY) expect(story.headers.get(name), `story ${name}`).toBeNull();
  });

  it("passes the redirect Location through only on the OAuth hop", async () => {
    stubUpstream(hostileUpstream(302));
    const login = await call("GET", "auth/github/login");
    expect(login.status).toBe(302);
    expect(login.headers.get("location")).toBe("https://evil.test/");
    expect(login.headers.get("cache-control")).toBe("no-store");
    for (const name of NEVER) expect(login.headers.get(name), name).toBeNull();
  });

  it("answers 503 dependency_unavailable when the upstream request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const response = await call("GET", "projects");
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: { code: "dependency_unavailable" } });
  });
});

describe("against a real loopback upstream", () => {
  type Seen = { method: string; url: string; headers: IncomingHttpHeaders; body: string };
  const seen: Seen[] = [];
  let server: Server;
  let base = "";

  beforeAll(async () => {
    server = createServer((request, response) => {
      const chunks: Buffer[] = [];
      request.on("data", (chunk: Buffer) => chunks.push(chunk));
      request.on("end", () => {
        seen.push({
          method: request.method ?? "",
          url: request.url ?? "",
          headers: request.headers,
          body: Buffer.concat(chunks).toString("utf-8"),
        });
        if (request.url === "/v1/auth/github/login") {
          response.writeHead(302, { location: "https://github.com/login/oauth/authorize?client_id=synthetic" });
          response.end();
        } else if (request.url?.startsWith("/v1/projects")) {
          // Any redirect on an ordinary route must be refused, never followed.
          response.writeHead(request.url === "/v1/projects" ? 302 : 307, { location: "http://evil.test/steal" });
          response.end();
        } else {
          response.writeHead(200, { "content-type": "application/json" });
          response.end('{"ok":true}');
        }
      });
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });
  afterAll(() => new Promise<void>((resolve) => server.close(() => resolve())));
  beforeEach(() => {
    seen.length = 0;
    vi.stubEnv("REPOVOX_API_URL", base);
  });

  it.each([
    ["GET", "projects"],
    ["PATCH", `projects/${PROJECT}`],
  ] as const)("turns an upstream redirect on %s %s into 503 dependency_unavailable", async (method, route) => {
    const response = await call(method, route, method === "PATCH" ? { body: '{"title":"x"}' } : {});
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: { code: "dependency_unavailable" } });
    expect(response.headers.get("location")).toBeNull();
    // The redirect target was never requested.
    expect(seen.map((entry) => entry.url)).toEqual([`/v1/${route}`]);
  });

  it("hands the OAuth redirect to the browser instead of following it", async () => {
    const response = await call("GET", "auth/github/login");
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe("https://github.com/login/oauth/authorize?client_id=synthetic");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(seen).toHaveLength(1);
  });

  it("puts only allowlisted headers and the exact body on the wire", async () => {
    const body = '{"processing_acknowledged":true}';
    const response = await call("POST", `jobs/${JOB}/cancel`, { headers: { ...FORWARDED, ...DROPPED }, body });
    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
    const [request] = seen;
    expect(request.method).toBe("POST");
    expect(request.url).toBe(`/v1/jobs/${JOB}/cancel`);
    expect(request.body).toBe(body);
    for (const [name, value] of Object.entries(FORWARDED)) expect(request.headers[name], name).toBe(value);
    // Spoofable identity headers never arrive; Host names the upstream, and the client's
    // User-Agent is replaced by the server runtime's own.
    for (const name of ["authorization", "proxy-authorization", "x-api-key", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded", "x-middleware-subrequest"])
      expect(request.headers[name], name).toBeUndefined();
    expect(request.headers.host).toBe(base.slice("http://".length));
    expect(request.headers["user-agent"]).not.toBe(DROPPED["user-agent"]);
  });

  it("answers 503 when nothing is listening upstream", async () => {
    const closed = createServer();
    await new Promise<void>((resolve) => closed.listen(0, "127.0.0.1", resolve));
    const port = (closed.address() as AddressInfo).port;
    await new Promise<void>((resolve) => closed.close(() => resolve()));
    vi.stubEnv("REPOVOX_API_URL", `http://127.0.0.1:${port}`);
    const response = await call("GET", "auth/session");
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: { code: "dependency_unavailable" } });
  });
});
