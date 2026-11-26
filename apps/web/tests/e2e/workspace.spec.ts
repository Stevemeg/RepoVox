import { test, expect, type APIResponse } from "@playwright/test";

// Literal copies of next.config.ts, deliberately not imported from it: weakening or dropping
// any header there must fail here.
const CONTENT_SECURITY_POLICY =
  "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; worker-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'";
const HARDENED_HEADERS: Record<string, string> = {
  "content-security-policy": CONTENT_SECURITY_POLICY,
  "x-content-type-options": "nosniff",
  "referrer-policy": "same-origin",
  "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  "cross-origin-opener-policy": "same-origin",
  "cross-origin-resource-policy": "same-origin",
};
const MALFORMED_RECORD_PATHS = [
  "/projects/not-a-uuid",
  "/jobs/not-a-uuid",
  // Uppercase hex is not the lowercase id form the API issues.
  "/projects/00000000-0000-4000-8000-00000000000A",
];

function expectHardened(response: APIResponse, label: string) {
  const headers = response.headers();
  for (const [name, value] of Object.entries(HARDENED_HEADERS))
    expect(headers[name], `${label}: ${name}`).toBe(value);
  expect(headers["x-powered-by"], `${label}: x-powered-by`).toBeUndefined();
}

test("rebuilt web preserves security headers and BFF restrictions", async ({ page, request }) => {
  const response = await request.get("/sign-in");
  expect(response.status()).toBe(200);
  expectHardened(response, "/sign-in");
  const headers = response.headers();
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("same-origin");
  expect(headers["content-security-policy"]).toBe(CONTENT_SECURITY_POLICY);
  expect(headers["x-powered-by"]).toBeUndefined();
  // fullscreen and picture-in-picture stay allowed for native video controls.
  expect(headers["permissions-policy"]).not.toMatch(/fullscreen|picture-in-picture/);

  // The same headers on every proxied API response, whatever its status.
  const config = await request.get("/api/v1/auth/config");
  expect(config.status()).toBe(200);
  expectHardened(config, "/api/v1/auth/config");
  expect(config.headers()["cache-control"]).toBe("no-store");
  const unauthenticated = await request.get("/api/v1/projects");
  expect(unauthenticated.status()).toBe(401);
  expectHardened(unauthenticated, "/api/v1/projects");
  expect(unauthenticated.headers()["cache-control"]).toBe("no-store");
  const queried = await request.get("/api/v1/projects?target=https://example.test");
  expect(queried.status()).toBe(404);
  expectHardened(queried, "/api/v1/projects?target");
  const unknownApi = await request.get("/api/v1/private/gold");
  expect(unknownApi.status()).toBe(404);
  expectHardened(unknownApi, "/api/v1/private/gold");
  const oversized = await request.post("/api/v1/projects", { data: "x".repeat(16385) });
  expect(oversized.status()).toBe(413);
  expectHardened(oversized, "413 /api/v1/projects");

  // Unknown paths are real 404s with the same security headers, never a rendered Overview.
  for (const path of ["/nonexistent-route", "/sign-in/extra", "/projects/a/b"]) {
    const missing = await request.get(path);
    expect(missing.status(), path).toBe(404);
    expect(missing.headers()["content-security-policy"]).toBe(headers["content-security-policy"]);
    expectHardened(missing, path);
  }
  // A malformed record id is stopped by src/proxy.ts before rendering: a real HTTP 404 that
  // renders the not-found page, carries every header and echoes nothing of the request.
  for (const path of MALFORMED_RECORD_PATHS) {
    const missing = await request.get(path);
    expect(missing.status(), path).toBe(404);
    expectHardened(missing, path);
    const body = await missing.text();
    expect(body, path).toContain("<title>Page not found · RepoVox</title>");
    expect(body, path).not.toContain(path.split("/")[2]);
    expect(missing.headers()["x-middleware-rewrite"] ?? "", path).not.toMatch(/^[a-z]+:/i);
  }
  // A well-formed id is not blocked by the proxy: the record page renders as before.
  for (const path of [
    "/projects/00000000-0000-4000-8000-000000000000",
    "/jobs/00000000-0000-4000-8000-000000000000",
  ]) {
    const record = await request.get(path);
    expect(record.status(), path).toBe(200);
    expectHardened(record, path);
  }

  await page.goto("/sign-in");
  await page.getByRole("button", { name: /Alex Chen/ }).click();
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  // A malformed record id renders the not-found page with HTTP 404 and never reaches the API.
  const leaked: string[] = [];
  page.on("request", (sent) => {
    if (sent.url().includes("/api/v1/") && sent.url().includes("not-a-uuid")) leaked.push(sent.url());
  });
  for (const path of ["/projects/not-a-uuid", "/jobs/not-a-uuid"]) {
    const document = await page.goto(path);
    expect(document?.status(), path).toBe(404);
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  }
  expect(leaked).toEqual([]);
  // A fresh tab of the signed-in session, so no earlier page's polling can be counted: the
  // not-found pages make no API request at all.
  const probe = await page.context().newPage();
  const apiRequests: string[] = [];
  probe.on("request", (sent) => {
    if (new URL(sent.url()).pathname.startsWith("/api/v1/")) apiRequests.push(sent.url());
  });
  for (const path of MALFORMED_RECORD_PATHS) {
    const document = await probe.goto(path);
    expect(document?.status(), path).toBe(404);
    await expect(probe.getByRole("heading", { name: "Page not found" })).toBeVisible();
  }
  expect(apiRequests).toEqual([]);
  await probe.close();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  // The context has a real local session but this request deliberately omits CSRF.
  const forbidden = await page.request.post("/api/v1/projects", {
    headers: { origin: "http://localhost:3000" },
    data: { title: "Rejected fixture", repository_url: "https://github.com/example/demo" },
  });
  expect(forbidden.status()).toBe(403);
  expectHardened(forbidden, "403 /api/v1/projects");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/sign-in/);
});
test("local sign-in, create project, fixture history, delete and sign-out", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/projects");
  await expect(page).toHaveURL(/sign-in/);
  await page.getByRole("button", { name: /Alex Chen/ }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".overview-callout")).toBeVisible();
  await expect(page.getByRole("button", { name: /Generate video/ })).toHaveCount(0);
  await expect(page.getByText(/later phase|Phase [12]\b|remains unavailable/i)).toHaveCount(0);
  await page.screenshot({
    path: "test-results/ui/desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 850 });
  expect(
    await page
      .locator(".overview-callout > div")
      .evaluate((element) => element.getBoundingClientRect().width),
  ).toBeGreaterThan(220);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/ui/mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("link", { name: /^Projects/ }).click();
  await page.getByRole("button", { name: "New project" }).first().click();
  const title = `Browser fixture ${Date.now()}`;
  await page.getByLabel("Project name").fill(title);
  await page
    .getByLabel("GitHub repository URL")
    .fill("https://github.com/example/demo");
  await page.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("link", { name: new RegExp(title) }).click();
  // Rename through PATCH /projects/{id}: focus starts in the field and returns to the opener.
  const renamed = `${title} renamed`;
  const rename = page.getByRole("button", { name: "Rename project" });
  await rename.click();
  const renameDialog = page.getByRole("dialog", { name: "Rename project" });
  await expect(renameDialog.getByLabel("Project name")).toBeFocused();
  await renameDialog.getByLabel("Project name").fill(renamed);
  await renameDialog.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("heading", { name: renamed, level: 1 })).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: `Project renamed to “${renamed}”.` }),
  ).toBeVisible();
  await expect(rename).toBeFocused();
  await page.getByRole("button", { name: "Run synthetic fixture" }).click();
  await expect(
    page.getByText("Synthetic ·", { exact: false }).first(),
  ).toBeVisible();
  await page.locator(".job-row").first().click();
  await expect(page.getByText("14 stages")).toBeVisible();
  await expect(
    page.getByText("The fixture finished its infrastructure demonstration.", {
      exact: false,
    }),
  ).toBeVisible({ timeout: 20000 });
  // Unified history: the fixture boundary is complete, never a red failure, and the raw
  // recorded state stays visible.
  await page
    .getByRole("navigation", { name: "Primary" })
    .getByRole("link", { name: "Job history" })
    .click();
  const history = page.getByRole("region", { name: "All jobs" });
  await page.getByLabel("Search", { exact: true }).fill(renamed);
  const rows = history.locator("a[data-kind]");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toHaveAttribute("data-kind", "fixture");
  await expect(rows.first().locator(".badge")).toHaveText("Fixture complete");
  await expect(rows.first().locator(".badge")).toHaveAttribute("data-tone", "succeeded");
  await expect(rows.first()).toContainText("recorded as failed / phase1_fixture_boundary");
  await page.getByLabel("Status", { exact: true }).selectOption("failed");
  await expect(rows).toHaveCount(0);
  await page.getByLabel("Status", { exact: true }).selectOption("succeeded");
  await page.getByLabel("Type", { exact: true }).selectOption("fixture");
  await expect(rows).toHaveCount(1);
  await page.getByRole("link", { name: /^Projects/ }).click();
  await page.getByRole("link", { name: new RegExp(title) }).click();
  let nativeDialogs = 0;
  page.on("dialog", (dialog) => {
    nativeDialogs += 1;
    void dialog.dismiss();
  });
  await page.getByRole("button", { name: "Delete project" }).click();
  const confirm = page.getByRole("alertdialog", { name: "Delete this project?" });
  await expect(confirm).toBeVisible();
  await expect(confirm.getByRole("button", { name: "Cancel" })).toBeFocused();
  await confirm.getByRole("button", { name: "Delete project" }).click();
  await expect(
    page.getByRole("heading", { name: "Projects", exact: true }),
  ).toBeVisible();
  // DELETE answers 202: access is revoked now and cleanup is reported as pending, not done.
  const deletedNotice = page
    .getByRole("status")
    .filter({ hasText: "was removed from your workspace" });
  await expect(deletedNotice).toContainText(
    "Access to the project and its jobs was revoked immediately.",
  );
  await expect(deletedNotice).toContainText("cleaned up in the background");
  await deletedNotice.getByRole("button", { name: "Dismiss notice" }).click();
  await expect(deletedNotice).toHaveCount(0);
  expect(nativeDialogs).toBe(0);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/sign-in/);
});
