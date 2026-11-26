import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StoryExplorer } from "../src/components/video/story-explorer";
import { VideoStudio } from "../src/components/video/video-studio";
import { WorkspaceContext, type WorkspaceValue } from "../src/components/workspace/context";
import { normalizeVideoStory } from "../src/lib/story-types";
import {
  claim,
  COMMIT,
  JOB,
  OTHER_COMMIT,
  permalink,
  ref,
  respond,
  routedFetch,
  SCOPE,
  STATUS_LABELS,
  storyResponse,
  videoJob,
  WALKTHROUGH,
} from "./story-fixture";

afterEach(() => vi.unstubAllGlobals());

const walkthrough = videoJob().videos[1];

/** Renders the explorer for an already-loaded story. */
function renderStory(raw: unknown = storyResponse()) {
  const normalized = normalizeVideoStory(raw)!;
  return render(
    <StoryExplorer
      video={walkthrough}
      state={{ status: "loaded", view: normalized.view, issues: normalized.issues }}
      expired={false}
      walkthrough={walkthrough}
      onRetry={() => undefined}
      onShowWalkthrough={() => undefined}
    />,
  );
}

const tab = (name: RegExp) => screen.getByRole("tab", { name });
const panel = () => screen.getByRole("tabpanel");
const TAB_NAMES = [/Summary & mismatches/, /Problem & solution/, /Implementation & architecture/, /Outcomes, limitations/];

describe("rule 1: literal status badges", () => {
  it("shows the four contract labels with four distinct tones in the status breakdown", () => {
    renderStory();
    const breakdown = screen.getByRole("list", { name: "Claims by verification status" });
    const rows = within(breakdown).getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "VERIFIED3",
      "INFERRED2",
      "AUTHOR-STATED / NOT VERIFIED BY CODE1",
      "UNVERIFIED2",
    ]);
    const tones = rows.map((row) => row.querySelector(".badge")!.getAttribute("data-tone"));
    expect(tones).toEqual(["verified", "inferred", "author-stated", "unverified"]);
    expect(screen.getByText(/8 claims in total/)).toBeVisible();
    expect(screen.getByText("README:", { exact: false })).toHaveTextContent("README: 1");
    expect(screen.getByText("Source:", { exact: false })).toHaveTextContent("Source: 3");
  });

  it("badges every claim in every tab with exactly its status label, never relabelled", () => {
    const raw = storyResponse({
      status_labels: { ...STATUS_LABELS, DOCUMENTATION_ONLY: "VERIFIED" },
    });
    renderStory(raw);
    const seen = new Set<string>();
    for (const name of TAB_NAMES) {
      fireEvent.click(tab(name));
      for (const item of panel().querySelectorAll(".story-claim")) {
        const status = item.getAttribute("data-status")!;
        const badge = item.querySelector(".badge")!;
        expect(badge.textContent).toBe(STATUS_LABELS[status as keyof typeof STATUS_LABELS]);
        expect(badge.getAttribute("data-state")).toBe(status);
        seen.add(status);
      }
    }
    expect([...seen].sort()).toEqual(["DOCUMENTATION_ONLY", "INFERRED", "UNVERIFIED", "VERIFIED"]);
    fireEvent.click(tab(/Problem & solution/));
    const stated = panel().querySelector('[data-claim-id="i-intended"] .badge')!;
    expect(stated).toHaveTextContent("AUTHOR-STATED / NOT VERIFIED BY CODE");
    expect(stated).toHaveAttribute("data-tone", "author-stated");
    // The malformed label was refused and disclosed.
    fireEvent.click(tab(/Summary & mismatches/));
    expect(screen.getByText(/1 story entry did not match the story contract/)).toBeVisible();
  });
});

