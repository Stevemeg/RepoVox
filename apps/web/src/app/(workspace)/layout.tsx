import { WorkspaceShell } from "@/components/workspace/shell";

// Signed-in pages are never prerendered or cached: each request renders the shell, which
// loads the session through the same-origin API proxy.
export const dynamic = "force-dynamic";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
