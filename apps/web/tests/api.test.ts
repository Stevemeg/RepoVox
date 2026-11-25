import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, readCsrfToken } from "../src/lib/api";

const fetcher = vi.fn();
const json = (value: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
const sent = (call = 0) => {
  const [url, init] = fetcher.mock.calls[call] as [string, RequestInit];
  return { url, init, headers: new Headers(init.headers) };
};

function setCookie(value: string) {
  document.cookie = `rv_csrf=${value};path=/`;
}

beforeEach(() => {
  fetcher.mockReset();
  // A fresh Response per call: a body can be read only once.
  fetcher.mockImplementation(() => Promise.resolve(json({ ok: true })));
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => {
  document.cookie = "rv_csrf=;path=/;max-age=0";
  vi.unstubAllGlobals();
});

describe("readCsrfToken", () => {
  it("returns the decoded rv_csrf value among other cookies", () => {
    expect(readCsrfToken("theme=dark; rv_csrf=a%2Bb%3D%3D; rv_session=x")).toBe("a+b==");
    expect(readCsrfToken("rv_csrf=plain-token")).toBe("plain-token");
  });
  it("falls back to the raw value when it is not valid percent-encoding", () => {
    expect(readCsrfToken("rv_csrf=50%zz")).toBe("50%zz");
  });
  it("ignores similarly named cookies and returns empty when absent", () => {
    expect(readCsrfToken("xrv_csrf=nope; rv_csrf_old=nope")).toBe("");
    expect(readCsrfToken("")).toBe("");
  });
});

describe("api", () => {
  it.each(["GET", "HEAD"] as const)(
    "%s sends neither a CSRF token nor a JSON content type",
    async (method) => {
      setCookie("token-123");
      fetcher.mockResolvedValue(new Response(method === "HEAD" ? null : "[]", { status: 200 }));
      await api("/projects", { method });
      const { url, init, headers } = sent();
      expect(url).toBe("/api/v1/projects");
      expect(init.method).toBe(method);
      expect(init.credentials).toBe("same-origin");
      expect(headers.has("x-csrf-token")).toBe(false);
      expect(headers.has("content-type")).toBe(false);
    },
  );

  it("a caller cannot attach mutation headers to a safe request", async () => {
    setCookie("token-123");
    await api("/projects", {
      headers: { "X-CSRF-Token": "forged", "Content-Type": "application/json" },
    });
    expect(sent().headers.has("x-csrf-token")).toBe(false);
    expect(sent().headers.has("content-type")).toBe(false);
  });

  it.each(["POST", "PATCH", "PUT", "DELETE"] as const)(
    "%s sends the decoded CSRF token and a JSON content type",
    async (method) => {
      setCookie("a%2Bb%3D%3D");
      await api("/projects/1", { method, body: "{}" });
      const { init, headers } = sent();
      expect(init.method).toBe(method);
      expect(headers.get("x-csrf-token")).toBe("a+b==");
      expect(headers.get("content-type")).toBe("application/json");
    },
  );

  it("passes a caller's stable idempotency key through unchanged", async () => {
    setCookie("t");
    const key = "4b0e7c1a-1111-4111-8111-111111111111";
    await api("/projects/1/video-jobs", { method: "POST", idempotencyKey: key, body: "{}" });
    await api("/projects/1/video-jobs", { method: "POST", idempotencyKey: key, body: "{}" });
    expect(sent(0).headers.get("idempotency-key")).toBe(key);
    expect(sent(1).headers.get("idempotency-key")).toBe(key);
  });

  it("sends no idempotency key unless the caller provides one", async () => {
    await api("/projects", { method: "POST", body: "{}" });
    expect(sent().headers.has("idempotency-key")).toBe(false);
  });

  it("raises the API's fixed code, status and request id, never server text", async () => {
    fetcher.mockResolvedValue(
      json({ error: { code: "csrf_rejected", request_id: "req-1", detail: "<b>x</b>" } }, 403),
    );
    const error = (await api("/projects", { method: "POST" }).catch(
      (cause: unknown) => cause,
    )) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "csrf_rejected", status: 403, requestId: "req-1" });
    expect(error.message).toBe("csrf_rejected");
  });

  it("uses the proxy's request id header when the body has none", async () => {
    fetcher.mockResolvedValue(json({ error: { code: "not_found" } }, 404, { "x-request-id": "hdr-9" }));
    await expect(api("/jobs/x")).rejects.toMatchObject({ requestId: "hdr-9", status: 404 });
  });

  it("maps an unreadable error body and an unreachable API to fixed codes", async () => {
    fetcher.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    await expect(api("/projects")).rejects.toMatchObject({ code: "request_failed", status: 502 });
    fetcher.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api("/projects")).rejects.toMatchObject({ code: "connection_failed", status: 0 });
  });

  it("returns undefined for 204 and parsed JSON otherwise", async () => {
    fetcher.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api("/auth/sign-out", { method: "POST" })).resolves.toBeUndefined();
    fetcher.mockResolvedValue(json([{ id: "p" }]));
    await expect(api("/projects")).resolves.toEqual([{ id: "p" }]);
  });
});
