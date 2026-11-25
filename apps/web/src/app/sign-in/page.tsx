import type { Metadata } from "next";
import { SignInPanel } from "@/components/sign-in";
import { authProvider } from "@/lib/auth";

export const metadata: Metadata = { title: "Sign in" };

// Rendered per request: the page asks the API which identity adapter is active.
export const dynamic = "force-dynamic";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ reason }, provider] = await Promise.all([searchParams, authProvider()]);
  // Only one fixed value is meaningful; nothing from the query is ever rendered.
  return <SignInPanel authProvider={provider} expired={reason === "expired"} />;
}
