"use client";
import { useCallback, useContext, useState } from "react";
import { toProblem, type ErrorContext, type Problem } from "@/lib/errors";
import { WorkspaceContext } from "./context";

/**
 * Runs one user action at a time with a busy flag and a mapped problem. A 401 is handed to
 * the workspace shell (which redirects to sign-in) when one is present.
 */
export function useAction(context: ErrorContext = "general") {
  const workspace = useContext(WorkspaceContext);
  const handleUnauthorized = workspace?.handleUnauthorized;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);

  const run = useCallback(
    async (action: () => Promise<unknown>): Promise<boolean> => {
      setBusy(true);
      setProblem(null);
      try {
        await action();
        return true;
      } catch (cause) {
        if (!handleUnauthorized?.(cause)) setProblem(toProblem(cause, context));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [context, handleUnauthorized],
  );
  const clear = useCallback(() => setProblem(null), []);
  return { busy, problem, run, clear };
}
