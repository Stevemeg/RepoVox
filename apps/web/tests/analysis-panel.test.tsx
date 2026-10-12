import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AnalysisPanel, safePermalink } from "../src/components/analysis-panel";

const sha = "a".repeat(40);
beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

it("permits pinned GitHub citations and rejects executable or redirected links", () => {
  expect(
    safePermalink(`https://github.com/owner/repo/blob/${sha}/a.py#L1-L2`, sha),
  ).toBe(true);
  for (const url of [
    "javascript:alert(1)",
    `https://github.com.evil/blob/${sha}/x#L1-L2`,
    `https://user@github.com/repo/blob/${sha}/x#L1-L2`,
    `https://github.com/o/r/blob/main/x#L1-L2`,
  ])
    expect(safePermalink(url, sha)).toBe(false);
});

it("labels uncertainty and escapes source excerpts", async () => {
  const body = {
    commit_sha: sha,
    payload: {
      knowledge: {
        repository: { canonical_url: "https://github.com/example/demo" },
        stack: ["python"],
        modules: ["app.py"],
        entrypoints: {
          candidates: [],
          uncertainty: ["No reliable entrypoint."],
        },
        edges: [],
        claims: [
          {
            id: "claim-1",
            text: "Observed import only",
            status: "inferred",
            reason: "Execution unknown",
          },
        ],
        coverage: {
          coverage: 1,
          parsed_bytes: 30,
          eligible_bytes: 30,
          files: [],
        },
        limitations: ["Static syntax only"],
      },
      evidence: {
        items: [
          {
            id: "e-1",
            path: "app.py",
            start_line: 1,
            end_line: 1,
            permalink: `https://github.com/example/demo/blob/${sha}/app.py#L1-L1`,
            excerpt: "<script>evil()</script>",
            validation_status: "valid",
            redacted: false,
          },
        ],
      },
      verification: {
        counts: {
          verified: 1,
          inferred: 1,
          documentation_only: 0,
          unsupported: 0,
        },
        conflicts: [],
      },
    },
  };
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify(body), { status: 200 }),
  );
  const { container } = render(<AnalysisPanel jobId="job-1" />);
  expect(await screen.findByText("Verified static analysis")).toBeVisible();
  expect(screen.getByText("inferred", { exact: true })).toBeVisible();
  expect(container.querySelector("pre")?.textContent).toBe(
    "<script>evil()</script>",
  );
  expect(container.querySelector("script")).toBeNull();
  expect(
    screen.getByRole("link", { name: "Pinned source permalink" }),
  ).toHaveAttribute("rel", "noreferrer");
});
