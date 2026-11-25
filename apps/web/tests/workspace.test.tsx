import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobDetailView } from "../src/components/workspace/job-detail";
import { JobsView } from "../src/components/workspace/jobs";
import { OverviewView } from "../src/components/workspace/overview";
import { ProjectDetailView } from "../src/components/workspace/project-detail";
import { ProjectsView } from "../src/components/workspace/projects";
import { SettingsView } from "../src/components/workspace/settings";
import { WorkspaceShell } from "../src/components/workspace/shell";
import type { Account, Job, Project } from "../src/lib/api";

const navigation = vi.hoisted(() => ({ path: "/", replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.path,
  useRouter: () => navigation,
}));

const account: Account = {
  id: "11111111-1111-4111-8111-111111111111",
  display_name: "Alex Chen",
  email: "alex@example.test",
  environment: "development",
  fixtures_enabled: true,
  analysis_enabled: true,
  video_enabled: false,
  auth_provider: "dev",
  github_oauth_enabled: false,
};
const project: Project = {
  id: "22222222-2222-4222-8222-222222222222",
  title: "Demo project",
  repository_url: "https://github.com/example/demo",
  status: "unprocessed",
  created_at: "2026-10-12T00:00:00Z",
};
const stages = Array.from({ length: 14 }, (_, index) => ({
  id: `33333333-3333-4333-8333-${String(index).padStart(12, "0")}`,
  ordinal: index + 1,
  stage_key: `stage_${index + 1}`,
  state: "succeeded",
  attempt_count: 1,
  error_code: null,
}));
const job = (overrides: Partial<Job> = {}): Job => ({
  id: "44444444-4444-4444-8444-444444444444",
  project_id: project.id,
  project_title: project.title,
  state: "failed",
  version: 3,
  synthetic: true,
  fixture: "normal",
  error_code: "phase1_fixture_boundary",
  created_at: project.created_at,
  deadline: project.created_at,
  stages,
  history: [{ version: 1, state: "queued", created_at: project.created_at }],
  attempts: [],
  usage: [],
  ...overrides,
});

