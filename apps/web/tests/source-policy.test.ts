// @vitest-environment node
// Static guard over the shipped source, complementing the ESLint rules: these patterns
// must never appear in apps/web/src.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = fileURLToPath(new URL("../src", import.meta.url));
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.(tsx?|css)$/.test(name) ? [path] : [];
  });
}
const sources = files(root).map((path) => ({
  path: relative(root, path).replaceAll("\\", "/"),
  text: readFileSync(path, "utf-8"),
}));
const count = (pattern: RegExp) =>
  sources.reduce((total, file) => total + (file.text.match(pattern)?.length ?? 0), 0);

describe("shipped web source", () => {
  it("contains the expected files", () => {
    expect(sources.length).toBeGreaterThan(20);
  });

  it.each([
    ["dangerouslySetInnerHTML", /dangerouslySetInnerHTML/g],
    ["innerHTML", /\.(inner|outer)HTML\b/g],
    ["eval", /\beval\s*\(/g],
    ["new Function", /new\s+Function\s*\(/g],
    ["window.confirm", /window\.confirm/g],
    ["window.open", /window\.open/g],
    ["NEXT_PUBLIC_", /NEXT_PUBLIC_/g],
    ["external font or remote asset", /@import\s+url\(|fonts\.googleapis|https?:\/\/[^"')\s]*\.(woff2?|ttf|otf|css)/g],
    ["stale phase copy", /later phase|Phase [12]\b|remains unavailable|arrives in a later/gi],
    ["raw status code as a message", /Status code:/g],
  ])("has no %s", (_, pattern) => {
    expect(count(pattern)).toBe(0);
  });

  it('sets target="_blank" only in ExternalLink, always with rel="noopener noreferrer"', () => {
    const withTarget = sources.filter((file) => /target=/.test(file.text));
    expect(withTarget.map((file) => file.path)).toEqual(["components/ui/external-link.tsx"]);
    const anchor = withTarget[0].text.match(/<a [^>]*>/)?.[0] ?? "";
    expect(anchor).toContain('target="_blank"');
    expect(anchor).toContain('rel="noopener noreferrer"');
  });

  it("never puts an unvalidated repository URL or permalink in an href", () => {
    expect(count(/href=\{[^}]*(repository_url|\.permalink)[^}]*\}/g)).toBe(0);
  });

  it("has no inline style attributes", () => {
    expect(count(/style=\{\{/g)).toBe(0);
  });
});
