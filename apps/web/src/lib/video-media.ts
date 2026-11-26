/*
 * Published-video helpers for the Video Studio: same-origin media routes, playlist order,
 * the 24-hour lifecycle and display formatting. Pure functions, so every rule is testable.
 */
import { API_BASE } from "./api";
import { isUuid } from "./security";
import type { Video } from "./types";

/** Same-origin, owner-authorized routes only. Both ids are validated before entering a URL. */
export function videoRoutes(jobId: string, videoId: string) {
  if (!isUuid(jobId) || !isUuid(videoId)) return null;
  const base = `${API_BASE}/video-jobs/${jobId}/videos/${videoId}`;
  return {
    video: base,
    captions: `${base}/captions`,
    download: `${base}/download`,
    story: `${base}/story`,
  };
}

/** The `api()` path (relative to `/api/v1`) of a video's story, or null for invalid ids. */
export function storyPath(jobId: string, videoId: string): string | null {
  if (!isUuid(jobId) || !isUuid(videoId)) return null;
  return `/video-jobs/${jobId}/videos/${videoId}/story`;
}

/** Playlist order: the job's own `position`, then id, so the order never depends on input. */
export function sortVideos(videos: readonly Video[]): Video[] {
  return [...videos].sort(
    (a, b) =>
      (Number.isFinite(a.position) ? a.position : Number.MAX_SAFE_INTEGER) -
        (Number.isFinite(b.position) ? b.position : Number.MAX_SAFE_INTEGER) ||
      (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
  );
}

export type Lifecycle = {
  /** True once `expires_at` has passed, or when it cannot be read. */
  expired: boolean;
  /** Milliseconds left, or 0 when expired. */
  remaining: number;
};

/**
 * Where a video is in its 24-hour lifecycle. An unreadable expiry is treated as expired: the
 * page never offers a player it cannot vouch for.
 */
export function lifecycle(video: Pick<Video, "expires_at">, now: number): Lifecycle {
  const expires = Date.parse(video.expires_at);
  if (Number.isNaN(expires) || expires <= now) return { expired: true, remaining: 0 };
  return { expired: false, remaining: expires - now };
}

/** "12 h 31 min", "45 min", "less than a minute". */
export function formatRemaining(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "less than a minute";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

/** An exact local timestamp with seconds and time zone, or "Unknown time". */
export function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unknown time"
    : date.toLocaleString("en", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZoneName: "short",
      });
}

/** Decimal (SI) sizes: "8.4 MB", "512 kB", "999 bytes". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "Unknown size";
  if (bytes < 1000) return `${Math.round(bytes)} ${bytes === 1 ? "byte" : "bytes"}`;
  if (bytes < 1_000_000) return `${(bytes / 1000).toFixed(bytes < 10_000 ? 1 : 0)} kB`;
  if (bytes < 1_000_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${(bytes / 1_000_000_000).toFixed(2)} GB`;
}

/** "1 min 32 s", "45 s", or null when no duration was recorded. */
export function formatDuration(seconds: unknown): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return null;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes === 0) return `${rest} s`;
  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** The recorded duration: walkthroughs carry it directly, explainers under `media`. */
export const videoDuration = (video: Video): number | undefined =>
  video.metadata?.duration_seconds ?? video.metadata?.media?.duration_seconds;

export const CATEGORY_LABELS: Record<string, string> = {
  walkthrough: "Walkthrough",
  architecture: "Architecture",
};

export const categoryLabel = (category: string): string =>
  CATEGORY_LABELS[category] ?? "Video";

/** The longer description used next to a player. */
export const categoryDescription = (category: string): string =>
  category === "walkthrough"
    ? "Repository walkthrough"
    : category === "architecture"
      ? "Architecture explainer"
      : "Narrated video";
