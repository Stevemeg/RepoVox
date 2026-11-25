/** Display helpers. Rendered only after data loads on the client, so no hydration drift. */

export function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unknown date"
    : date.toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" });
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unknown time"
    : date.toLocaleString("en", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

export function initials(name: string): string {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  return letters || "?";
}

export const shortId = (id: string) => id.slice(0, 8);

export const humanize = (value: string) => value.replaceAll("_", " ");

export const ACTIVE_JOB_STATES = ["queued", "running", "retry_wait"];
export const TERMINAL_VIDEO_STATES = ["succeeded", "failed", "cancelled"];
