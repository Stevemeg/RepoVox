import { Workspace } from "@/components/workspace";
import { authProvider } from "@/lib/auth";

// Rendered per request: the sign-in page asks the API which identity adapter is active.
export const dynamic = "force-dynamic";

export default async function Page({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path } = await params;
  const signIn = path?.length === 1 && path[0] === "sign-in";
  return <Workspace authProvider={signIn ? await authProvider() : "dev"} />;
}
