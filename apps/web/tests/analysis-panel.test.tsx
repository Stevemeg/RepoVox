import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { AnalysisPanel } from "../src/components/analysis-panel";
import { safePermalink } from "../src/lib/security";

const sha = "a".repeat(40);
beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

it("permits pinned GitHub citations and rejects executable or redirected links", () => {
  const pinned = `https://github.com/owner/repo/blob/${sha}/a.py#L1-L2`;
  expect(safePermalink(pinned, sha)).toBe(pinned);
  for (const url of [
    "javascript:alert(1)",
    `https://github.com.evil/blob/${sha}/x#L1-L2`,
    `https://user@github.com/repo/blob/${sha}/x#L1-L2`,
    `https://github.com/o/r/blob/main/x#L1-L2`,
  ])
    expect(safePermalink(url, sha)).toBeNull();
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
  await userEvent.click(screen.getByRole("tab", { name: /^Claims/ }));
  expect(screen.getByText("inferred", { exact: true })).toBeVisible();
  await userEvent.click(screen.getByRole("tab", { name: /^Code evidence/ }));
  expect(container.querySelector("pre")?.textContent).toBe(
    "<script>evil()</script>",
  );
  expect(container.querySelector("script")).toBeNull();
  const link = screen.getByRole("link", { name: /^Pinned source permalink/ });
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
  expect(link).toHaveAttribute(
    "href",
    `https://github.com/example/demo/blob/${sha}/app.py#L1-L1`,
  );
});

it("drops a citation whose permalink points at another commit or host", async () => {
  const other = "b".repeat(40);
  const body = {
    commit_sha: sha,
    payload: {
      knowledge: {
        repository: { canonical_url: "https://github.com/example/demo" },
        stack: [],
        modules: [],
        entrypoints: { candidates: [], uncertainty: [] },
        edges: [],
        claims: [],
        coverage: { coverage: 0, parsed_bytes: 0, eligible_bytes: 0, files: [] },
        limitations: [],
      },
      evidence: {
        items: [
          `https://github.com/example/demo/blob/${other}/a.py#L1-L1`,
          `https://evil.test/example/demo/blob/${sha}/a.py#L1-L1`,
          "javascript:alert(1)",
        ].map((permalink, i) => ({
          id: `e-${i}`,
          path: "a.py",
          start_line: 1,
          end_line: 1,
          permalink,
          excerpt: "x = 1",
          validation_status: "valid",
          redacted: false,
        })),
      },
      verification: { counts: {}, conflicts: [] },
    },
  };
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
  const { container } = render(<AnalysisPanel jobId="job-2" />);
  expect(await screen.findByText("Verified static analysis")).toBeVisible();
  await userEvent.click(screen.getByRole("tab", { name: /^Code evidence/ }));
  expect(container.querySelectorAll("details.evidence")).toHaveLength(3);
  expect(container.querySelectorAll("a[href]")).toHaveLength(0);
});
