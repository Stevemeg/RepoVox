import { test, expect } from "@playwright/test";
test("rebuilt web preserves security headers and BFF restrictions", async ({ page, request }) => {
  const response = await request.get("/sign-in");
  expect(response.status()).toBe(200);
  const headers = response.headers();
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("same-origin");
  expect(headers["content-security-policy"]).toBe(
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
  );
  expect(headers["x-powered-by"]).toBeUndefined();
  expect((await request.get("/api/v1/projects")).status()).toBe(401);
  expect((await request.get("/api/v1/projects?target=https://example.test")).status()).toBe(404);
  expect((await request.get("/api/v1/private/gold")).status()).toBe(404);
  const oversized = await request.post("/api/v1/projects", { data: "x".repeat(16385) });
  expect(oversized.status()).toBe(413);
  await page.goto("/sign-in");
  await page.getByRole("button", { name: /Alex Chen/ }).click();
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  // The context has a real local session but this request deliberately omits CSRF.
  const forbidden = await page.request.post("/api/v1/projects", {
    headers: { origin: "http://localhost:3000" },
    data: { title: "Rejected fixture", repository_url: "https://github.com/example/demo" },
  });
  expect(forbidden.status()).toBe(403);
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
  await expect(
    page.getByRole("button", { name: /Generate video/ }),
  ).toBeDisabled();
  await page.screenshot({
    path: "test-results/ui/desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 850 });
  expect(
    await page
      .locator(".generation-note > div")
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
  await page.getByRole("button", { name: "Run synthetic fixture" }).click();
  await expect(
    page.getByText("Synthetic ·", { exact: false }).first(),
  ).toBeVisible();
  await page.locator(".job-row").first().click();
  await expect(page.getByText("14 durable identifiers")).toBeVisible();
  await expect(
    page.getByText("The fixture finished its infrastructure demonstration.", {
      exact: false,
    }),
  ).toBeVisible({ timeout: 20000 });
  await page.getByRole("link", { name: /^Projects/ }).click();
  await page.getByRole("link", { name: new RegExp(title) }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete project" }).click();
  await expect(
    page.getByRole("heading", { name: "Projects", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/sign-in/);
});
