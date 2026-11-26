import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnalysisPanel } from "../src/components/analysis-panel";

const sha = "a".repeat(40);
const other = "b".repeat(40);
const permalink = (path: string, commit = sha) =>
  `https://github.com/example/demo/blob/${commit}/${path}#L1-L2`;

type Overrides = {
  modules?: string[];
  claims?: { id: string; text: string; status: string; reason: string }[];
  evidence?: Record<string, unknown>[];
  files?: Record<string, unknown>[];
  limitations?: string[];
};
function analysis(overrides: Overrides = {}) {
  return {
    commit_sha: sha,
    payload: {
      knowledge: {
        repository: { canonical_url: "https://github.com/example/demo" },
        stack: ["python", "typescript"],
        frameworks: [{ name: "FastAPI", qualification: "import" }],
        modules: overrides.modules ?? ["app/main.py", "app/routes.py", "web/index.ts"],
        nodes: [
          { id: "n1", path: "app/main.py", name: "main" },
          { id: "n2", path: "app/routes.py", name: "router" },
        ],
        entrypoints: {
          candidates: [
            { symbol_id: "s1", path: "app/main.py", rule: "python-main", category: "executable_application" },
          ],
          uncertainty: ["No single entrypoint was selected."],
        },
        edges: [
          {
            id: "e1",
            source: "n1",
            target: "n2",
            relationship: "imports",
            classification: "resolved_static",
            qualification: "Static syntax only.",
          },
        ],
        claims: overrides.claims ?? [
          { id: "c1", text: "main imports routes", status: "verified", reason: "Import resolved" },
          { id: "c2", text: "router serves HTTP", status: "inferred", reason: "Framework pattern" },
          { id: "c3", text: "README says it scales", status: "documentation_only", reason: "Docs only" },
        ],
        coverage: {
          coverage: 0.5,
          parsed_bytes: 50,
          eligible_bytes: 100,
          files: overrides.files ?? [
            { path: "app/main.py", status: "parsed", reason: "parsed_without_errors" },
            { path: "models/net.pt", status: "skipped", reason: "ml_weight_container", bytes: 2048 },
            { path: "tests/test_app.py", status: "parsed", reason: "parsed_test_calls_omitted" },
            { path: "dist/bundle.js", status: "skipped", reason: "vendor_or_build" },
            { path: "broken.py", status: "failed", reason: "parse_error" },
          ],
        },
        limitations: overrides.limitations ?? [
          "Calls do not prove execution.",
          "Test-fact budget: the repository exceeded the 10,000-fact analysis cap, so call facts from 1 test file were omitted; their test definitions and imports were kept. The budget omitted no source-file fact.",
        ],
        versions: { pipeline: "phase2-static-v1", schema: "analysis-2.3" },
      },
      evidence: {
        items: overrides.evidence ?? [
          {
            id: "ev1",
            path: "app/main.py",
            start_line: 1,
            end_line: 2,
            permalink: permalink("app/main.py"),
            excerpt: "import routes\n<img src=x onerror=alert(1)>",
            validation_status: "valid",
            redacted: false,
          },
          {
            id: "ev2",
            path: "app/routes.py",
            start_line: 1,
            end_line: 2,
            permalink: permalink("app/routes.py"),
            excerpt: "router = Router()",
            validation_status: "valid",
            redacted: true,
          },
          {
            id: "ev3",
            path: "app/stale.py",
            start_line: 1,
            end_line: 2,
            permalink: permalink("app/stale.py"),
            excerpt: "stale",
            validation_status: "stale",
            redacted: false,
          },
        ],
      },
      verification: {
        counts: { verified: 1, inferred: 1, documentation_only: 1, unsupported: 0 },
        conflicts: ["Two claims disagree about the router."],
      },
    },
  };
}

function mount(body: unknown) {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
  return render(<AnalysisPanel jobId="44444444-4444-4444-8444-444444444444" />);
}
const tab = (name: RegExp) => screen.getByRole("tab", { name });
const panel = () => screen.getByRole("tabpanel");

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

