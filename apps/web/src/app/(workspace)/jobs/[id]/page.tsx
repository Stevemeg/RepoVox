import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { JobDetailView } from "@/components/workspace/job-detail";
import { isUuid } from "@/lib/security";

export const metadata: Metadata = { title: "Job details" };

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // A malformed id never reaches the API: it renders the not-found page instead.
  if (!isUuid(id)) notFound();
  return <JobDetailView jobId={id} />;
}
