"use client";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, SkeletonRows } from "@/components/ui/states";
import { useWorkspace } from "./context";
import { NewProjectButton } from "./create-project";
import { ProjectGrid } from "./records";

export function ProjectsView() {
  const { projects, jobs, loading } = useWorkspace();
  return (
    <>
      <PageHeader
        eyebrow="Repositories"
        title="Projects"
        description="A home for the public repositories you want to understand."
        actions={<NewProjectButton />}
      />
      {loading ? (
        <section className="panel" aria-busy="true">
          <SkeletonRows />
        </section>
      ) : projects.length ? (
        <ProjectGrid projects={projects} jobs={jobs} />
      ) : (
        <section className="panel">
          <EmptyState
            title="No projects yet"
            description="Add a public GitHub repository to start building its story."
            action={<NewProjectButton className="" />}
          />
        </section>
      )}
    </>
  );
}