const fetcher = vi.fn();
const respond = (value: unknown, status = 200) =>
  new Response(value === undefined ? null : JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
type Handler = (init: RequestInit) => Response;
let routes: Record<string, Handler> = {};
function serve(table: Record<string, Handler | unknown>) {
  routes = Object.fromEntries(
    Object.entries(table).map(([key, value]) => [
      key,
      typeof value === "function" ? (value as Handler) : () => respond(value),
    ]),
  );
}
const calls = (method: string, url: string) =>
  fetcher.mock.calls.filter(
    ([called, init]) => called === url && ((init?.method as string) ?? "GET") === method,
  ) as [string, RequestInit][];
const header = (init: RequestInit, name: string) => new Headers(init.headers).get(name);

function renderAt(path: string, view: ReactNode) {
  navigation.path = path;
  return render(<WorkspaceShell>{view}</WorkspaceShell>);
}

beforeEach(() => {
  navigation.path = "/";
  navigation.replace.mockReset();
  navigation.push.mockReset();
  fetcher.mockReset();
  serve({
    "GET /api/v1/auth/session": account,
    "GET /api/v1/projects": [],
    "GET /api/v1/jobs": [],
  });
  fetcher.mockImplementation((url: string, init: RequestInit = {}) => {
    const handler = routes[`${init.method ?? "GET"} ${url}`];
    return Promise.resolve(
      handler ? handler(init) : respond({ error: { code: "not_found" } }, 404),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  document.cookie = "rv_csrf=test-csrf;path=/";
});
afterEach(() => {
  document.cookie = "rv_csrf=;path=/;max-age=0";
  vi.unstubAllGlobals();
});

describe("workspace shell", () => {
  it("shows loading while the session is unresolved", () => {
    fetcher.mockImplementation(() => new Promise(() => {}));
    renderAt("/", <OverviewView />);
    expect(screen.getByRole("status")).toHaveTextContent("Opening your workspace");
  });

  it("redirects an expired session to sign-in and says why", async () => {
    serve({ "GET /api/v1/auth/session": () => respond({ error: { code: "session_expired" } }, 401) });
    renderAt("/projects", <ProjectsView />);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/sign-in?reason=expired"));
    expect(screen.queryByText("Demo project")).not.toBeInTheDocument();
  });

  it("sends a browser without session cookies to sign-in without calling the API", async () => {
    document.cookie = "rv_csrf=;path=/;max-age=0";
    renderAt("/projects", <ProjectsView />);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/sign-in"));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("redirects a visitor with no session without claiming it expired", async () => {
    serve({ "GET /api/v1/auth/session": () => respond({ error: { code: "session_required" } }, 401) });
    renderAt("/", <OverviewView />);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/sign-in"));
  });

  it("maps a load failure to our own sentence, with code and request id as support metadata", async () => {
    serve({
      "GET /api/v1/auth/session": () =>
        respond({ error: { code: "dependency_unavailable", request_id: "req-9" } }, 503),
    });
    renderAt("/", <OverviewView />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A required service is temporarily unavailable. Try again in a moment.");
    expect(alert).toHaveTextContent("Reference: dependency_unavailable · request req-9");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("has a skip link, a labelled primary navigation and a focusable main region", async () => {
    renderAt("/projects", <ProjectsView />);
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    const projects = within(nav).getByRole("link", { name: /^Projects/ });
    expect(projects).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main-content");
    expect(document.getElementById("main-content")?.tagName).toBe("MAIN");
    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("opens and closes the mobile navigation drawer", async () => {
    const { container } = renderAt("/", <OverviewView />);
    const open = await screen.findByRole("button", { name: "Open navigation" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    expect(open).toHaveAttribute("aria-controls", "app-sidebar");
    await userEvent.click(open);
    expect(screen.getByRole("button", { name: "Close navigation" })).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector(".app-shell")).toHaveAttribute("data-nav-open", "true");
    await userEvent.keyboard("{Escape}");
    expect(container.querySelector(".app-shell")).toHaveAttribute("data-nav-open", "false");
  });

  it("signs out and clears session state without an expiration message", async () => {
    renderAt("/", <OverviewView />);
    await screen.findByRole("button", { name: "Sign out" });
    serve({
      "POST /api/v1/auth/sign-out": () => respond(undefined, 204),
      "GET /api/v1/auth/session": () => respond({ error: { code: "session_required" } }, 401),
    });
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/sign-in"));
    expect(screen.queryByText(/session expired/i)).not.toBeInTheDocument();
    expect(header(calls("POST", "/api/v1/auth/sign-out")[0][1], "x-csrf-token")).toBe("test-csrf");
  });

  it("reads the session, projects and jobs without CSRF or JSON headers", async () => {
    renderAt("/", <OverviewView />);
    await screen.findByRole("heading", { name: "Overview" });
    for (const url of ["/api/v1/auth/session", "/api/v1/projects", "/api/v1/jobs"]) {
      const [[, init]] = calls("GET", url);
      expect(header(init, "x-csrf-token")).toBeNull();
      expect(header(init, "content-type")).toBeNull();
    }
  });
});

describe("overview", () => {
  it("shows real empty states and no stale phase copy", async () => {
    renderAt("/", <OverviewView />);
    expect(
      await screen.findByText("Welcome back, Alex. Let's bring a little clarity to your code."),
    ).toBeVisible();
    expect(screen.getByText("No projects yet")).toBeVisible();
    expect(screen.getByText("No jobs yet")).toBeVisible();
    expect(screen.queryByText(/later phase|Phase [12]|remains unavailable/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /Generate video/ })).toBeNull();
  });

  it("states what this environment offers from the session flags", async () => {
    serve({
      "GET /api/v1/auth/session": { ...account, video_enabled: true },
      "GET /api/v1/projects": [project],
      "GET /api/v1/jobs": [job({ state: "running", error_code: null })],
    });
    const { unmount } = renderAt("/", <OverviewView />);
    expect(await screen.findByText("Create narrated videos from a project")).toBeVisible();
    expect(screen.getByRole("link", { name: /Go to your projects/ })).toHaveAttribute("href", "/projects");
    expect(screen.getByText("Active jobs").closest(".stat")).toHaveTextContent("1");
    unmount();
    serve({ "GET /api/v1/auth/session": account, "GET /api/v1/projects": [], "GET /api/v1/jobs": [] });
    renderAt("/", <OverviewView />);
    expect(await screen.findByText("Narrated videos are not enabled in this environment")).toBeVisible();
  });
});

describe("projects", () => {
  it("creates a project through the authenticated API", async () => {
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [],
      "GET /api/v1/jobs": [],
      "POST /api/v1/projects": () => respond(project, 201),
    });
    renderAt("/projects", <ProjectsView />);
    await screen.findByRole("heading", { name: "Projects" });
    await userEvent.click(screen.getAllByRole("button", { name: "New project" })[0]);
    await userEvent.type(screen.getByLabelText("Project name"), "Demo");
    await userEvent.type(screen.getByLabelText("GitHub repository URL"), "https://github.com/example/demo");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/projects"));
    const [[, init]] = calls("POST", "/api/v1/projects");
    expect(init.body).toBe(
      JSON.stringify({ title: "Demo", repository_url: "https://github.com/example/demo" }),
    );
    expect(header(init, "x-csrf-token")).toBe("test-csrf");
    expect(header(init, "content-type")).toBe("application/json");
  });

  it("refuses a non-canonical repository URL before calling the API", async () => {
    renderAt("/projects", <ProjectsView />);
    await screen.findByRole("heading", { name: "Projects" });
    await userEvent.click(screen.getAllByRole("button", { name: "New project" })[0]);
    await userEvent.type(screen.getByLabelText("Project name"), "Demo");
    const input = screen.getByLabelText("GitHub repository URL");
    await userEvent.type(input, "javascript:alert(1)");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription(/https:\/\/github\.com\/owner\/repository/);
    expect(calls("POST", "/api/v1/projects")).toHaveLength(0);
  });

  it("maps the API's validation and quota refusals to their own messages", async () => {
    let answer = respond({ error: { code: "invalid_request" } }, 422);
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [],
      "GET /api/v1/jobs": [],
      "POST /api/v1/projects": () => answer,
    });
    renderAt("/projects", <ProjectsView />);
    await screen.findByRole("heading", { name: "Projects" });
    await userEvent.click(screen.getAllByRole("button", { name: "New project" })[0]);
    await userEvent.type(screen.getByLabelText("Project name"), "Demo");
    await userEvent.type(screen.getByLabelText("GitHub repository URL"), "https://github.com/example/demo");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Check the project name and URL/);
    answer = respond({ error: { code: "project_quota" } }, 429);
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/project limit/));
  });

  it("keeps the create dialog keyboard usable", async () => {
    renderAt("/projects", <ProjectsView />);
    await screen.findByRole("heading", { name: "Projects" });
    await userEvent.click(screen.getAllByRole("button", { name: "New project" })[0]);
    expect(screen.getByRole("dialog", { name: "Add a project" })).toHaveAttribute("aria-modal", "true");
    expect(screen.getByLabelText("Project name")).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New project" })[0]).toHaveFocus();
  });
});

describe("project workspace", () => {
  beforeEach(() =>
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [project],
      "GET /api/v1/jobs": [],
    }),
  );

  it("links the repository only after validation, isolated in a new tab", async () => {
    renderAt(`/projects/${project.id}`, <ProjectDetailView projectId={project.id} />);
    const link = await screen.findByRole("link", { name: /example\/demo/ });
    expect(link).toHaveAttribute("href", "https://github.com/example/demo");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("never links an unsafe stored locator", async () => {
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [{ ...project, repository_url: "javascript:alert(1)" }],
      "GET /api/v1/jobs": [],
    });
    const { container } = renderAt(`/projects/${project.id}`, <ProjectDetailView projectId={project.id} />);
    expect(await screen.findByText("javascript:alert(1)")).toBeVisible();
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  });

  it("deletes only after the accessible confirmation, never window.confirm", async () => {
    const native = vi.spyOn(window, "confirm");
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [project],
      "GET /api/v1/jobs": [],
      [`DELETE /api/v1/projects/${project.id}`]: () =>
        respond({ deletion_id: "d", access_revoked: true, cleanup: "pending" }, 202),
    });
    renderAt(`/projects/${project.id}`, <ProjectDetailView projectId={project.id} />);
    const trigger = await screen.findByRole("button", { name: "Delete project" });
    await userEvent.click(trigger);
    const dialog = screen.getByRole("alertdialog", { name: "Delete this project?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(calls("DELETE", `/api/v1/projects/${project.id}`)).toHaveLength(0);

    await userEvent.click(trigger);
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete project" }),
    );
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/projects"));
    const [[, init]] = calls("DELETE", `/api/v1/projects/${project.id}`);
    expect(header(init, "x-csrf-token")).toBe("test-csrf");
    expect(native).not.toHaveBeenCalled();
    native.mockRestore();
  });

  it("reuses one idempotency key while retrying a submission, and a new one after success", async () => {
    const url = `/api/v1/development/projects/${project.id}/fixture-jobs`;
    const answers = [
      respond({ error: { code: "dependency_unavailable" } }, 503),
      respond(job(), 202),
      respond(job(), 202),
    ];
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [project],
      "GET /api/v1/jobs": [],
      [`POST ${url}`]: () => answers.shift()!,
    });
    renderAt(`/projects/${project.id}`, <ProjectDetailView projectId={project.id} />);
    const button = await screen.findByRole("button", { name: "Run synthetic fixture" });
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent(/temporarily unavailable/);
    await userEvent.click(button);
    await waitFor(() => expect(calls("POST", url)).toHaveLength(2));
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    await waitFor(() => expect(calls("POST", url)).toHaveLength(3));
    const keys = calls("POST", url).map(([, init]) => header(init, "idempotency-key"));
    expect(keys[0]).toMatch(/^[a-f0-9-]{36}$/);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[1]);
  });

  it("explains a project that is not in the workspace", async () => {
    serve({ "GET /api/v1/auth/session": account, "GET /api/v1/projects": [], "GET /api/v1/jobs": [] });
    renderAt(`/projects/${project.id}`, <ProjectDetailView projectId={project.id} />);
    expect(await screen.findByRole("heading", { name: "Project unavailable" })).toBeVisible();
  });
});

