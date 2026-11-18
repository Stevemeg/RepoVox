import { render, screen } from "@testing-library/react";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "../src/app/api/v1/[...path]/route";
import { Workspace } from "../src/components/workspace";
import { authProvider } from "../src/lib/auth";

vi.mock("next/navigation", () => ({
  usePathname: () => "/sign-in",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("sign-in page", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(json({ error: { code: "session_required" } }, 401)),
    );
  });
  it("offers Continue with GitHub, and no development identity, for the GitHub adapter", () => {
    render(<Workspace authProvider="github" />);
    const link = screen.getByRole("link", { name: /Continue with GitHub/ });
    expect(link).toHaveAttribute("href", "/api/v1/auth/github/login");
    expect(screen.queryByRole("button", { name: /Alex Chen/ })).toBeNull();
    expect(screen.queryByText(/LOCAL DEVELOPMENT/)).toBeNull();
  });
  it("keeps the development identities for the development adapter", () => {
    render(<Workspace authProvider="dev" />);
    expect(screen.getByRole("button", { name: /Alex Chen/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /Sam Rivera/ })).toBeVisible();
    expect(
      screen.queryByRole("link", { name: /Continue with GitHub/ }),
    ).toBeNull();
  });
  it("offers no sign-in when the API cannot say which adapter is active", () => {
    render(<Workspace authProvider="unavailable" />);
    expect(screen.getByText("Sign-in is unavailable")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Alex Chen/ })).toBeNull();
    expect(
      screen.queryByRole("link", { name: /Continue with GitHub/ }),
    ).toBeNull();
  });
});

describe("authProvider", () => {
  it.each([
    [json({ auth_provider: "github", github_oauth_enabled: true }), "github"],
    [json({ auth_provider: "dev", github_oauth_enabled: false }), "dev"],
    [json({ auth_provider: "something-else" }), "unavailable"],
    [json({ error: { code: "internal_error" } }, 500), "unavailable"],
  ])("reads the adapter the API reports", async (answer, expected) => {
    const fetch = vi.fn().mockResolvedValue(answer);
    vi.stubGlobal("fetch", fetch);
    expect(await authProvider("http://api:8000")).toBe(expected);
    expect(fetch.mock.calls[0][0]).toBe("http://api:8000/v1/auth/config");
  });
  it("reports unavailable when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("refused")));
    expect(await authProvider("http://api:8000")).toBe("unavailable");
  });
});

function call(
  method: "GET" | "POST",
  path: string,
  headers: Record<string, string> = {},
) {
  const [route] = path.split("?");
  const request = new NextRequest(`http://localhost:3000/api/v1/${path}`, {
    method,
    headers,
  });
  return (method === "POST" ? POST : GET)(request, {
    params: Promise.resolve({ path: route.split("/") }),
  });
}

describe("GitHub sign-in through the web proxy", () => {
  it("hands the login redirect and its state cookie to the browser", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(null, {
        status: 302,
        headers: {
          location:
            "https://github.com/login/oauth/authorize?client_id=x&state=s",
          "set-cookie": "rv_oauth_state=s; HttpOnly; Path=/; SameSite=lax",
        },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const response = await call("GET", "auth/github/login");
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toMatch(
      /^https:\/\/github\.com\/login\/oauth\/authorize\?/,
    );
    expect(response.headers.get("set-cookie")).toContain("rv_oauth_state=s");
    const [url, options] = fetch.mock.calls[0];
    expect(url).toMatch(/\/v1\/auth\/github\/login$/);
    expect(options.redirect).toBe("manual");
  });
  it("forwards GitHub's code and state to the callback, with the browser cookie", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(null, { status: 302, headers: { location: "/" } }),
      );
    vi.stubGlobal("fetch", fetch);
    const response = await call(
      "GET",
      "auth/github/callback?code=abc&state=s",
      {
        cookie: "rv_oauth_state=s",
      },
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe("/");
    const [url, options] = fetch.mock.calls[0];
    expect(url).toMatch(/\/v1\/auth\/github\/callback\?code=abc&state=s$/);
    expect(options.headers.get("cookie")).toBe("rv_oauth_state=s");
  });
  it.each([
    ["GET", "auth/github/login?next=https://attacker.test"],
    ["POST", "auth/github/login"],
    ["POST", "auth/github/callback"],
    ["GET", `auth/github/callback?code=${"a".repeat(2100)}`],
  ] as const)("refuses %s %s without fetching", async (method, path) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect((await call(method, path)).status).toBe(404);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("still follows no redirect on any other route", async () => {
    const fetch = vi.fn().mockResolvedValue(json({ auth_provider: "dev" }));
    vi.stubGlobal("fetch", fetch);
    expect((await call("GET", "auth/config")).status).toBe(200);
    expect(fetch.mock.calls[0][1].redirect).toBe("error");
    expect(
      (await call("GET", "auth/config")).headers.get("location"),
    ).toBeNull();
  });
});
