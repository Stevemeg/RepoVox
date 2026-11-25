import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ProjectDetailView } from "@/components/workspace/project-detail";
import { isUuid } from "@/lib/security";

export const metadata: Metadata = { title: "Project" };

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // A malformed id never reaches the API: it renders the not-found page instead.
  if (!isUuid(id)) notFound();
  return <ProjectDetailView projectId={id} />;
}
