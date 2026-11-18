export type AuthProvider = "dev" | "github" | "unavailable";

/**
 * Which sign-in the API offers, read on the server so the sign-in page renders the right
 * option first. The development identities are offered only when the API says so; if the
 * API cannot be asked, no sign-in is offered rather than the wrong one.
 */
export async function authProvider(
  base = process.env.REPOVOX_API_URL || "http://localhost:8000",
): Promise<AuthProvider> {
  try {
    const response = await fetch(`${base}/v1/auth/config`, {
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return "unavailable";
    const body: unknown = await response.json();
    const provider = (body as { auth_provider?: unknown } | null)
      ?.auth_provider;
    return provider === "github" || provider === "dev"
      ? provider
      : "unavailable";
  } catch {
    return "unavailable";
  }
}
