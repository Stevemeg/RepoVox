"use client";
import { useCallback, useContext, useEffect, useState } from "react";
import { WorkspaceContext } from "@/components/workspace/context";
import { linkAbort } from "@/lib/abort";
import { api, ApiError } from "@/lib/api";
import { toProblem, type Problem } from "@/lib/errors";
import { normalizeVideoStory, type VideoStoryView } from "@/lib/story-types";
import { storyPath } from "@/lib/video-media";

export type StoryState =
  /** Not requested: no story exists for this kind of video, or it has expired. */
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; view: VideoStoryView; issues: number }
  /** `404 story_not_available`: this video carries no story. Not an error. */
  | { status: "not-available" }
  /** `503 story_corrupt`: the stored story failed its integrity check. */
  | { status: "corrupt"; problem: Problem }
  /** A 200 response that is not shaped like a story. */
  | { status: "malformed" }
  | { status: "error"; problem: Problem };

type Settled = Exclude<StoryState, { status: "idle" } | { status: "loading" }>;

function classify(cause: unknown): Settled {
  if (cause instanceof ApiError && cause.status === 404 && cause.code === "story_not_available")
    return { status: "not-available" };
  if (cause instanceof ApiError && cause.code === "story_corrupt")
    return { status: "corrupt", problem: toProblem(cause, "video") };
  return { status: "error", problem: toProblem(cause, "video") };
}

/**
 * Lazily loads one video's story with `GET /video-jobs/{job}/videos/{video}/story` (a safe
 * request: no CSRF token and no content type), only while `enabled` and only for valid ids.
 * Switching videos or signing out aborts the request in flight. Each video's outcome is kept,
 * so switching back does not refetch; `retry` forgets it and loads again.
 */
export function useVideoStory(
  jobId: string,
  videoId: string | null,
  enabled: boolean,
): { state: StoryState; retry: () => void } {
  const workspace = useContext(WorkspaceContext);
  const handleUnauthorized = workspace?.handleUnauthorized;
  const sessionSignal = workspace?.sessionSignal;
  const [settled, setSettled] = useState<Record<string, Settled>>({});
  const path = enabled && videoId ? storyPath(jobId, videoId) : null;
  const known = path ? settled[path] : undefined;
  const needed = path !== null && known === undefined;

  useEffect(() => {
    if (!path || !needed) return;
    const controller = linkAbort(sessionSignal);
    if (controller.signal.aborted) return;
    const record = (result: Settled) => {
      if (!controller.signal.aborted) setSettled((previous) => ({ ...previous, [path]: result }));
    };
    api<unknown>(path, { signal: controller.signal })
      .then((raw) => {
        const normalized = normalizeVideoStory(raw);
        record(
          normalized
            ? { status: "loaded", view: normalized.view, issues: normalized.issues }
            : { status: "malformed" },
        );
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        if (handleUnauthorized?.(cause)) return;
        record(classify(cause));
      })
      .finally(controller.release);
    return () => controller.abort();
  }, [path, needed, handleUnauthorized, sessionSignal]);

  const retry = useCallback(() => {
    if (!path) return;
    setSettled((previous) => {
      const next = { ...previous };
      delete next[path];
      return next;
    });
  }, [path]);

  const state: StoryState = !path ? { status: "idle" } : (known ?? { status: "loading" });
  return { state, retry };
}
