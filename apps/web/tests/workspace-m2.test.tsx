import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobDetailView } from "../src/components/workspace/job-detail";
import { JobsView } from "../src/components/workspace/jobs";
import { OverviewView } from "../src/components/workspace/overview";
import { deletionNotice, ProjectDetailView } from "../src/components/workspace/project-detail";
import { ProjectsView } from "../src/components/workspace/projects";
import { titleProblem } from "../src/components/workspace/rename-project";
import { WorkspaceShell } from "../src/components/workspace/shell";
import type { Account, Job, Project, Video, VideoJob } from "../src/lib/api";

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
  video_enabled: true,
  auth_provider: "dev",
  github_oauth_enabled: false,
};
const alpha: Project = {
  id: "22222222-2222-4222-8222-222222222222",
  title: "Alpha service",
  repository_url: "https://github.com/example/alpha",
  status: "unprocessed",
  created_at: "2026-11-01T00:00:00Z",
};
const beta: Project = {
  id: "33333333-3333-4333-8333-333333333333",
  title: "Beta tools",
  repository_url: "https://github.com/example/beta",
  status: "unprocessed",
  created_at: "2026-11-02T00:00:00Z",
};
const SHA_A = "a".repeat(40);
const SHA_F = "f0e1d2c3b4a5968778695a4b3c2d1e0f00112233";
const job = (overrides: Partial<Job> = {}): Job => ({
  id: "44444444-4444-4444-8444-444444444444",
  project_id: alpha.id,
  project_title: alpha.title,
  state: "failed",
  version: 3,
  synthetic: false,
  fixture: "normal",
  error_code: "phase2_pipeline_boundary",
  created_at: "2026-11-20T10:00:00Z",
  deadline: "2026-11-20T11:00:00Z",
  commit_sha: SHA_A,
  repository_url: alpha.repository_url,
  stages: [],
  history: [
    { version: 1, state: "queued", error_code: null, created_at: "2026-11-20T10:00:00Z" },
    {
      version: 2,
      state: "failed",
      error_code: "phase2_pipeline_boundary",
      created_at: "2026-11-20T10:05:00Z",
    },
  ],
  attempts: [],
  usage: [],
  ...overrides,
});
const video = (overrides: Partial<Video> = {}): Video => ({
  id: "55555555-5555-4555-8555-555555555555",
  category: "walkthrough",
  position: 0,
  title: "Walkthrough",
  checksum: "c".repeat(64),
  byte_count: 1000,
  metadata: {},
  published_at: "2026-11-20T10:30:00Z",
  expires_at: "2099-01-01T00:00:00Z",
  ...overrides,
});
const videoJob = (overrides: Partial<VideoJob> = {}): VideoJob => ({
  id: "66666666-6666-4666-8666-666666666666",
  project_id: alpha.id,
  analysis_job_id: job().id,
  state: "succeeded",
  version: 5,
  repository: "example/alpha",
  commit_sha: SHA_F,
  architecture: "published",
  error_code: null,
  created_at: "2026-11-21T10:00:00Z",
  deadline: "2026-11-21T11:00:00Z",
  finished_at: "2026-11-21T10:20:00Z",
  stages: [],
  videos: [video()],
  ...overrides,
});