describe("rule 2: mismatches are first-class", () => {
  it("lists every mismatch in the default tab with kind, detail and resolved claims", () => {
    renderStory();
    expect(tab(/Summary & mismatches/)).toHaveAttribute("aria-selected", "true");
    expect(tab(/Summary & mismatches/)).toHaveTextContent("2 mismatches");
    const region = screen.getByRole("region", { name: /Mismatches/ });
    expect(region).toHaveAttribute("data-count", "2");
    expect(region.closest("details")).toBeNull();
    const items = within(region).getAllByRole("listitem").filter((item) => item.classList.contains("mismatch"));
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Declared-only technology");
    expect(items[0]).toHaveTextContent("declared_only_technology");
    expect(items[0]).toHaveTextContent("SyntheticDB is declared as a dependency, but no analysed source file imports it.");
    // Stated side: the author-stated claim, with its literal badge.
    expect(within(items[0]).getByText("The demo serves a synthetic greeting service.")).toBeVisible();
    expect(within(items[0]).getByText("AUTHOR-STATED / NOT VERIFIED BY CODE")).toBeVisible();
    expect(within(items[0]).getByText("SyntheticDB is declared as a dependency.")).toBeVisible();
    expect(items[1]).toHaveTextContent("Unstated implementation");
    expect(within(items[1]).getByText(/No stated claim: the documentation says nothing about this/)).toBeVisible();
  });

  it("jumps from a mismatch to its claim, and from the claim back to the mismatch", async () => {
    renderStory();
    const region = screen.getByRole("region", { name: /Mismatches/ });
    fireEvent.click(within(region).getAllByRole("button", { name: /Show claim, i-intended, in the story/ })[0]);
    expect(tab(/Problem & solution/)).toHaveAttribute("aria-selected", "true");
    const target = panel().querySelector('[data-claim-id="i-intended"]')!;
    await waitFor(() => expect(target).toHaveFocus());
    const chip = within(target as HTMLElement).getByRole("button", { name: /Stated side of a mismatch: Declared-only technology/ });
    fireEvent.click(chip);
    expect(tab(/Summary & mismatches/)).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(document.activeElement).toHaveAttribute("data-kind", "declared_only_technology"));
  });

  it("states explicitly when no mismatch was detected", () => {
    renderStory(storyResponse({ mismatches: [] }));
    expect(tab(/Summary & mismatches/)).toHaveTextContent("0 mismatches");
    expect(screen.getByText(/No mismatches were detected/)).toBeVisible();
  });
});

