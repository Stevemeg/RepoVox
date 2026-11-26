"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { VideoJob } from "@/lib/types";
import { lifecycle, sortVideos } from "@/lib/video-media";
import { NarrationPanel } from "./narration-panel";
import { StoryExplorer } from "./story-explorer";
import { useNow } from "./use-now";
import { useVideoStory } from "./use-video-story";
import { VideoPlaylist } from "./video-playlist";
import { VideoStage } from "./video-stage";

/** The expiry countdown refreshes this often; it makes no request. */
const CLOCK_MS = 30_000;

/**
 * A succeeded video job's published videos: one active stage, a playlist in `position`
 * order, the active video's narration provenance and its problem-to-solution story. Only the
 * walkthrough carries a story (`/story` is walkthrough-only in the contract), so the story is
 * requested only for an unexpired walkthrough, and only when it is on the stage.
 */
export function VideoStudio({ job }: { job: VideoJob }) {
  const videos = useMemo(() => sortVideos(job.videos), [job.videos]);
  const [selected, setSelected] = useState<string | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const moveFocus = useRef(false);
  const active = videos.find((video) => video.id === selected) ?? videos[0];
  const now = useNow(CLOCK_MS, videos.length > 0);
  const expired = active ? lifecycle(active, now).expired : true;
  const story = useVideoStory(
    job.id,
    active?.id ?? null,
    !!active && active.category === "walkthrough" && !expired,
  );

  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    stage.current?.scrollIntoView?.({ block: "start" });
    stage.current?.focus({ preventScroll: true });
  }, [active?.id]);

  if (!active) return null;
  const walkthrough =
    videos.find((video) => video.category === "walkthrough" && !lifecycle(video, now).expired) ??
    null;

  return (
    <div className="studio" data-job={job.id}>
      <div className="studio-main">
        <VideoStage ref={stage} key={active.id} jobId={job.id} video={active} now={now} />
        {videos.length > 1 && (
          <VideoPlaylist
            videos={videos}
            activeId={active.id}
            now={now}
            onSelect={(id) => setSelected(id)}
          />
        )}
      </div>
      <NarrationPanel
        video={active}
        storyNarration={story.state.status === "loaded" ? story.state.view.narration : null}
      />
      <StoryExplorer
        key={active.id}
        video={active}
        state={story.state}
        expired={expired}
        walkthrough={walkthrough}
        onRetry={story.retry}
        onShowWalkthrough={(id) => {
          moveFocus.current = true;
          setSelected(id);
        }}
      />
    </div>
  );
}
