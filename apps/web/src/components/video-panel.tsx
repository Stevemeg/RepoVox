"use client";
import { useState } from "react";

const JOB = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

// Same-origin, owner-authorized routes only. The job id is validated before it enters a URL.
export function videoRoutes(jobId: string) {
  if (!JOB.test(jobId)) return null;
  const base = `/api/v1/jobs/${jobId}/video`;
  return {
    video: base,
    captions: `${base}/captions`,
    download: `${base}/download`,
  };
}

export function VideoPanel({ jobId }: { jobId: string }) {
  const [failedJob, setFailedJob] = useState<string | null>(null);
  const routes = videoRoutes(jobId);
  if (!routes || failedJob === jobId)
    return (
      <section className="panel details">
        <p role="status">
          The video is not available. It may have expired, or it was never
          published for this job.
        </p>
      </section>
    );
  return (
    <section className="panel details">
      <div className="panel-heading">
        <h2>Narrated explanation video</h2>
      </div>
      <p>
        Generated from verified static analysis of the pinned commit. Narration
        is a local synthetic voice. Every technical statement cites source
        evidence; nothing about runtime behavior or project purpose is claimed.
      </p>
      <video
        key={jobId}
        controls
        preload="metadata"
        aria-label="Narrated repository explanation"
        style={{ width: "100%", aspectRatio: "16 / 9", background: "#0a1220" }}
        onError={() => setFailedJob(jobId)}
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
    </section>
  );
}
