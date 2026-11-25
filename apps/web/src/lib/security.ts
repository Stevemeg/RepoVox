/*
 * Client-side defence in depth for every URL that reaches an `href` or `src`.
 *
 * The API already canonicalises repository locators and builds citation permalinks, but
 * the browser re-checks them: repository strings are untrusted data, so a URL is used only
 * after it has been validated here, and only through the branded `SafeUrl` type that
 * `<ExternalLink>` requires.
 */

declare const safeUrl: unique symbol;
/** A URL that passed one of the validators below. Only they can produce one. */
export type SafeUrl = string & { readonly [safeUrl]: true };

const GITHUB = "https://github.com/";
// GitHub's own rules, matching the API's `repository_url()`: owner 1-39 characters of
// letters, digits and single inner hyphens; name 1-100 of letters, digits, `_`, `.`, `-`.
const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const NAME = /^[A-Za-z0-9_.-]{1,100}$/;
const PRINTABLE_ASCII = /^[\x21-\x7e]+$/;
const SHA = /^[a-f0-9]{40}$/;
const LINE_RANGE = /^#L[1-9][0-9]*-L[1-9][0-9]*$/;

function parse(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function plainGitHubOrigin(value: string, url: URL): boolean {
  return (
    value.startsWith(GITHUB) &&
    url.protocol === "https:" &&
    url.hostname === "github.com" &&
    url.port === "" &&
    url.username === "" &&
    url.password === "" &&
    url.search === "" &&
    !value.includes("?") &&
    !value.includes("\\")
  );
}

/**
 * The canonical `https://github.com/<owner>/<repo>` form of a repository locator, or null.
 * Rejects every other scheme (`javascript:`, `data:`, `http:`), host, port, credential,
 * query, fragment, extra path segment, percent-encoding and dot segment. The raw string is
 * parsed, not the WHATWG-normalised path, so `/x/../evil/repo` cannot pass.
 */
export function safeGitHubRepoUrl(value: unknown): SafeUrl | null {
  if (typeof value !== "string" || value.length > 250 || !PRINTABLE_ASCII.test(value))
    return null;
  const url = parse(value);
  if (!url || !plainGitHubOrigin(value, url) || url.hash !== "" || value.includes("#"))
    return null;
  const match = /^\/([^/]+)\/([^/]+)\/?$/.exec(value.slice(GITHUB.length - 1));
  if (!match) return null;
  const owner = match[1];
  const name = match[2].endsWith(".git") ? match[2].slice(0, -4) : match[2];
  if (!OWNER.test(owner) || !NAME.test(name) || name === "." || name === "..")
    return null;
  return `${GITHUB}${owner}/${name}` as SafeUrl;
}

/**
 * A pinned GitHub source citation (`https://github.com/<owner>/<repo>/blob/<40-hex>/<path>
 * #L<a>-L<b>`), or null. When `commitSha` is given the permalink must cite exactly that
 * commit, so a citation can never point at a moving branch or another snapshot.
 */
export function safePermalink(value: unknown, commitSha?: string): SafeUrl | null {
  if (typeof value !== "string" || value.length > 1000 || !PRINTABLE_ASCII.test(value))
    return null;
  if (commitSha !== undefined && !SHA.test(commitSha)) return null;
  const url = parse(value);
  if (!url || !plainGitHubOrigin(value, url) || !LINE_RANGE.test(url.hash)) return null;
  const path = value.slice(GITHUB.length - 1, value.indexOf("#"));
  const match = /^\/([^/]+)\/([^/]+)\/blob\/([a-f0-9]{40})\/(.+)$/.exec(path);
  if (!match || !OWNER.test(match[1]) || !NAME.test(match[2])) return null;
  if (path.split("/").some((segment) => segment === "." || segment === ".."))
    return null;
  if (commitSha !== undefined && match[3] !== commitSha) return null;
  return url.href as SafeUrl;
}

/** The lowercase-UUID form every RepoVox id takes; ids are checked before entering a URL. */
export const UUID =
  /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
export const isUuid = (value: unknown): value is string =>
  typeof value === "string" && UUID.test(value);
