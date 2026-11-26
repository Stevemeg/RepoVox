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
    // Frontend handoff section 3: narration provenance is conditional, and tests are read, not run.
    ["unconditional narration claim", /No AI model|no paid service/gi],
    ["claim that tests pass", /tests? (pass|passed|passing)\b/gi],
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

  it("builds media and story URLs only from id-validated route helpers", () => {
    // Every video, caption, download and story URL comes from lib/video-media.ts, which
    // checks both ids as UUIDs before they enter a path.
    const builders = sources.filter((file) => /\/videos\/\$\{/.test(file.text)).map((file) => file.path);
    expect(builders).toEqual(["lib/video-media.ts"]);
    const media = sources.find((file) => file.path === "lib/video-media.ts")!.text;
    expect(media.match(/if \(!isUuid\(jobId\) \|\| !isUuid\(videoId\)\) return null;/g)).toHaveLength(2);
  });

  it("loads caption tracks hidden and never with `default`", () => {
    const tracks = sources.flatMap((file) => [...file.text.matchAll(/<track[\s\S]*?\/>/g)].map((m) => m[0]));
    expect(tracks.length).toBeGreaterThan(0);
    for (const track of tracks) {
      expect(track).toContain("ref={loadCaptionsHidden}");
      expect(track).not.toMatch(/\bdefault\b/);
    }
  });

  it("has no inline style attributes", () => {
    expect(count(/style=\{\{/g)).toBe(0);
  });

  it("keeps every horizontal scroll container positioned, so hidden labels cannot widen the page", () => {
    // `.visually-hidden` is absolutely positioned. Inside a sideways-scrolling strip that is
    // not itself positioned, such spans escape the strip's clipping and widen the document
    // (the analysis tab strip measured 903px wide at a 375px viewport before this rule).
    const css = (name: string) => sources.find((file) => file.path === `styles/${name}`)!.text;
    const rules = (text: string) =>
      [...text.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^}]*)\}/g)].map((m) => ({
        selector: m[1].trim(),
        body: m[2],
      }));
    const hidden = rules(css("base.css")).find((rule) => rule.selector === ".visually-hidden");
    expect(hidden?.body).toMatch(/position:\s*absolute/);

    const tabs = rules(css("components.css")).find((rule) => rule.selector === ".tabs");
    expect(tabs?.body).toMatch(/overflow-x:\s*auto/);
    expect(tabs?.body).toMatch(/position:\s*relative/);

    const scrollers = ["base.css", "components.css", "layout.css"]
      .flatMap((name) => rules(css(name)))
      .filter((rule) => /overflow-x:\s*(auto|scroll)/.test(rule.body));
    expect(scrollers.length).toBeGreaterThan(0);
    for (const rule of scrollers)
      expect(rule.body, rule.selector).toMatch(/position:\s*(relative|absolute|fixed|sticky)/);
  });
});

