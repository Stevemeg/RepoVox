import { test, expect } from "@playwright/test";
test("local sign-in, create project, fixture history, delete and sign-out", async ({
  page,
}) => {
  await page.goto("/projects");
  await expect(page).toHaveURL(/sign-in/);
  await page.getByRole("button", { name: /Alex Chen/ }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Generate video/ }),
  ).toBeDisabled();
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