describe("analysis explorer tabs", () => {
  it("is an accessible tab set where every tab controls a real panel", async () => {
    mount(analysis());
    expect(await screen.findByText("Verified static analysis")).toBeVisible();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((item) => item.textContent?.replace(/[,\d].*$/, "").trim())).toEqual([
      "Overview & coverage",
      "Modules & entrypoints",
      "Claims",
      "Code evidence",
      "Limitations & skipped files",
    ]);
    for (const item of tabs)
      expect(document.getElementById(item.getAttribute("aria-controls")!)).not.toBeNull();
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(tabs.filter((item) => item.tabIndex === 0)).toHaveLength(1);
    expect(within(panel()).getByText("python, typescript")).toBeVisible();
    expect(within(panel()).getByText("FastAPI")).toBeVisible();
    expect(within(panel()).getByText(/50 \/ 100 \(50\.0%\)/)).toBeVisible();
  });

  it("moves between sections with the arrow, Home and End keys", async () => {
    mount(analysis());
    await screen.findByText("Verified static analysis");
    tab(/^Overview/).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab(/^Modules/)).toHaveFocus();
    expect(tab(/^Modules/)).toHaveAttribute("aria-selected", "true");
    expect(panel()).toHaveAttribute("aria-labelledby", tab(/^Modules/).id);
    await userEvent.keyboard("{End}");
    expect(tab(/^Limitations/)).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab(/^Overview/)).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(tab(/^Limitations/)).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Home}");
    expect(tab(/^Overview/)).toHaveAttribute("aria-selected", "true");
  });
});

