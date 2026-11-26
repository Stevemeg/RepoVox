"use client";
import { createContext, useContext } from "react";
import type { Account, Job, Project } from "@/lib/api";
import type { Problem } from "@/lib/errors";

/** A one-time status banner for the page at `path`, such as the result of a deletion. */
export type Flash = {
  path: string;
  title: string;
  message: string;
  /** A record reference shown as muted support metadata. */
  reference?: string;
};

export type WorkspaceValue = {
  account: Account;
  projects: Project[];
  jobs: Job[];
  /** True until the first project and job lists have loaded. */
  loading: boolean;
  /** The last refresh problem, shown by the shell. */
  problem: Problem | null;
  /** Reload the session, projects and jobs. */
  refresh: () => Promise<void>;
  /**
   * Ends the local session view and redirects to sign-in when `cause` is a 401. Returns
   * true when it handled the error, so callers report everything else themselves.
   */
  handleUnauthorized: (cause: unknown) => boolean;
  /**
   * Shows `flash` once its `path` is the current page. It stays until dismissed or until the
   * person navigates to another page.
   */
  showFlash: (flash: Flash) => void;
};

export const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside <WorkspaceShell>");
  return value;
}

/** Human labels for the account's identity adapter, from the session itself. */
export const authLabel = (account: Account) =>
  account.auth_provider === "github" ? "GitHub OAuth" : "Development authentication";