describe("jobs", () => {
  it("renders owned jobs with synthetic labels", async () => {
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [project],
      "GET /api/v1/jobs": [job({ id: "job-1" })],
    });
    renderAt("/jobs", <JobsView />);
    expect(await screen.findByText("Demo project")).toBeVisible();
    expect(screen.getByText(/Synthetic · job-1/)).toBeVisible();
    expect(screen.getByText(/do not analyze repositories or generate videos/)).toBeVisible();
  });

  it("shows a finished fixture's outcome and its real stage count", async () => {
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [project],
      "GET /api/v1/jobs": [],
      [`GET /api/v1/jobs/${job().id}`]: job(),
    });
    renderAt(`/jobs/${job().id}`, <JobDetailView jobId={job().id} />);
    expect(await screen.findByText("14 stages")).toBeVisible();
    expect(screen.getByText(/The fixture finished its infrastructure demonstration\./)).toBeVisible();
    expect(screen.queryByText(/Reference: phase1/)).toBeNull();
    expect(screen.queryByText(/Phase 1|Status code/)).toBeNull();
  });

  it("maps a stage refusal to a sentence and keeps the code as a reference", async () => {
    const refused = job({
      synthetic: false,
      error_code: "secret_detected",
      repository_url: "https://github.com/example/demo",
      commit_sha: "a".repeat(40),
    });
    serve({
      "GET /api/v1/auth/session": account,
      "GET /api/v1/projects": [project],
      "GET /api/v1/jobs": [],
      [`GET /api/v1/jobs/${refused.id}`]: refused,
    });
    renderAt(`/jobs/${refused.id}`, <JobDetailView jobId={refused.id} />);
    expect(await screen.findByText(/appears to contain a credential or secret/)).toBeVisible();
    expect(screen.getByText("Reference: secret_detected")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry pinned analysis" })).toBeVisible();
    expect(screen.getByRole("link", { name: /example\/demo/ })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByText(/Status code/)).toBeNull();
  });
});

describe("settings", () => {
  it("describes development authentication truthfully", async () => {
    renderAt("/settings", <SettingsView />);
    expect(await screen.findByText("Development authentication")).toBeVisible();
    expect(screen.getByText(/seeded development identity/)).toBeVisible();
    expect(screen.queryByText("GitHub OAuth")).toBeNull();
  });

  it("describes GitHub OAuth truthfully", async () => {
    serve({
      "GET /api/v1/auth/session": {
        ...account,
        auth_provider: "github",
        github_oauth_enabled: true,
        environment: "production",
        fixtures_enabled: false,
        video_enabled: true,
      },
      "GET /api/v1/projects": [],
      "GET /api/v1/jobs": [],
    });
    renderAt("/settings", <SettingsView />);
    expect(await screen.findByText("GitHub OAuth")).toBeVisible();
    expect(screen.queryByText("Development authentication")).toBeNull();
    expect(screen.queryByText(/seeded/)).toBeNull();
    expect(screen.getAllByText("production").length).toBeGreaterThan(0);
  });
});
