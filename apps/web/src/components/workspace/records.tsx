import Link from "next/link";
import { ChevronRight, Code2, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/states";
import type { Job, Project } from "@/lib/api";
import { formatDate, shortId } from "@/lib/format";
import { safeGitHubRepoUrl } from "@/lib/security";

/** "owner/name" for a validated locator; the raw string is shown only as inert text. */
export function repositoryLabel(url: string): string {
  const safe = safeGitHubRepoUrl(url);
  return safe ? safe.slice("https://github.com/".length) : url;
}

export function ProjectCard({ project }: { project: Project }) {
  return (
    <Link className="project-card" href={`/projects/${encodeURIComponent(project.id)}`}>
      <div className="project-card-top">
        <span className="icon-tile" aria-hidden="true">
          <Code2 size={18} />
        </span>
        <ChevronRight size={16} aria-hidden="true" />
      </div>
      <h3>{project.title}</h3>
      <p className="project-card-repo">{repositoryLabel(project.repository_url)}</p>
      <div className="project-card-bottom">
        <Badge state={project.status} />
        <small>{formatDate(project.created_at)}</small>
      </div>
    </Link>
  );
}

export function ProjectGrid({ projects }: { projects: Project[] }) {
  return (
    <div className="card-grid">
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  );
}

export function JobList({
  jobs,
  emptyDescription = "Repository analyses and synthetic fixtures appear here once you start one from a project.",
}: {
  jobs: Job[];
  emptyDescription?: string;
}) {
  if (jobs.length === 0) return <EmptyState title="No jobs yet" description={emptyDescription} />;
  return (
    <div className="job-list">
      {jobs.map((job) => (
        <Link className="job-row" href={`/jobs/${encodeURIComponent(job.id)}`} key={job.id}>
          <span className="icon-tile" aria-hidden="true">
            <Workflow size={18} />
          </span>
          <div className="job-row-main">
            <strong>{job.project_title || "Untitled project"}</strong>
            <small>
              {job.synthetic ? "Synthetic" : "Static analysis"} · {shortId(job.id)} ·{" "}
              {formatDate(job.created_at)}
            </small>
          </div>
          <Badge state={job.state} />
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      ))}
    </div>
  );
}
