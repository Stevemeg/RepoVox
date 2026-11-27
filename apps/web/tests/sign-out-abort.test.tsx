import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { VideoStudio } from "../src/components/video/video-studio";
import { useWorkspace } from "../src/components/workspace/context";
import { JobDetailView } from "../src/components/workspace/job-detail";
import { OverviewView } from "../src/components/workspace/overview";
import { ProjectDetailView } from "../src/components/workspace/project-detail";
import { WorkspaceShell } from "../src/components/workspace/shell";
import type { Account, Job, Project, VideoJob } from "../src/lib/api";
import { VIDEO_JOB_CONCURRENCY } from "../src/lib/video-jobs";
import { JOB as STORY_JOB, WALKTHROUGH, videoJob as storyVideoJob } from "./story-fixture";

/*
 * The rapid sign-out race: signing out while workspace reads are still in flight must
 * cancel every one of them before POST /auth/sign-out is sent. Otherwise a trailing GET
 * reaches the API after the session has ended and is answered 401, which the browser
 * logs as a console error.
 */

const navigation = vi.hoisted(() => ({ path: "/", replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.path,
  useRouter: () => navigation,
}));

const account: Account = {
  id: "11111111-1111-4111-8111-111111111111",
  display_name: "Sam Rivera",
  email: "sam@example.test",
  environment: "development",
  fixtures_enabled: true,
  analysis_enabled: true,
  video_enabled: true,
  auth_provider: "dev",
  github_oauth_enabled: false,
};
const project = (n: number): Project => ({
  id: `aaaaaaaa-0000-4000-8000-${String(n).padStart(12, "0")}`,
  title: `Project ${n}`,
  repository_url: `https://github.com/example/project-${n}`,
  status: "unprocessed",
  created_at: "2026-11-01T00:00:00Z",
});
// More projects than the fan-out runs at once, so some are still queued when it is aborted.
const PROJECTS = Array.from({ length: VIDEO_JOB_CONCURRENCY + 2 }, (_, index) => project(index + 1));
const [first] = PROJECTS;
const analysisJob: Job = {
  id: "bbbbbbbb-0000-4000-8000-000000000001",
  project_id: first.id,
  project_title: first.title,
  state: "failed",
  version: 3,
  synthetic: false,
  fixture: "normal",
  error_code: "phase2_pipeline_boundary",
  created_at: "2026-11-20T10:00:00Z",
  deadline: "2026-11-20T11:00:00Z",
  commit_sha: "a".repeat(40),
  repository_url: first.repository_url,
  stages: [],
  history: [],
  attempts: [],
  usage: [],
};
const runningVideoJob: VideoJob = {
  ...storyVideoJob(),
  id: "cccccccc-0000-4000-8000-000000000001",
  project_id: first.id,
  state: "running",
  finished_at: null,
  videos: [],
};

const SESSION = "GET /api/v1/auth/session";
const SIGN_OUT = "POST /api/v1/auth/sign-out";
const videoJobsOf = (target: Project) => `GET /api/v1/projects/${target.id}/video-jobs`;
const STORY = `GET /api/v1/video-jobs/${STORY_JOB}/videos/${WALKTHROUGH}/story`;
const ANALYSIS = `GET /api/v1/development/jobs/${analysisJob.id}/analysis`;

const respond = (value: unknown, status = 200) =>
  new Response(value === undefined ? null : JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });

/** A request that stays in flight until its signal aborts. */
const HANG = Symbol("in flight until aborted");
type Route = typeof HANG | ((init: RequestInit) => Response | Promise<Response>) | object;
let routes: Record<string, Route> = {};
/** Every request sent and every abort, in the order they happened. */
let events: string[] = [];
type Sent = { key: string; at: number; signal: AbortSignal | null | undefined; status?: number };
let sent: Sent[] = [];
/** Set once the API has ended the session: every later read is answered 401. */
let sessionEnded = false;

const signOutOk = () => {
  sessionEnded = true;
  return respond(undefined, 204);
};

function fakeFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const method = init.method ?? "GET";
  const key = `${method} ${url}`;
  const { signal } = init;
  // A browser never sends a request whose signal has already aborted.
  if (signal?.aborted) {
    events.push(`unsent ${key}`);
    return Promise.reject(new DOMException("The operation was aborted.", "AbortError"));
  }
  const entry: Sent = { key, at: events.length, signal };
  events.push(`send ${key}`);
  sent.push(entry);
  const settle = (response: Response) => {
    entry.status = response.status;
    return response;
  };
  if (sessionEnded && method === "GET")
    return Promise.resolve(settle(respond({ error: { code: "session_required" } }, 401)));
  const route = routes[key];
  if (route === HANG)
    return new Promise((_, reject) =>
      signal?.addEventListener(
        "abort",
        () => {
          events.push(`abort ${key}`);
          reject(new DOMException("The operation was aborted.", "AbortError"));
        },
        { once: true },
      ),
    );
  if (typeof route === "function") return Promise.resolve(route(init)).then(settle);
  return Promise.resolve(
    settle(route === undefined ? respond({ error: { code: "not_found" } }, 404) : respond(route)),
  );
}

const fetcher = vi.fn(fakeFetch);
const requests = (key: string) => sent.filter((request) => request.key === key);
const videoJobRequests = () => sent.filter((request) => request.key.endsWith("/video-jobs"));
const signOutAt = () => events.indexOf(`send ${SIGN_OUT}`);

function serve(extra: Record<string, Route> = {}) {
  routes = {
    [SESSION]: account,
    "GET /api/v1/projects": PROJECTS,
    "GET /api/v1/jobs": [],
    ...Object.fromEntries(PROJECTS.map((target) => [videoJobsOf(target), []])),
    [SIGN_OUT]: signOutOk,
    ...extra,
  };
}

function renderAt(path: string, view: ReactNode) {
  navigation.path = path;
  return render(<WorkspaceShell>{view}</WorkspaceShell>);
}

/** Every given request was in flight, was aborted, and was aborted before sign-out was sent. */
function expectAbortedBeforeSignOut(keys: readonly string[]) {
  const post = signOutAt();
  expect(post).toBeGreaterThan(-1);
  for (const key of keys) {
    const [request] = requests(key);
    expect(request, key).toBeDefined();
    expect(request.signal?.aborted, key).toBe(true);
    const aborted = events.indexOf(`abort ${key}`);
    expect(aborted, key).toBeGreaterThan(-1);
    expect(aborted, key).toBeLessThan(post);
  }
}

/** Signed out to /sign-in with nothing sent after the sign-out, no 401 and no error shown. */
function expectCleanSignOut(errors: MockInstance) {
  const post = signOutAt();
  expect(events.slice(post + 1).filter((event) => !event.startsWith("abort "))).toEqual([]);
  expect(sent.filter((request) => request.status === 401)).toEqual([]);
  expect(navigation.replace.mock.calls).toEqual([["/sign-in"]]);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText(/could not be loaded|session expired/i)).toBeNull();
  expect(errors).not.toHaveBeenCalled();
}

/** A view that refreshes the shell on demand, to hold the shell's own load in flight. */
function RefreshButton() {
  const { refresh } = useWorkspace();
  return (
    <button type="button" onClick={() => void refresh()}>
      Refresh workspace
    </button>
  );
}

let errors: MockInstance;
beforeEach(() => {
  navigation.path = "/";
  navigation.replace.mockReset();
  navigation.push.mockReset();
  events = [];
  sent = [];
  sessionEnded = false;
  serve();
  fetcher.mockClear();
  vi.stubGlobal("fetch", fetcher);
  document.cookie = "rv_csrf=test-csrf;path=/";
  errors = vi.spyOn(console, "error");
});
afterEach(() => {
  errors.mockRestore();
  document.cookie = "rv_csrf=;path=/;max-age=0";
  vi.unstubAllGlobals();
});

