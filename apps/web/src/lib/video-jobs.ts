/*
 * Video jobs across every project, from the existing per-project route only
 * (`GET /projects/{id}/video-jobs`). There is no account-wide video-job listing, so this
 * fans out with bounded concurrency and reports each project's outcome separately: one
 * failing project never fails the whole load.
 */
import { api, ApiError } from "./api";
import { isUuid } from "./security";
import type { VideoJob } from "./types";

/** At most this many per-project requests are in flight at once. */
export const VIDEO_JOB_CONCURRENCY = 4;

export type ProjectVideoJobs =
  | { projectId: string; ok: true; jobs: VideoJob[] }
  | { projectId: string; ok: false; error: unknown };

const abortError = (signal: AbortSignal): unknown =>
  signal.reason ?? new DOMException("The operation was aborted.", "AbortError");

/**
 * Runs `task` over `items` with at most `limit` in flight, keeping input order. Stops taking
 * new items, and rejects, once `signal` aborts.
 */
export async function mapBounded<T, R>(
  items: readonly T[],
  limit: number,
  task: (item: T) => Promise<R>,
  signal?: AbortSignal,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      if (signal?.aborted) throw abortError(signal);
      const index = next++;
      results[index] = await task(items[index]);
    }
  }
  const workers = Math.min(Math.max(1, Math.floor(limit) || 1), items.length);
  await Promise.all(Array.from({ length: workers }, worker));
  if (signal?.aborted) throw abortError(signal);
  return results;
}

/**
 * Each project's video jobs, in the order given. Malformed ids never reach a URL. A project
 * that is no longer available (404: deleted, or deleted while loading) has no reachable
 * video jobs and is reported as an empty list, matching the job listing, which also omits
 * deleted projects. Any other error is that project's failure. Rejects only on abort.
 */
export async function fetchVideoJobs(
  projectIds: readonly string[],
  {
    signal,
    concurrency = VIDEO_JOB_CONCURRENCY,
  }: { signal?: AbortSignal; concurrency?: number } = {},
): Promise<ProjectVideoJobs[]> {
  return mapBounded(
    projectIds.filter(isUuid),
    concurrency,
    async (projectId): Promise<ProjectVideoJobs> => {
      try {
        const jobs = await api<VideoJob[]>(`/projects/${projectId}/video-jobs`, { signal });
        return { projectId, ok: true, jobs: Array.isArray(jobs) ? jobs : [] };
      } catch (error) {
        if (signal?.aborted) throw abortError(signal);
        if (error instanceof ApiError && error.status === 404 && error.code === "not_found")
          return { projectId, ok: true, jobs: [] };
        return { projectId, ok: false, error };
      }
    },
    signal,
  );
}