describe("rule 3: an undocumented problem is said plainly", () => {
  it("shows a prominent notice above every tab when the problem is undocumented", () => {
    renderStory();
    const undocumented = document.querySelector('[data-problem="undocumented"]')!;
    expect(undocumented).toHaveTextContent("This repository does not document the problem it solves.");
    expect(undocumented).toHaveTextContent(/did not infer or invent a problem from the repository's name or description/);
    for (const name of TAB_NAMES) {
      fireEvent.click(tab(name));
      expect(document.querySelector('[data-problem="undocumented"]')).not.toBeNull();
    }
  });

  it("shows no such notice for a documented problem", () => {
    const documented = claim({
      id: "p-stated",
      text: "Teams need a synthetic greeting.",
      status: "DOCUMENTATION_ONLY",
      evidence_type: "author_stated_problem",
      refs: [ref("e-p", "README.md", 1, "Teams need a synthetic greeting.")],
    });
    renderStory(storyResponse({ problem_statement: { sufficiency: "documented", claims: [documented] } }));
    expect(document.querySelector('[data-problem="undocumented"]')).toBeNull();
    expect(screen.getByText(/documents the problem it solves/)).toBeVisible();
  });
});

describe("rule 4: tests were read, not run", () => {
  it("shows the outcome scope verbatim next to the outcomes, and never says tests pass", () => {
    const { container } = renderStory();
    fireEvent.click(tab(/Outcomes, limitations/));
    expect(screen.getByText("Tests were read, not run.")).toBeVisible();
    expect(container.querySelector("[data-outcome-scope]")!.textContent).toBe(SCOPE);
    expect(screen.getByText(/Unit test source, read and not run/)).toBeVisible();
    expect(container.textContent).not.toMatch(/tests? pass/i);
  });
});

describe("rules 6 and 7: untrusted text and pinned citations", () => {
  const hostile = () =>
    storyResponse({
      implementation_approach: {
        claims: [
          claim({
            id: "i-xss",
            text: '<img src=x onerror="alert(1)"> claim',
            status: "VERIFIED",
            evidence_type: "implemented_solution",
            refs: [
              ref("e-ok", "app/<b>main</b>.py", 3, "<script>alert(1)</script>", permalink("app/main.py", 3)),
              ref("e-other", "app/x.py", 4, "x = 1", permalink("app/x.py", 4, OTHER_COMMIT)),
              ref("e-js", "app/y.py", 5, "y = 2", "javascript:alert(1)"),
              ref("e-branch", "app/z.py", 6, "z = 3", "https://github.com/example/demo/blob/main/app/z.py#L6-L6"),
            ],
          }),
        ],
        decisions: [],
      },
      mismatches: [
        {
          id: "x-xss",
          kind: "readme_only_feature",
          detail: "<iframe src=javascript:alert(1)></iframe> detail",
          stated_claim_ids: ["i-xss"],
          evidence_claim_ids: [],
        },
      ],
    });

  it("renders hostile claim text, paths, quotes and mismatch details as inert text", () => {
    const { container } = renderStory(hostile());
    expect(screen.getByText("<iframe src=javascript:alert(1)></iframe> detail")).toBeVisible();
    fireEvent.click(tab(/Implementation & architecture/));
    expect(screen.getByText('<img src=x onerror="alert(1)"> claim')).toBeVisible();
    expect(screen.getByText("app/<b>main</b>.py:3-3")).toBeVisible();
    expect(screen.getByText("<script>alert(1)</script>").tagName).toBe("PRE");
    expect(container.querySelector("script, img, iframe, b")).toBeNull();
  });

  it("links only commit-pinned GitHub permalinks, through ExternalLink, and says why others are withheld", () => {
    const { container } = renderStory(hostile());
    fireEvent.click(tab(/Implementation & architecture/));
    const links = [...container.querySelectorAll("a")];
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", permalink("app/main.py", 3));
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(links[0]).toHaveTextContent(`View these lines on GitHub at commit ${COMMIT.slice(0, 7)}`);
    expect(container.querySelectorAll('[data-permalink="withheld"]')).toHaveLength(3);
    const attributes = [...container.querySelectorAll("*")].flatMap((element) =>
      [...element.attributes].map((attribute) => attribute.value),
    );
    expect(attributes.some((value) => value.includes("javascript:"))).toBe(false);
    expect(attributes.some((value) => value.includes("/blob/main/"))).toBe(false);
    expect(attributes.some((value) => value.includes(OTHER_COMMIT))).toBe(false);
  });

  it("links no citation when the story has no valid pinned commit", () => {
    const { container } = renderStory(storyResponse({ commit_sha: "not-a-sha" }));
    fireEvent.click(tab(/Implementation & architecture/));
    expect(container.querySelector("a")).toBeNull();
    expect(screen.getAllByText(/did not record a valid pinned commit/).length).toBeGreaterThan(0);
  });

  it("shows path:start-end citations for every claim's evidence", () => {
    renderStory();
    fireEvent.click(tab(/Implementation & architecture/));
    expect(screen.getByText("app/main.py:12-12")).toBeVisible();
    expect(screen.getByText("pyproject.toml:8-8")).toBeVisible();
    expect(screen.getAllByText("app/main.py:12").length).toBeGreaterThan(0);
  });
});

describe("summary, disclosures and keyboard use", () => {
  it("discloses trimmed evidence, instruction-like README lines and the story record", () => {
    renderStory();
    expect(document.querySelector('[data-disclosure="evidence-trimmed"]')).toHaveTextContent(/at most 3 citations/);
    expect(document.querySelector('[data-disclosure="instruction-like-lines"]')).toHaveTextContent(
      "2 README lines read like instructions addressed to an AI model. RepoVox counted them and did not follow or use them.",
    );
    expect(screen.getByText(COMMIT)).toBeVisible();
    expect(screen.getByText("problem-to-solution-extractor-1.0")).toBeVisible();
    expect(screen.getByText(/Deterministic template wording \(no language model\); voice kokoro_onnx \/ kokoro-onnx \/ af_heart\./)).toBeVisible();
  });

  it("moves between tabs with the arrow, Home and End keys, with one tab stop", () => {
    renderStory();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((item) => item.tabIndex)).toEqual([0, -1, -1, -1]);
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(screen.getAllByRole("tab")[1]).toHaveFocus();
    expect(screen.getAllByRole("tab")[1]).toHaveAttribute("aria-selected", "true");
    expect(panel()).toHaveAttribute("aria-labelledby", screen.getAllByRole("tab")[1].id);
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(screen.getAllByRole("tab")[3]).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(screen.getAllByRole("tab")[0]).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    expect(screen.getAllByRole("tab")[3]).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(screen.getAllByRole("tab")[0]).toHaveFocus();
    expect(screen.getAllByRole("tab").map((item) => item.tabIndex)).toEqual([0, -1, -1, -1]);
    // Every tab controls a panel that exists.
    for (const item of screen.getAllByRole("tab"))
      expect(document.getElementById(item.getAttribute("aria-controls")!)).not.toBeNull();
  });
});