const fetcher = vi.fn();
const respond = (value: unknown, status = 200) =>
  new Response(value === undefined ? null : JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
type Handler = (init: RequestInit) => Response | Promise<Response>;
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
const base = (extra: Record<string, Handler | unknown> = {}) => ({
  "GET /api/v1/auth/session": account,
  "GET /api/v1/projects": [alpha],
  "GET /api/v1/jobs": [],
  ...extra,
});

function renderAt(path: string, view: ReactNode) {
  navigation.path = path;
  return render(<WorkspaceShell>{view}</WorkspaceShell>);
}

beforeEach(() => {
  navigation.path = "/";
  navigation.replace.mockReset();
  navigation.push.mockReset();
  fetcher.mockReset();
  serve(base());
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

describe("project workspace: direct fetch", () => {
  it("loads a deep-linked project from GET /projects/{id}, not the workspace list", async () => {
    serve(
      base({
        "GET /api/v1/projects": [],
        [`GET /api/v1/projects/${alpha.id}`]: alpha,
        [`GET /api/v1/projects/${alpha.id}/jobs`]: [],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [],
      }),
    );
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    expect(await screen.findByRole("heading", { name: "Alpha service", level: 1 })).toBeVisible();
    expect(await screen.findByText("Newly registered")).toBeVisible();
    expect(screen.getByText(/No job has read this repository yet/)).toBeVisible();
    // The record's raw lifecycle value is shown only as technical metadata.
    expect(screen.getByText("API record status")).toBeVisible();
    expect(screen.getByText("unprocessed").tagName).toBe("CODE");
    for (const url of [`/api/v1/projects/${alpha.id}`, `/api/v1/projects/${alpha.id}/jobs`]) {
      const [[, init]] = calls("GET", url);
      expect(header(init, "x-csrf-token")).toBeNull();
      expect(header(init, "content-type")).toBeNull();
      expect(init.signal).toBeInstanceOf(AbortSignal);
    }
  });

  it("renders a clean not-found view when the API answers 404", async () => {
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}`]: () => respond({ error: { code: "not_found" } }, 404),
        [`GET /api/v1/projects/${alpha.id}/jobs`]: () =>
          respond({ error: { code: "not_found" } }, 404),
      }),
    );
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    expect(await screen.findByRole("heading", { name: "Project unavailable" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to your projects" })).toHaveAttribute(
      "href",
      "/projects",
    );
    // Even though the workspace list still had it cached.
    expect(screen.queryByRole("button", { name: /Delete project/ })).toBeNull();
  });

  it("offers a retry for a temporary failure instead of claiming the project is gone", async () => {
    let answer = () =>
      respond({ error: { code: "dependency_unavailable", request_id: "r-1" } }, 503);
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}`]: () => answer(),
        [`GET /api/v1/projects/${alpha.id}/jobs`]: [],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [],
      }),
    );
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("temporarily unavailable");
    expect(screen.queryByText("Project unavailable")).toBeNull();
    answer = () => respond(alpha);
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Alpha service", level: 1 })).toBeVisible();
  });

  it("describes activity from the project's own jobs and published videos", async () => {
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}`]: alpha,
        [`GET /api/v1/projects/${alpha.id}/jobs`]: [job()],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [videoJob()],
      }),
    );
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    const badge = await screen.findByText("Videos published");
    expect(badge.closest(".badge")).toHaveAttribute("data-tone", "succeeded");
    expect(screen.getByText(/1 published video is available/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Open the latest verified analysis/ })).toHaveAttribute(
      "href",
      `/jobs/${job().id}`,
    );
    // The project's job list shows the boundary as complete, with the raw record beside it.
    const jobs = screen.getByRole("region", { name: "Project jobs" });
    expect(within(jobs).getByText("Analysis complete")).toBeVisible();
    expect(within(jobs).getByText(/recorded as/)).toHaveTextContent(
      "recorded as failed / phase2_pipeline_boundary",
    );
    expect(document.getElementById("videos")).not.toBeNull();
  });

  it("shows analysis in progress while an analysis runs", async () => {
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}`]: alpha,
        [`GET /api/v1/projects/${alpha.id}/jobs`]: [job({ state: "running", error_code: null })],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [],
      }),
    );
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    expect(await screen.findByText("Analysis in progress")).toBeVisible();
  });
});