describe("rapid sign-out", () => {
  it("aborts the per-project video-job fan-out before POST /auth/sign-out and starts no queued project", async () => {
    serve(Object.fromEntries(PROJECTS.map((target) => [videoJobsOf(target), HANG])));
    renderAt("/", <OverviewView />);
    const button = await screen.findByRole("button", { name: "Sign out" });
    await waitFor(() => expect(videoJobRequests()).toHaveLength(VIDEO_JOB_CONCURRENCY));
    await userEvent.click(button);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/sign-in"));

    // Only the bounded window was ever sent: the queued projects never started.
    expect(PROJECTS.length).toBeGreaterThan(VIDEO_JOB_CONCURRENCY);
    expect(videoJobRequests()).toHaveLength(VIDEO_JOB_CONCURRENCY);
    expectAbortedBeforeSignOut(videoJobRequests().map((request) => request.key));
    expect(header(SIGN_OUT, "x-csrf-token")).toBe("test-csrf");
    expectCleanSignOut(errors);
  });

  it("aborts the shell's own in-flight refresh before signing out", async () => {
    renderAt("/", <RefreshButton />);
    const button = await screen.findByRole("button", { name: "Sign out" });
    routes[SESSION] = HANG;
    await userEvent.click(screen.getByRole("button", { name: "Refresh workspace" }));
    await waitFor(() => expect(requests(SESSION)).toHaveLength(2));
    await userEvent.click(button);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/sign-in"));
    const [, refresh] = requests(SESSION);
    expect(refresh.signal?.aborted).toBe(true);
    expect(events.indexOf(`abort ${SESSION}`)).toBeLessThan(signOutAt());
    expectCleanSignOut(errors);
  });

  it.each([
    {
      name: "the project page's project and job reads",
      path: `/projects/${first.id}`,
      view: () => <ProjectDetailView projectId={first.id} />,
      hung: [`GET /api/v1/projects/${first.id}`, `GET /api/v1/projects/${first.id}/jobs`],
      ready: undefined,
    },
    {
      name: "the project page's video-job read (VideoJobs)",
      path: `/projects/${first.id}`,
      view: () => <ProjectDetailView projectId={first.id} />,
      routes: {
        [`GET /api/v1/projects/${first.id}`]: first,
        [`GET /api/v1/projects/${first.id}/jobs`]: [],
      },
      hung: [videoJobsOf(first)],
      ready: "Narrated videos",
    },
    {
      name: "the walkthrough story read (useVideoStory)",
      path: "/",
      view: () => <VideoStudio job={storyVideoJob()} />,
      hung: [STORY],
      ready: undefined,
    },
    {
      name: "the job page's own read",
      path: `/jobs/${analysisJob.id}`,
      view: () => <JobDetailView jobId={analysisJob.id} />,
      hung: [`GET /api/v1/jobs/${analysisJob.id}`],
      ready: undefined,
    },
    {
      name: "the job page's verified analysis read (AnalysisPanel)",
      path: `/jobs/${analysisJob.id}`,
      view: () => <JobDetailView jobId={analysisJob.id} />,
      routes: { [`GET /api/v1/jobs/${analysisJob.id}`]: analysisJob },
      hung: [ANALYSIS],
      ready: "Loading verified analysis…",
    },
  ])("aborts $name before signing out, without an error notice", async (scenario) => {
    serve({
      ...("routes" in scenario ? scenario.routes : {}),
      ...Object.fromEntries(scenario.hung.map((key) => [key, HANG])),
    });
    renderAt(scenario.path, scenario.view());
    const button = await screen.findByRole("button", { name: "Sign out" });
    if (scenario.ready) expect(await screen.findByText(scenario.ready)).toBeVisible();
    await waitFor(() => {
      for (const key of scenario.hung) expect(requests(key), key).toHaveLength(1);
    });
    await userEvent.click(button);
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/sign-in"));
    expectAbortedBeforeSignOut(scenario.hung);
    expectCleanSignOut(errors);
  });

  it("starts no polling read while sign-out is in progress", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      serve({
        [videoJobsOf(first)]: [runningVideoJob],
        // Sign-out stays in progress for the rest of the test.
        [SIGN_OUT]: () => new Promise<Response>(() => {}),
      });
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      renderAt("/", <OverviewView />);
      const button = await screen.findByRole("button", { name: "Sign out" });
      await waitFor(() => expect(requests(videoJobsOf(first))).toHaveLength(1));

      // Polling is live: one interval refreshes the shell and the active video job.
      await act(() => vi.advanceTimersByTimeAsync(5_000));
      expect(requests(SESSION).length).toBeGreaterThan(1);
      expect(requests(videoJobsOf(first)).length).toBeGreaterThan(1);

      await user.click(button);
      const post = signOutAt();
      expect(post).toBeGreaterThan(-1);
      expect(button).toBeDisabled();
      await act(() => vi.advanceTimersByTimeAsync(30_000));
      // Nothing at all after the sign-out request: no poll was sent or even attempted.
      expect(events.slice(post + 1)).toEqual([]);
      expect(errors).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("recovers with a fresh session signal when sign-out fails with 503", async () => {
    serve({
      ...Object.fromEntries(PROJECTS.map((target) => [videoJobsOf(target), HANG])),
      [SIGN_OUT]: () =>
        respond({ error: { code: "dependency_unavailable", request_id: "req-503" } }, 503),
    });
    renderAt("/", <OverviewView />);
    const button = await screen.findByRole("button", { name: "Sign out" });
    await waitFor(() => expect(videoJobRequests()).toHaveLength(VIDEO_JOB_CONCURRENCY));
    // From now on the API answers the video-job reads.
    for (const target of PROJECTS) routes[videoJobsOf(target)] = [];

    await userEvent.click(button);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A required service is temporarily unavailable");
    expect(alert).toHaveTextContent("request req-503");
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeEnabled();
    const post = signOutAt();
    expectAbortedBeforeSignOut(
      videoJobRequests()
        .filter((request) => request.at < post)
        .map((request) => request.key),
    );

    // The cancelled fan-out runs again with the fresh signal and completes for every project.
    const reloaded = () =>
      videoJobRequests().filter((request) => request.at > post && request.status === 200);
    await waitFor(() => expect(reloaded()).toHaveLength(PROJECTS.length));
    for (const request of reloaded()) expect(request.signal?.aborted).toBe(false);
    // Reloading the views does not clear the notice that says why sign-out failed.
    expect(screen.getByRole("alert")).toHaveTextContent("A required service is temporarily unavailable");

    // Retrying reloads the shell with a live signal and clears the notice.
    await userEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    const retried = requests(SESSION).at(-1)!;
    expect(retried.at).toBeGreaterThan(post);
    expect(retried.status).toBe(200);
    expect(retried.signal?.aborted).toBe(false);

    // And the next sign-out completes cleanly.
    routes[SIGN_OUT] = signOutOk;
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/sign-in"));
    expect(sent.filter((request) => request.status === 401)).toEqual([]);
    expect(errors).not.toHaveBeenCalled();
  });

  it("aborts the project page's video-job read when the page unmounts", async () => {
    serve({
      [`GET /api/v1/projects/${first.id}`]: first,
      [`GET /api/v1/projects/${first.id}/jobs`]: [],
      [videoJobsOf(first)]: HANG,
    });
    const { unmount } = renderAt(`/projects/${first.id}`, <ProjectDetailView projectId={first.id} />);
    await waitFor(() => expect(requests(videoJobsOf(first))).toHaveLength(1));
    unmount();
    expect(requests(videoJobsOf(first))[0].signal?.aborted).toBe(true);
    expect(events).toContain(`abort ${videoJobsOf(first)}`);
  });
});

function header(key: string, name: string) {
  const index = fetcher.mock.calls.findIndex(
    ([url, init]) => `${init?.method ?? "GET"} ${url}` === key,
  );
  return new Headers(fetcher.mock.calls[index]?.[1]?.headers).get(name);
}