describe("loading the story", () => {
  const listUrl = "/api/v1/projects/11111111-1111-4111-8111-111111111111/video-jobs";
  const stub = (story: () => Response | Promise<Response>) => {
    const fetch = vi.fn(routedFetch({ "/story": story, [listUrl]: () => respond([videoJob()]) }));
    vi.stubGlobal("fetch", fetch);
    return fetch;
  };
  const storyCalls = (fetch: ReturnType<typeof vi.fn>) =>
    fetch.mock.calls.filter(([url]) => String(url).endsWith("/story"));

  it("requests the walkthrough story with a plain GET: no CSRF token and no content type", async () => {
    document.cookie = "rv_csrf=synthetic-token";
    try {
      const fetch = stub(() => respond(storyResponse()));
      render(<VideoStudio job={videoJob()} />);
      await screen.findByRole("tab", { name: /Summary & mismatches/ });
      const [url, init] = storyCalls(fetch)[0];
      expect(url).toBe(`/api/v1/video-jobs/${JOB}/videos/${WALKTHROUGH}/story`);
      expect(init.method).toBe("GET");
      expect(init.credentials).toBe("same-origin");
      expect(init.signal).toBeInstanceOf(AbortSignal);
      expect(init.body).toBeUndefined();
      const headers = new Headers(init.headers);
      expect(headers.get("X-CSRF-Token")).toBeNull();
      expect(headers.get("Content-Type")).toBeNull();
      expect(headers.get("Idempotency-Key")).toBeNull();
    } finally {
      document.cookie = "rv_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    }
  });

  it("shows a calm note for a walkthrough without a story, not an error", async () => {
    stub(() => respond({ error: { code: "story_not_available", request_id: "r-1" } }, 404));
    render(<VideoStudio job={videoJob()} />);
    const note = await screen.findByText(/No structured problem-to-solution story is available for this walkthrough/);
    expect(note.closest("[data-story]")).toHaveAttribute("data-story", "not-available");
    expect(note.closest('[role="status"]')).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText("Repository walkthrough")).toBeVisible();
  });

  it("explains that explainers carry no story and jumps to the walkthrough in one click", async () => {
    const fetch = stub(() => respond(storyResponse()));
    render(<VideoStudio job={videoJob()} />);
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
    fireEvent.click(screen.getByRole("button", { name: /System architecture across 2 tiers/ }));
    expect(await screen.findByText(/This video carries no problem-to-solution story/)).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show the repository walkthrough and its story" }));
    expect(screen.getByRole("button", { name: /Repository walkthrough/ })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(document.activeElement).toHaveAttribute("data-video-id", WALKTHROUGH));
    // The walkthrough's story was kept: switching back does not refetch it.
    await screen.findByRole("tab", { name: /Summary & mismatches/ });
    expect(storyCalls(fetch)).toHaveLength(1);
  });

  it("refuses to show a story that failed its integrity check, without breaking playback", async () => {
    stub(() => respond({ error: { code: "story_corrupt", request_id: "r-2" } }, 503));
    render(<VideoStudio job={videoJob()} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This video's engineering story failed its integrity check, so RepoVox will not show it.");
    expect(alert).toHaveTextContent("Reference: story_corrupt · request r-2");
    expect(within(alert).queryByRole("button")).toBeNull();
    expect(screen.getByText(/RepoVox refuses to show a story it cannot verify/)).toBeVisible();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.getByLabelText("Repository walkthrough")).toBeVisible();
  });

  it("offers a retry after a network failure and loads the story on retry", async () => {
    let calls = 0;
    const fetch = stub(() => {
      calls += 1;
      if (calls === 1) throw new TypeError("network down");
      return respond(storyResponse());
    });
    render(<VideoStudio job={videoJob()} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("RepoVox could not be reached. Check your connection and try again.");
    expect(screen.getByText(/Playback is unaffected/)).toBeVisible();
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("tab", { name: /Summary & mismatches/ })).toBeVisible();
    expect(storyCalls(fetch)).toHaveLength(2);
  });

  it("does not show a response that is not shaped like a story", async () => {
    stub(() => respond({ story: "<script>alert(1)</script>" }));
    const { container } = render(<VideoStudio job={videoJob()} />);
    expect(await screen.findByText(/The story response could not be read/)).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
  });

  it("aborts the story request when another video is selected", async () => {
    let signal: AbortSignal | undefined;
    const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      signal = init?.signal ?? undefined;
      return new Promise<Response>((_, reject) =>
        signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
      );
    });
    vi.stubGlobal("fetch", fetch);
    render(<VideoStudio job={videoJob()} />);
    expect(screen.getByText(/Loading the problem-to-solution story/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /HTTP service in app\/main.py/ }));
    expect(signal?.aborted).toBe(true);
    expect(await screen.findByText(/This video carries no problem-to-solution story/)).toBeVisible();
  });

  it("hands a 401 to the workspace session handler", async () => {
    stub(() => respond({ error: { code: "session_expired" } }, 401));
    const handleUnauthorized = vi.fn(() => true);
    render(
      <WorkspaceContext.Provider value={{ handleUnauthorized } as unknown as WorkspaceValue}>
        <VideoStudio job={videoJob()} />
      </WorkspaceContext.Provider>,
    );
    await waitFor(() => expect(handleUnauthorized).toHaveBeenCalledOnce());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not request a story for an expired walkthrough", () => {
    const fetch = stub(() => respond(storyResponse()));
    render(
      <StoryExplorer
        video={walkthrough}
        state={{ status: "idle" }}
        expired
        walkthrough={null}
        onRetry={() => undefined}
        onShowWalkthrough={() => undefined}
      />,
    );
    expect(screen.getByText(/its story is no longer available/)).toBeVisible();
    expect(storyCalls(fetch)).toHaveLength(0);
  });
});
