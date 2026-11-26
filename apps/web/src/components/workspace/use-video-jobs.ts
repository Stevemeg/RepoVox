"use client";
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { Project, VideoJob } from "@/lib/api";
import { isUnauthorized, toProblem, type Problem } from "@/lib/errors";
import { isActiveState } from "@/lib/job-status";
import { isUuid } from "@/lib/security";
import { useVisibilityPolling } from "@/lib/use-visibility-polling";
import { fetchVideoJobs } from "@/lib/video-jobs";
import { WorkspaceContext } from "./context";

const REFRESH_MS = 5000;

export type VideoJobsFailure = { projectId: string; projectTitle: string; problem: Problem };

export type VideoJobsState = {
  /** False when this environment does not offer narrated videos: nothing is requested. */
  enabled: boolean;
  /** Every loaded video job across the given projects, newest first. */
  jobs: VideoJob[];
  /** False until the first load has finished. */
  settled: boolean;
  /** Projects whose video jobs could not be loaded on the latest attempt. */
  failures: VideoJobsFailure[];
  /** How many projects the latest attempt covered. */
  projectCount: number;
  /** Load again now (also used by "Try again"). */
  reload: () => Promise<void>;
};

type Loaded = { byProject: Record<string, VideoJob[]>; failed: { id: string; problem: Problem }[] };

/**
 * Video jobs for every given project, loaded through the per-project route with bounded
 * concurrency. Each load aborts the one before it, and unmounting aborts the last; a
 * project whose request fails keeps its last good list and is reported in `failures`, so a
 * single failure never empties the page. While any video job is active the list refreshes
 * every few seconds, only while the tab is visible. `refreshKey` reloads on change (pass
 * the workspace's job ids: every video job admits an analysis job, so a new video job
 * always changes them).
 */
export function useVideoJobs(
  projects: readonly Project[],
  enabled: boolean,
  refreshKey = "",
): VideoJobsState {
  const workspace = useContext(WorkspaceContext);
  const handleUnauthorized = workspace?.handleUnauthorized;
  // Keyed by the id set, not the array, so the shell's periodic refresh does not refetch.
  const ids = useMemo(
    () =>
      projects
        .map((project) => project.id)
        .filter(isUuid)
        .sort()
        .join(","),
    [projects],
  );
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (!enabled) return;
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    try {
      const results = await fetchVideoJobs(ids ? ids.split(",") : [], {
        signal: current.signal,
      });
      if (current.signal.aborted) return;
      const ended = results.find((result) => !result.ok && isUnauthorized(result.error));
      if (ended && !ended.ok && handleUnauthorized?.(ended.error)) return;
      setLoaded((previous) => {
        const byProject: Record<string, VideoJob[]> = {};
        const failed: Loaded["failed"] = [];
        for (const result of results) {
          if (result.ok) byProject[result.projectId] = result.jobs;
          else {
            failed.push({ id: result.projectId, problem: toProblem(result.error, "video") });
            const last = previous?.byProject[result.projectId];
            if (last) byProject[result.projectId] = last;
          }
        }
        return { byProject, failed };
      });
    } catch {
      // fetchVideoJobs rejects only when this load was aborted for a newer one.
    } finally {
      if (controller.current === current) controller.current = null;
    }
  }, [enabled, ids, handleUnauthorized]);

  useEffect(() => {
    void load();
    return () => controller.current?.abort();
  }, [load, refreshKey]);

  const titles = useMemo(
    () => new Map(projects.map((project) => [project.id, project.title])),
    [projects],
  );
  const jobs = useMemo(() => {
    if (!loaded) return [];
    const current = new Set(ids ? ids.split(",") : []);
    return Object.entries(loaded.byProject)
      .filter(([id]) => current.has(id))
      .flatMap(([, list]) => list)
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  }, [loaded, ids]);
  const failures = useMemo(
    () =>
      (loaded?.failed ?? [])
        .filter((failure) => titles.has(failure.id))
        .map((failure) => ({
          projectId: failure.id,
          projectTitle: titles.get(failure.id) || "Untitled project",
          problem: failure.problem,
        })),
    [loaded, titles],
  );
  const active = jobs.some((job) => isActiveState(job.state));
  useVisibilityPolling(load, REFRESH_MS, enabled && active);

  return {
    enabled,
    jobs,
    settled: !enabled || loaded !== null,
    failures,
    projectCount: ids ? ids.split(",").length : 0,
    reload: load,
  };
}
