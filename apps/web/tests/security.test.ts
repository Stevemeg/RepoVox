import { describe, expect, it } from "vitest";
import { isUuid, safeGitHubRepoUrl, safePermalink } from "../src/lib/security";

const sha = "a".repeat(40);

describe("safeGitHubRepoUrl", () => {
  it.each([
    ["https://github.com/owner/repo", "https://github.com/owner/repo"],
    ["https://github.com/owner/repo/", "https://github.com/owner/repo"],
    ["https://github.com/owner/repo.git", "https://github.com/owner/repo"],
    ["https://github.com/my-org/my_repo.v2", "https://github.com/my-org/my_repo.v2"],
    ["https://github.com/a/b", "https://github.com/a/b"],
  ])("accepts the canonical locator %s", (input, canonical) => {
    expect(safeGitHubRepoUrl(input)).toBe(canonical);
  });

  it.each([
    ["javascript:", "javascript:alert(1)"],
    ["javascript: disguised", "javascript://github.com/owner/repo"],
    ["data:", "data:text/html,<script>alert(1)</script>"],
    ["http:", "http://github.com/owner/repo"],
    ["protocol-relative", "//github.com/owner/repo"],
    ["embedded credentials", "https://user:pass@github.com/owner/repo"],
    ["embedded user", "https://user@github.com/owner/repo"],
    ["port", "https://github.com:443/owner/repo"],
    ["query", "https://github.com/owner/repo?tab=readme"],
    ["empty query", "https://github.com/owner/repo?"],
    ["fragment", "https://github.com/owner/repo#readme"],
    ["lookalike host", "https://github.com.evil.test/owner/repo"],
    ["subdomain", "https://gist.github.com/owner/repo"],
    ["other host", "https://gitlab.com/owner/repo"],
    ["uppercase host", "https://GitHub.com/owner/repo"],
    ["extra path", "https://github.com/owner/repo/tree/main"],
    ["owner only", "https://github.com/owner"],
    ["dot segment", "https://github.com/x/../owner/repo"],
    ["dot name", "https://github.com/owner/.."],
    ["percent-encoding", "https://github.com/owner/re%2fpo"],
    ["backslash", "https://github.com\\owner/repo"],
    ["whitespace", " https://github.com/owner/repo"],
    ["leading hyphen owner", "https://github.com/-owner/repo"],
    ["double hyphen owner", "https://github.com/ow--ner/repo"],
    ["non-ASCII", "https://github.com/ownér/repo"],
    ["over length", `https://github.com/owner/${"r".repeat(240)}`],
    ["empty", ""],
  ])("rejects %s", (_, input) => {
    expect(safeGitHubRepoUrl(input)).toBeNull();
  });

  it("rejects non-strings", () => {
    for (const value of [null, undefined, 42, {}, ["https://github.com/a/b"]])
      expect(safeGitHubRepoUrl(value)).toBeNull();
  });
});

describe("safePermalink", () => {
  const valid = `https://github.com/owner/repo/blob/${sha}/src/app.py#L1-L2`;

  it("accepts a pinned line-range citation and binds it to the commit", () => {
    expect(safePermalink(valid)).toBe(valid);
    expect(safePermalink(valid, sha)).toBe(valid);
    expect(
      safePermalink(`https://github.com/o/r/blob/${sha}/docs/a%20b.md#L3-L3`, sha),
    ).toBe(`https://github.com/o/r/blob/${sha}/docs/a%20b.md#L3-L3`);
  });

  it.each([
    ["javascript:", "javascript:alert(1)"],
    ["http:", valid.replace("https:", "http:")],
    ["credentials", valid.replace("https://", "https://user@")],
    ["lookalike host", `https://github.com.evil/owner/repo/blob/${sha}/x#L1-L2`],
    ["port", valid.replace("github.com", "github.com:8443")],
    ["query", `https://github.com/owner/repo/blob/${sha}/x?raw=1#L1-L2`],
    ["branch instead of commit", "https://github.com/o/r/blob/main/x#L1-L2"],
    ["short sha", "https://github.com/o/r/blob/abc123/x#L1-L2"],
    ["no line range", `https://github.com/o/r/blob/${sha}/x`],
    ["single line anchor", `https://github.com/o/r/blob/${sha}/x#L1`],
    ["zero line", `https://github.com/o/r/blob/${sha}/x#L0-L2`],
    ["extra fragment", `https://github.com/o/r/blob/${sha}/x#L1-L2#evil`],
    ["dot segment", `https://github.com/o/r/blob/${sha}/../../x#L1-L2`],
    ["raw host", `https://raw.githubusercontent.com/o/r/${sha}/x#L1-L2`],
  ])("rejects %s", (_, input) => {
    expect(safePermalink(input, sha)).toBeNull();
  });

  it("rejects a citation of a different commit, and a malformed expected commit", () => {
    expect(safePermalink(valid, "b".repeat(40))).toBeNull();
    expect(safePermalink(valid, "main")).toBeNull();
  });
});

describe("isUuid", () => {
  it("accepts lowercase UUIDs only", () => {
    expect(isUuid("11111111-1111-4111-8111-111111111111")).toBe(true);
    for (const value of [
      "11111111-1111-4111-8111-11111111111",
      "11111111-1111-4111-8111-111111111111/../x",
      "11111111-1111-4111-8111-11111111111G",
      "",
      null,
    ])
      expect(isUuid(value)).toBe(false);
  });
});