describe("project workspace: rename", () => {
  beforeEach(() =>
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}`]: alpha,
        [`GET /api/v1/projects/${alpha.id}/jobs`]: [],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [],
      }),
    ),
  );

  it("validates names like the API does", () => {
    expect(titleProblem("")).toMatch(/Enter a project name/);
    expect(titleProblem("   ")).toMatch(/Enter a project name/);
    expect(titleProblem("x".repeat(101))).toMatch(/at most 100/);
    expect(titleProblem(`  ${"x".repeat(100)}  `)).toBeNull();
    expect(titleProblem("tab\there")).toMatch(/control characters/);
    expect(titleProblem("line\nbreak")).toMatch(/control characters/);
    expect(titleProblem("Ünïcode ✓ name")).toBeNull();
  });

  it("refuses an empty name without calling the API, keeping focus in the field", async () => {
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    await userEvent.click(await screen.findByRole("button", { name: "Rename project" }));
    const dialog = screen.getByRole("dialog", { name: "Rename project" });
    const input = within(dialog).getByLabelText("Project name");
    expect(input).toHaveFocus();
    expect(input).toHaveValue("Alpha service");
    await userEvent.clear(input);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save name" }));
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Enter a project name.");
    expect(input).toHaveFocus();
    expect(calls("PATCH", `/api/v1/projects/${alpha.id}`)).toHaveLength(0);
  });

  it("renames with PATCH /projects/{id}, announces it and returns focus", async () => {
    serve({
      ...routes,
      [`PATCH /api/v1/projects/${alpha.id}`]: () => respond({ ...alpha, title: "Alpha platform" }),
    });
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    const trigger = await screen.findByRole("button", { name: "Rename project" });
    await userEvent.click(trigger);
    const input = screen.getByLabelText("Project name");
    await userEvent.clear(input);
    await userEvent.type(input, "  Alpha platform  ");
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByText("Project renamed to “Alpha platform”.")).toHaveAttribute(
      "role",
      "status",
    );
    expect(screen.getByRole("heading", { name: "Alpha platform", level: 1 })).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
    const [[, init]] = calls("PATCH", `/api/v1/projects/${alpha.id}`);
    expect(init.body).toBe(JSON.stringify({ title: "Alpha platform" }));
    expect(header(init, "x-csrf-token")).toBe("test-csrf");
    expect(header(init, "content-type")).toBe("application/json");
    // The workspace (sidebar count, lists) refreshes after the rename.
    await waitFor(() => expect(calls("GET", "/api/v1/projects").length).toBeGreaterThan(1));
  });

  it("shows API refusals in our own words and keeps the dialog open", async () => {
    let answer = () => respond({ error: { code: "invalid_request", request_id: "r-9" } }, 422);
    serve({ ...routes, [`PATCH /api/v1/projects/${alpha.id}`]: () => answer() });
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    await userEvent.click(await screen.findByRole("button", { name: "Rename project" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Project name"), " v2");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save name" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Enter a project name of 1 to 100 characters");
    expect(alert).toHaveTextContent("Reference: invalid_request · request r-9");
    answer = () => respond({ error: { code: "not_found" } }, 404);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save name" }));
    await waitFor(() =>
      expect(within(dialog).getByRole("alert")).toHaveTextContent(/deleted in another tab/),
    );
  });
});

describe("project workspace: 202 deletion", () => {
  it("states the accepted deletion truthfully", () => {
    const notice = deletionNotice("Alpha service", {
      deletion_id: "77777777-7777-4777-8777-777777777777",
      access_revoked: true,
      cleanup: "pending",
    });
    expect(notice.path).toBe("/projects");
    expect(notice.message).toContain("revoked immediately");
    expect(notice.message).toContain("cleaned up in the background");
    expect(notice.message).toContain("not instant");
    expect(notice.message).not.toMatch(/permanently erased|purged|all data (is|was) deleted/i);
    expect(notice.reference).toBe("deletion 77777777-7777-4777-8777-777777777777");
    // A response without those fields is not described as revoked or pending.
    const vague = deletionNotice("Alpha service", undefined);
    expect(vague.message).not.toContain("revoked immediately");
    expect(vague.reference).toBeUndefined();
  });

  it("returns to Projects with a dismissible banner after the 202", async () => {
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}`]: alpha,
        [`GET /api/v1/projects/${alpha.id}/jobs`]: [],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [],
        [`DELETE /api/v1/projects/${alpha.id}`]: () =>
          respond(
            {
              deletion_id: "77777777-7777-4777-8777-777777777777",
              access_revoked: true,
              cleanup: "pending",
            },
            202,
          ),
      }),
    );
    const view = renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete project" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete project" }),
    );
    await waitFor(() => expect(navigation.push).toHaveBeenCalledWith("/projects"));
    const [[, init]] = calls("DELETE", `/api/v1/projects/${alpha.id}`);
    expect(header(init, "x-csrf-token")).toBe("test-csrf");

    // The router moves to /projects; the shell keeps the banner for that page.
    navigation.path = "/projects";
    view.rerender(
      <WorkspaceShell>
        <ProjectsView />
      </WorkspaceShell>,
    );
    const banner = await screen.findByText(/was removed from your workspace/);
    const status = banner.closest('[role="status"]')!;
    expect(status).toHaveTextContent("Project deleted.");
    expect(status).toHaveTextContent("Access to the project and its jobs was revoked immediately.");
    expect(status).toHaveTextContent("cleaned up in the background");
    expect(status).toHaveTextContent("Reference: deletion 77777777-7777-4777-8777-777777777777");
    await userEvent.click(screen.getByRole("button", { name: "Dismiss notice" }));
    expect(screen.queryByText(/was removed from your workspace/)).toBeNull();
  });
});