describe("search and claim verdicts", () => {
  it("filters modules, claims and evidence as plain text and shows match counts", async () => {
    mount(analysis());
    await screen.findByText("Verified static analysis");
    await userEvent.type(screen.getByLabelText("Search this analysis"), "ROUTES");
    expect(tab(/^Claims/)).toHaveTextContent(/1\s*matching/);
    await userEvent.click(tab(/^Modules/));
    expect(within(panel()).getByText("Showing all 1 modules matching (3 in total).")).toBeVisible();
    expect(within(panel()).getByText("app/routes.py")).toBeVisible();
    expect(within(panel()).queryByText("web/index.ts")).toBeNull();
    await userEvent.click(tab(/^Claims/));
    expect(within(panel()).getByText("main imports routes")).toBeVisible();
    expect(within(panel()).queryByText("router serves HTTP")).toBeNull();
    await userEvent.click(tab(/^Code evidence/));
    // Matches the excerpt of ev1 ("import routes") and the path of ev2.
    expect(panel().querySelectorAll("details.evidence")).toHaveLength(2);
    await userEvent.clear(screen.getByLabelText("Search this analysis"));
    await userEvent.type(screen.getByLabelText("Search this analysis"), "(.*");
    expect(within(panel()).getByText("No citations match this search.")).toBeVisible();
  });

  it("offers All plus exactly the verdicts present, and filters by them", async () => {
    mount(analysis());
    await screen.findByText("Verified static analysis");
    await userEvent.click(tab(/^Claims/));
    const select = within(panel()).getByLabelText("Claim verdict");
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "All verdicts (3)",
      "documentation only (1)",
      "inferred (1)",
      "verified (1)",
    ]);
    await userEvent.selectOptions(select, "inferred");
    expect(within(panel()).getByText("router serves HTTP")).toBeVisible();
    expect(within(panel()).queryByText("main imports routes")).toBeNull();
    const badge = within(panel()).getByText("inferred", { selector: ".badge" });
    expect(badge).toHaveAttribute("data-tone", "inferred");
    await userEvent.selectOptions(select, "all");
    expect(within(panel()).getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("display caps", () => {
  it("discloses every cap and reveals the rest on request", async () => {
    const modules = Array.from({ length: 120 }, (_, index) => `pkg/mod_${String(index).padStart(3, "0")}.py`);
    mount(analysis({ modules }));
    await screen.findByText("Verified static analysis");
    await userEvent.click(tab(/^Modules/));
    expect(within(panel()).getByText("Showing 50 of 120 modules.")).toBeVisible();
    expect(within(panel()).getAllByText(/^pkg\/mod_/)).toHaveLength(50);
    await userEvent.click(within(panel()).getByRole("button", { name: "Show 50 more modules" }));
    expect(within(panel()).getByText("Showing 100 of 120 modules.")).toBeVisible();
    await userEvent.click(within(panel()).getByRole("button", { name: "Show 20 more modules" }));
    expect(within(panel()).getByText("Showing all 120 modules.")).toBeVisible();
    expect(within(panel()).getAllByText(/^pkg\/mod_/)).toHaveLength(120);
    expect(within(panel()).queryByRole("button", { name: /Show \d+ more/ })).toBeNull();
  });
});

describe("evidence links", () => {
  it("links only permalinks pinned to this exact commit, and says when it does not", async () => {
    const hostile = [
      permalink("a.py", other),
      `https://github.com/example/demo/blob/main/a.py#L1-L2`,
      `https://evil.test/example/demo/blob/${sha}/a.py#L1-L2`,
      `https://github.com.evil/example/demo/blob/${sha}/a.py#L1-L2`,
      `https://user@github.com/example/demo/blob/${sha}/a.py#L1-L2`,
      `http://github.com/example/demo/blob/${sha}/a.py#L1-L2`,
      `https://github.com/example/demo/blob/${sha}/a.py?x=1#L1-L2`,
      `https://github.com/example/demo/blob/${sha}/../../evil/a.py#L1-L2`,
      `https://github.com/example/demo/blob/${sha}/a.py`,
      "javascript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
    ];
    mount(
      analysis({
        evidence: [permalink("ok.py"), ...hostile].map((url, index) => ({
          id: `e-${index}`,
          path: index === 0 ? "ok.py" : `bad_${index}.py`,
          start_line: 1,
          end_line: 2,
          permalink: url,
          excerpt: "x = 1",
          validation_status: "valid",
          redacted: false,
        })),
      }),
    );
    await screen.findByText("Verified static analysis");
    await userEvent.click(tab(/^Code evidence/));
    const anchors = panel().querySelectorAll("a[href]");
    expect(anchors).toHaveLength(1);
    expect(anchors[0]).toHaveAttribute("href", permalink("ok.py"));
    expect(anchors[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(anchors[0]).toHaveAttribute("target", "_blank");
    expect(within(panel()).getAllByText(/did not match the pinned commit/)).toHaveLength(hostile.length);
  });

  it("renders excerpts as text, marks redactions and discloses unvalidated records", async () => {
    const { container } = mount(analysis());
    await screen.findByText("Verified static analysis");
    await userEvent.click(tab(/^Code evidence/));
    expect(within(panel()).getByText("1 evidence record did not pass validation and is not shown.")).toBeVisible();
    expect(container.querySelector("img, script")).toBeNull();
    expect(container.querySelector("pre")?.textContent).toBe("import routes\n<img src=x onerror=alert(1)>");
    expect(within(panel()).getByText(/app\/routes\.py:1–2 · redacted/)).toBeVisible();
  });
});

describe("limitations and skipped files", () => {
  it("surfaces the test-fact budget, model weights, budgeted test files and skipped files", async () => {
    const { container } = mount(analysis());
    await screen.findByText("Verified static analysis");
    // The overview points at the disclosures.
    expect(within(panel()).getByText(/disclosures about omitted test facts or skipped model weights/)).toBeVisible();
    await userEvent.click(tab(/^Limitations/));
    expect(container.querySelector('[data-disclosure="test-fact-budget"]')).toHaveTextContent(
      "Test-fact budget: the repository exceeded the 10,000-fact analysis cap",
    );
    expect(within(panel()).getByText("Calls do not prove execution.")).toBeVisible();
    expect(within(panel()).getByText("No single entrypoint was selected.")).toBeVisible();
    expect(within(panel()).getByText("Two claims disagree about the router.")).toBeVisible();
    expect(within(panel()).getByRole("heading", { name: "Model weight files (1)" })).toBeVisible();
    expect(within(panel()).getAllByText("models/net.pt").length).toBeGreaterThan(0);
    expect(within(panel()).getByRole("heading", { name: "Test files with omitted facts (1)" })).toBeVisible();
    expect(within(panel()).getByText("Showing all 3 skipped or failed files.")).toBeVisible();
    expect(within(panel()).getByText("broken.py")).toBeVisible();
  });

  it("keeps limitations visible while a search filters skipped files", async () => {
    mount(analysis());
    await screen.findByText("Verified static analysis");
    await userEvent.type(screen.getByLabelText("Search this analysis"), "dist/");
    await userEvent.click(tab(/^Limitations/));
    expect(within(panel()).getByText("Calls do not prove execution.")).toBeVisible();
    expect(within(panel()).getByText("Showing all 1 skipped or failed files matching (3 in total).")).toBeVisible();
    expect(within(panel()).getByText("dist/bundle.js")).toBeVisible();
    expect(within(panel()).queryByText("broken.py")).toBeNull();
  });
});
