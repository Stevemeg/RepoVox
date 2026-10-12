import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  Empty,
  GenerationNotice,
  Workspace,
} from "../src/components/workspace";
import { api, ApiError } from "../src/lib/api";

const navigation = vi.hoisted(() => ({
  path: "/",
  replace: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.path,
  useRouter: () => navigation,
}));
const account = {
  id: "a",
  display_name: "Alex Chen",
  email: "alex@example.test",
  environment: "test",
  fixtures_enabled: true,
};
const project = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Demo project",
  repository_url: "https://github.com/example/demo",
  status: "unprocessed",
  created_at: "2026-10-12T00:00:00Z",
};
const fetcher = vi.fn();
function respond(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}
beforeEach(() => {
  navigation.path = "/";
  navigation.replace.mockReset();
  navigation.push.mockReset();
  fetcher.mockReset();
  vi.stubGlobal("fetch", fetcher);
  fetcher.mockImplementation((url: string) =>
    Promise.resolve(respond(url.endsWith("/auth/session") ? account : [])),
  );
});

describe("Workspace", () => {
  it("shows real empty states and disabled generation", async () => {
    render(<Workspace />);
    expect(
      await screen.findByText(
        "Welcome back, Alex. Let's bring a little clarity to your code.",
      ),
    ).toBeVisible();
    expect(await screen.findByText("No projects yet")).toBeVisible();
    expect(screen.getByText("No jobs yet")).toBeVisible();
    expect(
      screen.getByRole("button", { name: /Generate video/ }),
    ).toBeDisabled();
  });
  it("guards expired protected navigation and removes records", async () => {
    fetcher.mockResolvedValue(
      respond({ error: { code: "session_expired" } }, 401),
    );
    render(<Workspace />);
    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/sign-in"),
    );
    expect(screen.queryByText("Demo project")).not.toBeInTheDocument();
  });
  it("shows loading while session is unresolved", () => {
    fetcher.mockImplementation(() => new Promise(() => {}));
    render(<Workspace />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your workspace",
    );
  });
  it("creates a project through the authenticated API", async () => {
    navigation.path = "/projects";
    render(<Workspace />);
    await screen.findByRole("heading", { name: "Projects" });
    await userEvent.click(
      screen.getAllByRole("button", { name: "New project" })[0],
    );
    await userEvent.type(screen.getByLabelText("Project name"), "Demo");
    await userEvent.type(
      screen.getByLabelText("GitHub repository URL"),
      "https://github.com/example/demo",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Create project" }),
    );
    await waitFor(() =>
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/projects",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            title: "Demo",
            repository_url: "https://github.com/example/demo",
          }),
        }),
      ),
    );
  });
  it("renders owned projects and synthetic job labels", async () => {
    navigation.path = "/jobs";
    fetcher.mockImplementation((url: string) =>
      Promise.resolve(
        respond(
          url.endsWith("/auth/session")
            ? account
            : url.endsWith("/projects")
              ? [project]
              : [
                  {
                    id: "job-1",
                    project_id: project.id,
                    project_title: "Demo project",
                    state: "failed",
                    synthetic: true,
                    created_at: project.created_at,
                  },
                ],
        ),
      ),
    );
    render(<Workspace />);
    expect(await screen.findByText("Demo project")).toBeVisible();
    expect(screen.getByText(/Synthetic · job-1/)).toBeVisible();
    expect(
      screen.getByText(/do not analyze repositories or generate videos/),
    ).toBeVisible();
  });
  it("displays sanitized errors with recovery", async () => {
    fetcher.mockResolvedValue(
      respond({ error: { code: "dependency_unavailable" } }, 503),
    );
    render(<Workspace />);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "We could not complete that request",
    );
  });
  it("offers only local development identities at sign-in", async () => {
    navigation.path = "/sign-in";
    fetcher.mockResolvedValue(
      respond({ error: { code: "session_required" } }, 401),
    );
    render(<Workspace />);
    expect(screen.getByRole("button", { name: /Alex Chen/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /Sam Rivera/ })).toBeVisible();
    expect(screen.getByText(/Development identities only/)).toBeVisible();
  });
  it("keeps the create dialog keyboard usable", async () => {
    navigation.path = "/projects";
    render(<Workspace />);
    await screen.findByRole("heading", { name: "Projects" });
    await userEvent.click(
      screen.getAllByRole("button", { name: "New project" })[0],
    );
    expect(screen.getByLabelText("Project name")).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "New project" })[0],
    ).toHaveFocus();
  });
  it("signs out and clears session state without an expiration error", async () => {
    render(<Workspace />);
    await screen.findByRole("button", { name: "Sign out" });
    fetcher.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/sign-out")
          ? new Response(null, { status: 204 })
          : respond({ error: { code: "session_required" } }, 401),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/sign-in"),
    );
    expect(
      screen.queryByText("Your session expired. Sign in to continue."),
    ).not.toBeInTheDocument();
  });
});
it("sends CSRF and reports unauthorized API response", async () => {
  document.cookie = "rv_csrf=test-csrf;path=/";
  fetcher.mockResolvedValue(
    respond({ error: { code: "session_expired" } }, 401),
  );
  await expect(api("/projects", { method: "POST" })).rejects.toEqual(
    new ApiError("session_expired", 401),
  );
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/projects",
    expect.objectContaining({
      headers: expect.objectContaining({ "X-CSRF-Token": "test-csrf" }),
    }),
  );
});
it("reusable empty and generation components are explicit", () => {
  render(
    <>
      <Empty kind="projects" />
      <GenerationNotice />
    </>,
  );
  expect(screen.getByText("No projects yet")).toBeVisible();
  expect(screen.getByRole("button", { name: /Generate video/ })).toBeDisabled();
});
