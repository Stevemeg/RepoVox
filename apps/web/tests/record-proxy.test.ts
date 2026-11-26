// @vitest-environment node
// The record-page request boundary (src/proxy.ts): a malformed /projects/<id> or /jobs/<id>
// is rewritten to a path no route matches, which Next.js serves as a real HTTP 404. The
// end-to-end status and headers are asserted in tests/e2e/workspace.spec.ts.
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { config, proxy } from "../src/proxy";

const run = (path: string) => proxy(new NextRequest(`http://localhost:3000${path}`));
const SENTINEL = "http://localhost:3000/_not-a-route/malformed-record-id";

describe("record page proxy", () => {
  it("runs only on single-segment record pages", () => {
    expect(config.matcher).toEqual(["/projects/:id", "/jobs/:id"]);
  });

  it.each([
    "/projects/00000000-0000-4000-8000-000000000000",
    "/jobs/0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0",
    "/projects/00000000-0000-4000-8000-000000000000?tab=videos",
  ])("lets the well-formed id %s through untouched", (path) => {
    const response = run(path);
    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(response.headers.get("x-middleware-rewrite")).toBeNull();
    expect(response.status).toBe(200);
  });

  it.each([
    "/projects/not-a-uuid",
    "/jobs/not-a-uuid",
    "/projects/0F1E2D3C-4B5A-4968-8776-A5B4C3D2E1F0",
    "/jobs/0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f",
    "/jobs/0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f00",
    "/projects/0f1e2d3c4b5a49688776a5b4c3d2e1f0",
    "/projects/%30f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0",
    "/projects/0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0%00",
    "/jobs/%3Cscript%3E",
    "/projects/not-a-uuid?next=https://evil.test",
  ])("rewrites the malformed id %s to the not-found sentinel", (path) => {
    const response = run(path);
    expect(response.headers.get("x-middleware-rewrite")).toBe(SENTINEL);
    expect(response.headers.get("x-middleware-next")).toBeNull();
  });

  it("fails closed on a path outside the matcher shape", () => {
    expect(run("/projects/a/b").headers.get("x-middleware-rewrite")).toBe(SENTINEL);
  });

  it("rewrites to a path that can never be an app route", () => {
    const path = new URL(SENTINEL).pathname;
    // app/ folders starting with "_" are private: Next.js never routes them.
    expect(path.split("/")[1].startsWith("_")).toBe(true);
    const app = fileURLToPath(new URL("../src/app", import.meta.url));
    expect(existsSync(`${app}/${path.split("/")[1]}`)).toBe(false);
  });
});
