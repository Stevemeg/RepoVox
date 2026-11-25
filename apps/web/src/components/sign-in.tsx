"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { Brand } from "@/components/brand";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { api, readCsrfToken } from "@/lib/api";
import type { AuthProvider } from "@/lib/auth";
import { toProblem, type Problem } from "@/lib/errors";

const PERSONAS = [
  { subject: "alex", name: "Alex Chen", initials: "AC" },
  { subject: "sam", name: "Sam Rivera", initials: "SR" },
] as const;

/**
 * Sign-in for whichever identity adapter the API reports (read on the server). The
 * development personas appear only when the API says the development adapter is active.
 */
export function SignInPanel({
  authProvider,
  expired = false,
}: {
  authProvider: AuthProvider;
  expired?: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);

  // Someone already signed in is sent straight to the workspace. The API issues and clears
  // the readable CSRF cookie together with the session cookie, so without it there is no
  // session to find and no request is made.
  useEffect(() => {
    if (!readCsrfToken()) return;
    const controller = new AbortController();
    api("/auth/session", { signal: controller.signal })
      .then(() => {
        if (!controller.signal.aborted) router.replace("/");
      })
      .catch(() => {});
    return () => controller.abort();
  }, [router]);

  async function signIn(subject: string) {
    setBusy(true);
    setProblem(null);
    try {
      await api("/auth/development/sign-in", {
        method: "POST",
        body: JSON.stringify({ subject }),
      });
      router.replace("/");
    } catch (cause) {
      setProblem(toProblem(cause, "sign-in"));
      setBusy(false);
    }
  }

  return (
    <main className="sign-in">
      <div className="sign-in-art">
        <Brand />
        <div>
          <span className="eyebrow">From repository to revelation</span>
          <h1>
            Every codebase
            <br />
            has a story.
          </h1>
          <p>
            RepoVox reads one pinned commit of a public repository as data, never runs it,
            and separates what the code shows from what its authors say.
          </p>
          <ol className="pipeline-art" aria-label="How RepoVox works">
            <li>pinned commit</li>
            <li>verified analysis</li>
            <li>narrated story</li>
          </ol>
        </div>
        <small>Bring source code to life visually.</small>
      </div>
      <div className="sign-in-panel">
        {authProvider === "github" ? (
          <>
            <span className="env-badge">Secure sign-in</span>
            <h2>Welcome to your workspace</h2>
            <p>Sign in with GitHub. Access is limited to accounts an administrator has approved.</p>
            {expired && <p role="status">Your session expired. Sign in to continue.</p>}
            <a className="identity" href="/api/v1/auth/github/login">
              <span className="avatar" aria-hidden="true">
                GH
              </span>
              <span className="identity-text">
                <strong>Continue with GitHub</strong>
                <small>You return here after GitHub confirms it is you.</small>
              </span>
              <ArrowRight size={18} aria-hidden="true" />
            </a>
            <p className="fine-print">
              RepoVox reads only your public GitHub profile to confirm your account. Your
              GitHub access token is not stored. Sessions expire automatically (one hour by
              default).
            </p>
          </>
        ) : authProvider === "unavailable" ? (
          <>
            <h2>Sign-in is unavailable</h2>
            <div className="problem" role="alert">
              <p className="problem-message">
                The RepoVox service could not be reached, so no sign-in can be offered. Try
                again in a moment.
              </p>
            </div>
            <a className="button" href="/sign-in">
              Try again
            </a>
          </>
        ) : (
          <>
            <span className="env-badge">Development sign-in</span>
            <h2>Welcome to your workspace</h2>
            <p>Choose a seeded development identity to explore RepoVox.</p>
            {expired && <p role="status">Your session expired. Sign in to continue.</p>}
            {problem && <ProblemNotice problem={problem} />}
            {PERSONAS.map((persona) => (
              <button
                type="button"
                className="identity"
                disabled={busy}
                key={persona.subject}
                onClick={() => void signIn(persona.subject)}
              >
                <span className="avatar" aria-hidden="true">
                  {persona.initials}
                </span>
                <span className="identity-text">
                  <strong>{persona.name}</strong>
                  <small>{persona.subject}@example.test</small>
                </span>
                <ArrowRight size={18} aria-hidden="true" />
              </button>
            ))}
            <p className="fine-print">
              Development identities only. They exist only in development and test
              environments, have no password, and are not production accounts. Sessions
              expire automatically (one hour by default).
            </p>
          </>
        )}
      </div>
    </main>
  );
}
