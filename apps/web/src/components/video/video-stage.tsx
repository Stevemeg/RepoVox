"use client";
import { useState, type Ref } from "react";
import { Clock, Download } from "lucide-react";
import type { Video } from "@/lib/types";
import {
  categoryDescription,
  categoryLabel,
  formatBytes,
  formatDuration,
  formatRemaining,
  formatTimestamp,
  lifecycle,
  videoDuration,
  videoRoutes,
} from "@/lib/video-media";

/*
 * The active video: an accessible native player, its 24-hour lifecycle and a same-origin
 * download. An expired video gets a clear expired state, never a broken player.
 */

// Every frame already shows its caption in the lower band, so the WebVTT track is loaded
// hidden: its cues are available to the page and to the player's captions menu, but the
// browser does not draw a second caption box over the burned-in one. Without `default` a
// track starts disabled and is never fetched; "hidden" fetches it without drawing it.
// The callback is module-level, so its identity is stable and React calls it only when
// the track mounts: a re-render does not undo a viewer's own captions choice.
function loadCaptionsHidden(element: HTMLTrackElement | null) {
  if (element?.track) element.track.mode = "hidden";
}

export function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="category-badge" data-category={category}>
      {categoryLabel(category)}
    </span>
  );
}

function Timestamp({ value }: { value: string }) {
  return <time dateTime={value}>{formatTimestamp(value)}</time>;
}

/** Published and expiry times, size and checksum of one video. */
function VideoFacts({ video, now }: { video: Video; now: number }) {
  const life = lifecycle(video, now);
  return (
    <dl className="definition-list studio-facts">
      <dt>Published</dt>
      <dd data-published-at={video.published_at}>
        <Timestamp value={video.published_at} />
      </dd>
      <dt>Expires</dt>
      <dd data-expires-at={video.expires_at}>
        <Timestamp value={video.expires_at} />{" "}
        {life.expired ? (
          <span className="expiry" data-expired="true">
            · Expired
          </span>
        ) : (
          <span className="expiry" data-expired="false">
            · in {formatRemaining(life.remaining)}
          </span>
        )}
      </dd>
      <dt>Size</dt>
      <dd>{formatBytes(video.byte_count)}</dd>
      <dt>SHA-256</dt>
      <dd>
        <code className="sha">{video.checksum}</code>
      </dd>
    </dl>
  );
}

/**
 * One video on the stage. Give it `key={video.id}`: a new video mounts a new player, so its
 * source loads and its caption track is set to hidden on mount.
 */
export function VideoStage({
  jobId,
  video,
  now,
  ref,
}: {
  jobId: string;
  video: Video;
  now: number;
  ref?: Ref<HTMLDivElement>;
}) {
  const [failed, setFailed] = useState(false);
  const routes = videoRoutes(jobId, video.id);
  const life = lifecycle(video, now);
  const duration = formatDuration(videoDuration(video));

  let player;
  if (life.expired)
    player = (
      <div className="studio-unavailable" role="status" data-state="expired">
        <Clock size={20} aria-hidden="true" />
        <div>
          <p>
            <strong>This video has expired.</strong>
          </p>
          <p>
            It was available until <Timestamp value={video.expires_at} />. Published videos are
            available for 24 hours after their job was created; start a new video job to make it
            again.
          </p>
        </div>
      </div>
    );
  else if (!routes || failed)
    player = (
      <p role="status" className="notice studio-unavailable" data-tone="neutral" data-state="unavailable">
        {video.title}: this video is not available. It may have expired or been removed.
      </p>
    );
  else
    player = (
      <video
        className="video-player"
        controls
        preload="metadata"
        aria-label={video.title}
        onError={() => setFailed(true)}
      >
        <source src={routes.video} type="video/mp4" onError={() => setFailed(true)} />
        <track
          ref={loadCaptionsHidden}
          kind="captions"
          src={routes.captions}
          srcLang="en"
          label="English captions"
        />
      </video>
    );

  return (
    <div
      ref={ref}
      className="studio-stage"
      tabIndex={-1}
      data-video-id={video.id}
      data-expired={life.expired}
      aria-label={`Now showing: ${video.title}`}
      role="group"
    >
      {player}
      <div className="studio-heading">
        <CategoryBadge category={video.category} />
        <strong className="studio-title">{video.title}</strong>
        <span className="studio-subtitle">
          {categoryDescription(video.category)}
          {duration ? ` · ${duration}` : ""}
        </span>
      </div>
      {!life.expired && routes && !failed && (
        <p className="field-hint caption-note">
          Captions are burned into every frame. An English caption track is also loaded hidden,
          so assistive technology and the player&apos;s captions menu can use it without drawing
          captions twice.
        </p>
      )}
      <VideoFacts video={video} now={now} />
      {!life.expired && routes && (
        <div className="actions">
          <a className="button" href={routes.download} download>
            <Download size={16} aria-hidden="true" />
            Download MP4
          </a>
        </div>
      )}
    </div>
  );
}
