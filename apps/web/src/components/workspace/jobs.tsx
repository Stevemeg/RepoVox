"use client";
import { Info } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonRows } from "@/components/ui/states";
import { useWorkspace } from "./context";
import { JobList } from "./records";

export function JobsView() {
  const { account, jobs, loading } = useWorkspace();
  return (
    <>
      <PageHeader
        eyebrow="History"
        title="Job history"
        description="Durable records of every repository analysis and synthetic fixture you started."
      />
      <div className="notice" data-tone="neutral">
        <Info size={16} aria-hidden="true" />
        <p>
          Synthetic fixtures exercise the job pipeline only; they do not analyze repositories
          or generate videos. Repository analyses are labelled separately.
          {account.video_enabled &&
            " Narrated video jobs are listed on each project's page."}
        </p>
      </div>
      <section className="panel" aria-label="Jobs" aria-busy={loading}>
        {loading ? <SkeletonRows rows={5} /> : <JobList jobs={jobs} />}
      </section>
    </>
  );
}
