import type { Metadata } from "next";
import { JobsView } from "@/components/workspace/jobs";

export const metadata: Metadata = { title: "Job history" };

export default function JobsPage() {
  return <JobsView />;
}
