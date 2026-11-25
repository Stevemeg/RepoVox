import type { Metadata } from "next";
import { ProjectsView } from "@/components/workspace/projects";

export const metadata: Metadata = { title: "Projects" };

export default function ProjectsPage() {
  return <ProjectsView />;
}