/** Every block of a stylesheet with its full prelude path, e.g. ["@media (...)", ".a"]. */
type Block = { file: string; path: string[]; declarations: [string, string][] };
function blocks(file: string, text: string): Block[] {
  const found: Block[] = [];
  const open: { prelude: string; body: string }[] = [];
  let buffer = "";
  for (const char of text.replace(/\/\*[\s\S]*?\*\//g, "")) {
    if (char === "{") {
      open.push({ prelude: buffer.trim().replace(/\s+/g, " "), body: "" });
      buffer = "";
    } else if (char === "}") {
      const block = open.pop()!;
      block.body += buffer;
      buffer = "";
      found.push({
        file,
        path: [...open.map((outer) => outer.prelude), block.prelude],
        declarations: block.body
          .split(";")
          .map((line) => line.split(/:(.*)/s).map((part) => part.trim()))
          .filter(([property, value]) => property && value)
          .map(([property, value]) => [property, value.replace(/\s+/g, " ")]),
      });
    } else if (char === ";" && open.length) {
      open[open.length - 1].body += `${buffer};`;
      buffer = "";
    } else buffer += char;
  }
  return found;
}

describe("motion system", () => {
  const stylesheets = sources.filter((file) => file.path.startsWith("styles/"));
  const all = stylesheets.flatMap((file) => blocks(file.path, file.text));
  const reduced = "@media (prefers-reduced-motion: reduce)";
  const selectors = (block: Block) => block.path[block.path.length - 1].split(",").map((s) => s.trim());
  const value = (block: Block | undefined, property: string) =>
    block?.declarations.find(([name]) => name === property)?.[1];
  const rule = (selector: string, file?: string) =>
    all.filter(
      (block) =>
        (!file || block.file === file) &&
        !block.path[0].startsWith("@media") &&
        selectors(block).includes(selector),
    );
  const timed = all.filter((block) => block.path[0] !== reduced && block.file !== "styles/tokens.css");
  const timing = timed.flatMap((block) =>
    block.declarations
      .filter(([property]) => /^(transition|animation)(-duration|-delay)?$/.test(property))
      .map(([property, text]) => ({ where: `${block.file} ${block.path.join(" ")}`, property, text })),
  );

  it("collapses every animation and transition under prefers-reduced-motion", () => {
    const inside = (block: Block) => block.path[0] === reduced && block.path.length === 2;
    const base = all.filter((block) => block.file === "styles/base.css" && inside(block));
    expect(base).toHaveLength(1);
    const [block] = base;
    expect(selectors(block)).toEqual(["*", "*::before", "*::after"]);
    expect(Object.fromEntries(block.declarations)).toEqual({
      "animation-duration": "0.01ms !important",
      "animation-iteration-count": "1 !important",
      "animation-delay": "0ms !important",
      "transition-duration": "0.01ms !important",
      "transition-delay": "0ms !important",
      "scroll-behavior": "auto !important",
    });
    // Only time is removed: no other stylesheet overrides visibility, focus or state there.
    expect(all.filter(inside)).toHaveLength(1);
  });

  it("has animations and transitions for the reduced-motion block to collapse", () => {
    expect(timing.filter((entry) => entry.property === "animation").length).toBeGreaterThan(8);
    expect(timing.filter((entry) => entry.property === "transition").length).toBeGreaterThan(6);
  });

  it("times every transition and animation with motion tokens, never literal values", () => {
    expect(timing.length).toBeGreaterThan(0);
    for (const entry of timing) {
      expect(entry.text, entry.where).not.toMatch(/(^|[\s,(])-?\d*\.?\d+m?s\b/);
      // Keyword easings outside a var(--ease-*) name (which also contains "ease" and "linear").
      expect(entry.text, entry.where).not.toMatch(
        /(^|[\s,])(ease|ease-in|ease-out|ease-in-out|linear|step-start|step-end)(?=[\s,]|$)|cubic-bezier|steps\(/,
      );
      for (const part of entry.text.split(","))
        expect(part, entry.where).toMatch(/var\(--motion-[a-z-]+\).*var\(--ease-[a-z-]+\)/);
    }
  });

  it("defines every motion token in use and none of the retired names", () => {
    const tokens = sources.find((file) => file.path === "styles/tokens.css")!.text;
    const defined = new Set([...tokens.matchAll(/(--(?:motion|ease)-[a-z-]+):/g)].map((m) => m[1]));
    for (const name of ["--motion-fast", "--motion-base", "--motion-slow", "--ease-standard", "--ease-decelerate"])
      expect(defined, name).toContain(name);
    const used = new Set(
      stylesheets.flatMap((file) => [...file.text.matchAll(/var\((--(?:motion|ease)-[a-z-]+)\)/g)].map((m) => m[1])),
    );
    expect(used.size).toBeGreaterThan(5);
    for (const name of used) expect(defined, name).toContain(name);
    expect(count(/--duration-|--easing-/g)).toBe(0);
  });

  it("animates only with keyframes that exist, and leaves no keyframes unused", () => {
    const keyframes = new Set(
      all.filter((block) => block.path[0].startsWith("@keyframes")).map((block) => block.path[0].split(" ")[1]),
    );
    const named = new Set(
      timing.filter((entry) => entry.property === "animation").map((entry) => entry.text.split(" ")[0]),
    );
    expect([...named].sort()).toEqual([...keyframes].sort());
    // Keyframes animate only opacity and transform, so the compositor does the work.
    for (const block of all.filter((frame) => frame.path[0].startsWith("@keyframes")))
      for (const [property] of block.declarations)
        expect(["opacity", "transform"], `${block.path.join(" ")} ${property}`).toContain(property);
  });

  it("moves entrances vertically: translateX appears only in the clipped shimmer and the off-canvas drawer", () => {
    const horizontal = all.filter((block) => block.declarations.some(([, text]) => /translateX\(/.test(text)));
    const places = horizontal.map((block) => `${block.file} ${block.path.join(" ")}`).sort();
    expect(places).toEqual([
      "styles/base.css @keyframes rv-shimmer from",
      "styles/base.css @keyframes rv-shimmer to",
      "styles/components.css .skeleton::after",
      "styles/layout.css @media (max-width: 760px) .sidebar",
    ]);
    // The shimmer's host clips it, and the drawer only ever moves left of the viewport.
    const skeleton = rule(".skeleton", "styles/components.css")[0];
    expect(value(skeleton, "overflow")).toBe("hidden");
    expect(value(skeleton, "position")).toBe("relative");
    const drawer = horizontal.find((block) => block.path.includes(".sidebar"));
    expect(value(drawer, "transform")).toBe("translateX(-100%)");
    expect(value(drawer, "visibility")).toBe("hidden");
  });

  it.each([
    [".content > *", "rv-rise"],
    [".tab-panel:not([hidden])", "rv-rise"],
    [".studio-stage", "rv-rise"],
    [".dialog-backdrop", "rv-fade"],
    [".dialog", "rv-dialog-in"],
    [".flash-notice", "rv-rise"],
    [".problem", "rv-rise"],
    [".evidence[open] > :not(summary)", "rv-rise"],
    [".skeleton::after", "rv-shimmer"],
    ['.badge[data-tone="running"] .badge-dot::after', "rv-pulse"],
  ])("gives %s its %s entrance or loop", (selector, keyframes) => {
    const animated = rule(selector).find((block) => value(block, "animation"));
    expect(value(animated, "animation")?.split(" ")[0]).toBe(keyframes);
  });

  it("keeps the closed mobile drawer and its backdrop hidden, not just transparent", () => {
    const mobile = all.filter((block) => block.path[0] === "@media (max-width: 760px)");
    const backdrop = mobile.find((block) => selectors(block).includes(".nav-backdrop"));
    expect(value(backdrop, "visibility")).toBe("hidden");
    expect(value(backdrop, "opacity")).toBe("0");
    expect(value(backdrop, "position")).toBe("fixed");
    const open = mobile.find((block) => selectors(block).includes('.app-shell[data-nav-open="true"] .nav-backdrop'));
    expect(value(open, "visibility")).toBe("visible");
  });
});
