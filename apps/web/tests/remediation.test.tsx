import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RemediationPanel } from "../src/components/ui/remediation-panel";
import { REMEDIATION_CODES, remediationFor } from "../src/lib/remediation";

const REQUIRED = [
  // Source safety
  "secret_detected",
  "archive_nested",
  "archive_download_limit",
  "archive_expansion_limit",
  "archive_member_limit",
  "archive_unsafe_entry",
  "archive_unsafe_path",
  // Size limits
  "analysis_fact_limit",
  "eligible_source_limit",
  // Repository resolution
  "repository_private",
  "repository_not_found",
  "source_changed",
  // Quotas and rate limits
  "monthly_quota",
  "queue_quota",
  "project_quota",
  "admission_rate",
  "github_rate_limited",
  // Media and evidence
  "media_timeout",
  "insufficient_evidence",
];

const allText = (code: string, context: "job" | "request" = "job") => {
  const guidance = remediationFor(code, context)!;
  return [
    guidance.title,
    guidance.explanation,
    guidance.withheld ?? "",
    guidance.retry ?? "",
    ...guidance.steps,
    guidance.policy?.heading ?? "",
    ...(guidance.policy?.items ?? []),
  ].join("\n");
};

describe("remediation guidance", () => {
  it.each(REQUIRED)("has actionable guidance for %s", (code) => {
    const guidance = remediationFor(code);
    expect(guidance).not.toBeNull();
    expect(guidance!.code).toBe(code);
    expect(guidance!.title.length).toBeGreaterThan(5);
    expect(guidance!.explanation.length).toBeGreaterThan(20);
    expect(guidance!.steps.length).toBeGreaterThan(0);
  });

  it("covers exactly the documented codes plus extraction limits", () => {
    expect([...REMEDIATION_CODES].sort()).toEqual([...REQUIRED, "archive_extraction_limit"].sort());
  });

  it("never fabricates a repository file path, line number or count", () => {
    for (const code of REMEDIATION_CODES)
      for (const context of ["job", "request"] as const) {
        const text = allText(code, context);
        // A directory/file path such as src/config.py or app/settings/base.ts.
        expect(text, code).not.toMatch(/\b[\w-]+\/[\w./-]*\.[a-z]{1,5}\b/i);
        expect(text, code).not.toMatch(/\bline \d+|:\d+[-–]\d+\b|\bL\d+\b/i);
        expect(text, code).not.toMatch(/\b\d+ (files?|lines?|matches) (were|was) found\b/i);
      }
  });

  it("explains that secret_detected withholds the location on purpose", () => {
    const guidance = remediationFor("secret_detected")!;
    expect(guidance.withheld).toMatch(/does not show which file, line or value matched/);
    const policy = guidance.policy!.items.join(" ");
    for (const pattern of ["PRIVATE KEY", "AKIA", "github_pat_", "sk_live_", "password", "24 or more"])
      expect(policy).toContain(pattern);
    expect(guidance.steps.join(" ")).toMatch(/revoke or rotate/);
    expect(guidance.retry).toMatch(/same pinned commit/);
  });

  it("separates skipped model weights from refused archives", () => {
    const items = remediationFor("archive_nested")!.policy!.items.join(" ");
    for (const refused of [".zip", ".tar", ".jar", ".whl", ".docx"]) expect(items).toContain(refused);
    expect(items).toMatch(/Skipped, not refused: PyTorch \.pt and \.pth and Keras \.keras/);
  });

  it("states real limits, and what an admission refusal did not use", () => {
    expect(allText("archive_download_limit")).toContain("100 MB");
    expect(allText("analysis_fact_limit")).toContain("10,000 facts");
    expect(allText("eligible_source_limit")).toMatch(/5,000 eligible source files and 100 MB/);
    expect(allText("project_quota")).toMatch(/100 projects/);
    expect(remediationFor("monthly_quota", "request")!.retry).toMatch(/no allowance was used/);
    expect(remediationFor("monthly_quota", "job")!.retry).toBeUndefined();
  });

  it("returns nothing for unknown, empty and prototype codes", () => {
    for (const code of ["", null, undefined, "unknown_code", "constructor", "__proto__", "toString"])
      expect(remediationFor(code)).toBeNull();
  });
});

describe("RemediationPanel", () => {
  it("renders guidance as an accessible section of plain text", () => {
    const { container } = render(<RemediationPanel code="secret_detected" />);
    const panel = screen.getByRole("region", { name: "The credential screen refused this snapshot" });
    expect(within(panel).getByText(/Not shown on purpose/)).toBeVisible();
    expect(within(panel).getByRole("heading", { name: "What you can do" })).toBeVisible();
    expect(within(panel).getAllByRole("listitem").length).toBeGreaterThan(5);
    expect(container.querySelector("a[href], script")).toBeNull();
  });

  it("omits the explanation when compact, and renders nothing without guidance", () => {
    const { rerender, container } = render(
      <RemediationPanel code="monthly_quota" context="request" compact />,
    );
    expect(screen.getByText("Monthly analysis allowance used")).toBeVisible();
    expect(screen.queryByText(/counts against this account's monthly allowance/)).toBeNull();
    expect(screen.getByText(/no allowance was used/)).toBeVisible();
    rerender(<RemediationPanel code="phase2_pipeline_boundary" />);
    expect(container).toBeEmptyDOMElement();
  });
});