describe("unified job history", () => {
  const analysisDone = job();
  const fixtureDone = job({
    id: "88888888-8888-4888-8888-888888888888",
    synthetic: true,
    error_code: "phase1_fixture_boundary",
    commit_sha: null,
    created_at: "2026-11-19T10:00:00Z",
  });
  const refused = job({
    id: "99999999-9999-4999-8999-999999999999",
    project_id: beta.id,
    project_title: beta.title,
    repository_url: beta.repository_url,
    error_code: "secret_detected",
    created_at: "2026-11-18T10:00:00Z",
  });
  const setup = (betaVideos: Handler | unknown) =>
    serve(
      base({
        "GET /api/v1/projects": [alpha, beta],
        "GET /api/v1/jobs": [analysisDone, fixtureDone, refused],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [
          videoJob(),
          videoJob({
            id: "66666666-6666-4666-8666-000000000002",
            state: "failed",
            error_code: "media_timeout",
            videos: [],
            commit_sha: null,
            created_at: "2026-11-17T10:00:00Z",
          }),
        ],
        [`GET /api/v1/projects/${beta.id}/video-jobs`]: betaVideos,
      }),
    );

  it("merges video, analysis and fixture jobs newest first with correct links", async () => {
    setup([]);
    renderAt("/jobs", <JobsView />);
    const list = await screen.findByRole("region", { name: "All jobs" });
    await waitFor(() => expect(within(list).getAllByRole("link")).toHaveLength(5));
    const links = within(list).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("data-kind"))).toEqual([
      "video",
      "analysis",
      "fixture",
      "analysis",
      "video",
    ]);
    expect(links[0]).toHaveAttribute("href", `/projects/${alpha.id}#videos`);
    expect(links[0]).toHaveTextContent("1 video published");
    expect(links[1]).toHaveAttribute("href", `/jobs/${analysisDone.id}`);
    expect(links[2]).toHaveAttribute("href", `/jobs/${fixtureDone.id}`);
    // Boundary jobs are complete, never red, and the raw record stays visible.
    const complete = within(links[1]).getByText("Analysis complete").closest(".badge")!;
    expect(complete).toHaveAttribute("data-tone", "succeeded");
    expect(complete).toHaveAttribute("data-state", "failed");
    expect(links[1]).toHaveTextContent("recorded as failed / phase2_pipeline_boundary");
    expect(within(links[2]).getByText("Fixture complete").closest(".badge")).toHaveAttribute(
      "data-tone",
      "succeeded",
    );
    expect(within(links[3]).getByText("Failed").closest(".badge")).toHaveAttribute(
      "data-tone",
      "failed",
    );
    expect(screen.getByText("5 jobs")).toBeVisible();
  });

  it("keeps the page working when one project's video jobs fail to load", async () => {
    let betaAnswer = () =>
      respond({ error: { code: "dependency_unavailable", request_id: "r-5" } }, 503);
    setup(() => betaAnswer());
    renderAt("/jobs", <JobsView />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Video jobs could not be loaded for 1 of 2 projects (“Beta tools”)");
    expect(alert).toHaveTextContent("Reference: dependency_unavailable · request r-5");
    // Everything else still renders.
    const list = screen.getByRole("region", { name: "All jobs" });
    expect(within(list).getAllByRole("link")).toHaveLength(5);
    betaAnswer = () =>
      respond([
        videoJob({
          id: "66666666-6666-4666-8666-000000000003",
          project_id: beta.id,
          created_at: "2026-11-25T10:00:00Z",
        }),
      ]);
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(within(list).getAllByRole("link")).toHaveLength(6);
    expect(within(list).getAllByRole("link")[0]).toHaveAttribute(
      "href",
      `/projects/${beta.id}#videos`,
    );
  });

  it("filters by type, status and plain-text search", async () => {
    setup([]);
    renderAt("/jobs", <JobsView />);
    const list = await screen.findByRole("region", { name: "All jobs" });
    await waitFor(() => expect(within(list).getAllByRole("link")).toHaveLength(5));
    const rows = () => within(list).queryAllByRole("link");

    await userEvent.selectOptions(screen.getByLabelText("Type"), "video");
    expect(rows().map((row) => row.getAttribute("data-kind"))).toEqual(["video", "video"]);
    expect(screen.getByText("Showing 2 of 5 jobs")).toBeVisible();

    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");
    expect(rows()).toHaveLength(1);
    expect(rows()[0]).toHaveTextContent("Video job");

    await userEvent.selectOptions(screen.getByLabelText("Type"), "all");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "succeeded");
    expect(rows().map((row) => row.getAttribute("data-kind"))).toEqual([
      "video",
      "analysis",
      "fixture",
    ]);

    await userEvent.selectOptions(screen.getByLabelText("Status"), "all");
    await userEvent.type(screen.getByLabelText("Search"), "F0E1D2C3");
    expect(rows()).toHaveLength(1);
    expect(rows()[0]).toHaveAttribute("href", `/projects/${alpha.id}#videos`);

    await userEvent.clear(screen.getByLabelText("Search"));
    await userEvent.type(screen.getByLabelText("Search"), "example/beta");
    expect(rows()).toHaveLength(1);
    expect(rows()[0]).toHaveTextContent("Beta tools");

    await userEvent.clear(screen.getByLabelText("Search"));
    await userEvent.type(screen.getByLabelText("Search"), "<script>");
    expect(rows()).toHaveLength(0);
    expect(screen.getByText("No jobs match these filters")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(rows()).toHaveLength(5);
  });

  it("requests no video jobs when videos are not enabled", async () => {
    serve(
      base({
        "GET /api/v1/auth/session": { ...account, video_enabled: false },
        "GET /api/v1/projects": [alpha, beta],
        "GET /api/v1/jobs": [analysisDone],
      }),
    );
    renderAt("/jobs", <JobsView />);
    expect(await screen.findByText("Analysis complete")).toBeVisible();
    expect(
      fetcher.mock.calls.filter(([url]) => String(url).endsWith("/video-jobs")),
    ).toHaveLength(0);
  });
});

