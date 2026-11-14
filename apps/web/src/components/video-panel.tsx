"use client";
import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";

const ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const TERMINAL = ["succeeded", "failed", "cancelled"];

export type Video = {
  id: string;
  category: string;
  title: string;
  byte_count: number;
  checksum: string;
  metadata: {
    duration_seconds?: number;
    media?: { duration_seconds?: number };
  };
};
export type VideoJob = {
  id: string;
  project_id: string;
  state: string;
  repository: string | null;
  commit_sha: string | null;
  architecture: string | null;
  error_code: string | null;
  created_at: string;
  stages: { ordinal: number; stage_key: string; state: string }[];
  videos: Video[];
};

// Same-origin, owner-authorized routes only. Ids are validated before they enter a URL.
export function videoRoutes(jobId: string, videoId: string) {
  if (!ID.test(jobId) || !ID.test(videoId)) return null;
  const base = `/api/v1/video-jobs/${jobId}/videos/${videoId}`;
  return {
    video: base,
    captions: `${base}/captions`,
    download: `${base}/download`,
  };
}

const architectureNote = (job: VideoJob): string => {
  if (job.architecture === "supported")
    return "Architecture explainers were generated from verified source relationships.";
  if (job.architecture === "unsupported")
    return "No architecture explainer: the source evidence was not sufficient to establish one.";
  if (job.architecture === "failed")
    return "The architecture explainer could not be completed. The walkthrough is unaffected.";
  return "";
};

export function VideoPlayer({ jobId, video }: { jobId: string; video: Video }) {
  const [failed, setFailed] = useState(false);
  const routes = videoRoutes(jobId, video.id);
  const seconds =
    video.metadata.duration_seconds ?? video.metadata.media?.duration_seconds;
  if (!routes || failed)
    return (
      <p role="status">
        {video.title}: this video is not available. It may have expired.
      </p>
    );
  return (
    <figure className="video-item">
      <figcaption>
        <strong>{video.title}</strong>{" "}
        <span>
          {video.category === "architecture"
            ? "Architecture explainer"
            : "Repository walkthrough"}
          {seconds ? ` · ${Math.round(seconds)} s` : ""}
        </span>
      </figcaption>
      <video
        controls
        preload="metadata"
        aria-label={video.title}
        style={{ width: "100%", aspectRatio: "16 / 9", background: "#0a1220" }}
        onError={() => setFailed(true)}
      >
        <source src={routes.video} type="video/mp4" />
        <track
          kind="captions"
          src={routes.captions}
          srcLang="en"
          label="English"
          default
        />
      </video>
      <p className="actions">
        <a href={routes.download} download>
          Download MP4
        </a>
      </p>
    </figure>
  );
}

export function VideoJobs({ projectId }: { projectId: string }) {
  const [jobs, setJobs] = useState<VideoJob[]>([]);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const valid = ID.test(projectId);
  const load = useCallback(async () => {
    if (!valid) return;
    try {
      setJobs(await api<VideoJob[]>(`/projects/${projectId}/video-jobs`));
    } catch (error) {
      setMessage(errorMessage(error));
    }
  }, [projectId, valid]);
  const active = jobs.some((job) => !TERMINAL.includes(job.state));
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!active) return;
    // Reading a job is also what lets a waiting job pick up its finished analysis.
    const timer = setInterval(() => void load(), 3000);
    return () => clearInterval(timer);
  }, [active, load]);
  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    setMessage("");
    try {
      await run();
      await load();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  if (!valid) return null;
  return (
    <section className="panel details">
      <div className="panel-heading">
        <h2>Narrated videos</h2>
      </div>
      <p>
        Creates a repository walkthrough and, where the source evidence supports
        it, architecture explainers. A public GitHub snapshot is analysed as
        data in local private storage for up to 24 hours. Narration is a local
        synthetic voice. No AI model and no paid service is used.
      </p>
      <label>
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => setAcknowledged(event.target.checked)}
        />{" "}
        I acknowledge this local source processing for video creation.
      </label>
      <div className="actions">
        <button
          disabled={busy || !acknowledged || active}
          onClick={() =>
            void act(() =>
              api(`/projects/${projectId}/video-jobs`, {
                method: "POST",
                headers: { "Idempotency-Key": crypto.randomUUID() },
                body: JSON.stringify({ processing_acknowledged: true }),
              }),
            )
          }
        >
          Create narrated videos
        </button>
      </div>
      {message && <p className="notice">{message}</p>}
      {jobs.map((job) => (
        <article key={job.id} aria-label={`Video job ${job.id.slice(0, 8)}`}>
          <h3>
            Video job <span>{job.id.slice(0, 8)}</span> · {job.state}
          </h3>
          {job.commit_sha && (
            <p>
              {job.repository} · pinned commit <code>{job.commit_sha}</code>
            </p>
          )}
          {!TERMINAL.includes(job.state) && (
            <>
              <p role="status">
                {job.state === "awaiting_analysis"
                  ? "Waiting for verified static analysis to finish."
                  : `Working: ${
                      job.stages.find((stage) =>
                        ["ready", "running", "retry_wait"].includes(
                          stage.state,
                        ),
                      )?.stage_key ?? "starting"
                    }.`}
              </p>
              <button
                disabled={busy}
                onClick={() =>
                  void act(() =>
                    api(`/video-jobs/${job.id}/cancel`, { method: "POST" }),
                  )
                }
              >
                Cancel video job
              </button>
            </>
          )}
          {job.error_code && (
            <p className="notice">Status code: {job.error_code}</p>
          )}
          {job.state === "succeeded" && <p>{architectureNote(job)}</p>}
          {job.videos.map((video) => (
            <VideoPlayer key={video.id} jobId={job.id} video={video} />
          ))}
        </article>
      ))}
    </section>
  );
}
