"use client";
import { useId } from "react";
import type { Video } from "@/lib/types";
import { formatBytes, formatDuration, lifecycle, videoDuration } from "@/lib/video-media";
import { CategoryBadge } from "./video-stage";

/**
 * The job's videos in `position` order. Each entry is a toggle button: the one on the stage
 * is `aria-pressed="true"`. Choosing an entry never starts playback by itself.
 */
export function VideoPlaylist({
  videos,
  activeId,
  now,
  onSelect,
}: {
  videos: Video[];
  activeId: string;
  now: number;
  onSelect: (id: string) => void;
}) {
  const titleId = useId();
  return (
    <div className="studio-playlist">
      <h4 id={titleId}>
        Videos in this job <span className="panel-count">{videos.length}</span>
      </h4>
      <ol className="playlist" aria-labelledby={titleId}>
        {videos.map((video, index) => {
          const active = video.id === activeId;
          const expired = lifecycle(video, now).expired;
          const duration = formatDuration(videoDuration(video));
          return (
            <li key={video.id}>
              <button
                type="button"
                className="playlist-item"
                aria-pressed={active}
                data-video-id={video.id}
                data-category={video.category}
                onClick={() => onSelect(video.id)}
              >
                <span className="playlist-index" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="playlist-body">
                  <CategoryBadge category={video.category} />
                  <span className="playlist-title">{video.title}</span>
                  <span className="playlist-meta">
                    {[duration, formatBytes(video.byte_count), expired ? "Expired" : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                {active && <span className="playlist-now">Now showing</span>}
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