describe("overview metrics", () => {
  it("counts projects, active jobs, completed analyses and unexpired published videos", async () => {
    serve(
      base({
        "GET /api/v1/projects": [alpha, beta],
        "GET /api/v1/jobs": [
          job(),
          job({ id: "a2", state: "running", error_code: null }),
          job({ id: "a3", synthetic: true, error_code: "phase1_fixture_boundary" }),
          job({ id: "a4", error_code: "secret_detected" }),
        ],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [
          videoJob({
            videos: [
              video(),
              video({ id: "v-arch", category: "architecture" }),
              video({ id: "v-old", expires_at: "2020-01-01T00:00:00Z" }),
            ],
          }),
          videoJob({ id: "vj-failed", state: "failed", videos: [video({ id: "never" })] }),
        ],
        [`GET /api/v1/projects/${beta.id}/video-jobs`]: [
          videoJob({ id: "vj-wait", project_id: beta.id, state: "awaiting_analysis", videos: [] }),
        ],
      }),
    );
    renderAt("/", <OverviewView />);
    const stat = (label: string) =>
      within(document.querySelector<HTMLElement>(".stat-grid")!).getByText(label).closest(".stat")!;
    await waitFor(() => expect(stat("Published videos").querySelector(".stat-value")).not.toBeNull());
    expect(stat("Projects").querySelector(".stat-value")).toHaveTextContent("2");
    // One running analysis plus one video job awaiting analysis.
    expect(stat("Active jobs").querySelector(".stat-value")).toHaveTextContent("2");
    // Only the Stage 9 boundary analysis: not the fixture, not the refused job.
    expect(stat("Completed analyses").querySelector(".stat-value")).toHaveTextContent("1");
    // Two unexpired videos of the succeeded job; the expired one and the failed job's are not.
    expect(stat("Published videos").querySelector(".stat-value")).toHaveTextContent("2");
    const activity = screen.getByRole("region", { name: "Recent activity" });
    const kinds = within(activity)
      .getAllByRole("link")
      .filter((link) => link.hasAttribute("data-kind"))
      .map((link) => link.getAttribute("data-kind"));
    expect(kinds).toContain("video");
    expect(kinds).toContain("analysis");
    expect(kinds.length).toBeLessThanOrEqual(5);
  });

  it("shows a loading skeleton, never a number, until video jobs settle", async () => {
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: () => new Promise<Response>(() => {}),
      }),
    );
    renderAt("/", <OverviewView />);
    const stat = (await screen.findByText("Published videos")).closest(".stat")!;
    expect(stat).toHaveAttribute("aria-busy", "true");
    expect(stat.querySelector(".stat-value")).toBeNull();
    expect(stat).toHaveTextContent("Loading…");
    expect(stat).not.toHaveTextContent(/\b0\b/);
  });

  it("says when video counts are incomplete", async () => {
    serve(
      base({
        "GET /api/v1/projects": [alpha, beta],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [videoJob()],
        [`GET /api/v1/projects/${beta.id}/video-jobs`]: () =>
          respond({ error: { code: "internal_error" } }, 500),
      }),
    );
    renderAt("/", <OverviewView />);
    expect(await screen.findByText("Unexpired videos from 1 of 2 projects")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Beta tools");
  });

  it("shows no video number when videos are not enabled", async () => {
    serve(base({ "GET /api/v1/auth/session": { ...account, video_enabled: false } }));
    renderAt("/", <OverviewView />);
    const stat = (await screen.findByText("Published videos")).closest(".stat")!;
    expect(stat.querySelector(".stat-value")).toHaveTextContent("—");
  });
});

