import { render, screen } from "@testing-library/react";
import { isValidElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import NotFound from "../src/app/not-found";
import JobPage from "../src/app/(workspace)/jobs/[id]/page";
import ProjectPage from "../src/app/(workspace)/projects/[id]/page";
import SignInPage from "../src/app/sign-in/page";

const id = "11111111-1111-4111-8111-111111111111";
afterEach(() => vi.unstubAllGlobals());

describe("not-found route", () => {
  it("renders a real 404 page with ways back into the workspace", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeVisible();
    expect(screen.getByText("404")).toBeVisible();
    expect(screen.getByRole("link", { name: "Go to Overview" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Go to your projects" })).toHaveAttribute(
      "href",
      "/projects",
    );
  });
});

describe("record routes", () => {
  it.each([
    ["project", ProjectPage],
    ["job", JobPage],
  ])("a malformed %s id renders the not-found page, never an API request", async (_, Page) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const hex = "abcdef12-3456-4789-8abc-def012345678";
    for (const bad of ["not-a-uuid", "../auth/session", `${id}/../x`, hex.toUpperCase(), ""]) {
      const rendered = Page({ params: Promise.resolve({ id: bad }) });
      await expect(rendered).rejects.toMatchObject({
        digest: expect.stringContaining("404"),
      });
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("passes a well-formed id to the client view", async () => {
    const project = await ProjectPage({ params: Promise.resolve({ id }) });
    const job = await JobPage({ params: Promise.resolve({ id }) });
    expect(isValidElement(project) && (project.props as { projectId: string }).projectId).toBe(id);
    expect(isValidElement(job) && (job.props as { jobId: string }).jobId).toBe(id);
  });
});

describe("sign-in route", () => {
  it.each([
    [{ reason: "expired" }, true],
    [{ reason: "EXPIRED" }, false],
    [{ reason: ["expired", "x"] }, false],
    [{ reason: "<script>alert(1)</script>" }, false],
    [{}, false],
  ])("treats only reason=expired as an expired session (%j)", async (params, expired) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ auth_provider: "dev" }), { status: 200 }),
      ),
    );
    const page = await SignInPage({ searchParams: Promise.resolve(params) });
    expect(isValidElement(page)).toBe(true);
    expect(page.props).toEqual({ authProvider: "dev", expired });
  });
});