describe("job details", () => {
  it("shows a Stage 9 boundary as complete and keeps the raw state in technical details", async () => {
    serve(base({ [`GET /api/v1/jobs/${job().id}`]: job() }));
    renderAt(`/jobs/${job().id}`, <JobDetailView jobId={job().id} />);
    const header = await screen.findByRole("heading", { name: "Repository analysis" });
    const badge = header.closest(".page-header")!.querySelector(".badge")!;
    expect(badge).toHaveTextContent("Analysis complete");
    expect(badge).toHaveAttribute("data-tone", "succeeded");
    const details = screen.getByText("Technical details").closest("details")!;
    expect(within(details).getByText("Recorded state").nextElementSibling).toHaveTextContent(
      /^failed$/,
    );
    expect(within(details).getByText("Stop code").nextElementSibling).toHaveTextContent(
      /^phase2_pipeline_boundary$/,
    );
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
    expect(screen.queryByRole("region", { name: /credential/ })).toBeNull();
    // History shows the boundary entry as complete too.
    const history = screen.getByRole("region", { name: "History" });
    expect(within(history).getAllByText("Analysis complete")).toHaveLength(1);
  });

  it("adds remediation to a refused analysis without inventing where the secret is", async () => {
    const refused = job({ error_code: "secret_detected" });
    serve(base({ [`GET /api/v1/jobs/${refused.id}`]: refused }));
    renderAt(`/jobs/${refused.id}`, <JobDetailView jobId={refused.id} />);
    const panel = await screen.findByRole("region", {
      name: "The credential screen refused this snapshot",
    });
    expect(panel).toHaveTextContent("does not show which file, line or value matched");
    expect(panel).not.toHaveTextContent(/\b[\w-]+\/[\w./-]*\.[a-z]{1,5}\b/);
    expect(screen.getByRole("button", { name: "Retry pinned analysis" })).toBeVisible();
  });
});

describe("remediation where work is started", () => {
  it("adds quota guidance under a refused analysis request", async () => {
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}`]: alpha,
        [`GET /api/v1/projects/${alpha.id}/jobs`]: [],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [],
        [`POST /api/v1/development/projects/${alpha.id}/analysis-jobs`]: () =>
          respond({ error: { code: "monthly_quota" } }, 429),
      }),
    );
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    await userEvent.click(await screen.findByLabelText("I acknowledge this local source processing."));
    await userEvent.click(screen.getByRole("button", { name: "Analyze repository" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/analysis quota for this month/);
    const panel = screen.getByRole("region", { name: "Monthly analysis allowance used" });
    expect(panel).toHaveTextContent("Nothing was started by this attempt, and no allowance was used.");
  });

  it("adds guidance to a failed video job", async () => {
    serve(
      base({
        [`GET /api/v1/projects/${alpha.id}`]: alpha,
        [`GET /api/v1/projects/${alpha.id}/jobs`]: [job()],
        [`GET /api/v1/projects/${alpha.id}/video-jobs`]: [
          videoJob({ state: "failed", error_code: "media_timeout", videos: [] }),
        ],
      }),
    );
    renderAt(`/projects/${alpha.id}`, <ProjectDetailView projectId={alpha.id} />);
    const panel = await screen.findByRole("region", { name: "Video encoding took too long" });
    expect(panel).toHaveTextContent("counts against the monthly allowance");
    // A completed analysis still describes the project; the failed video job explains itself.
    expect(screen.getByText("Analysis complete", { selector: ".panel-header .badge" })).toBeVisible();
  });
});
