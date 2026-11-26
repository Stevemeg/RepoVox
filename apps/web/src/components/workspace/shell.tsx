"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  CheckCircle2,
  ChevronRight,
  Clock3,
  Folder,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings,
  X,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { ProblemNotice } from "@/components/ui/problem-notice";
import {
  api,
  ApiError,
  readCsrfToken,
  type Account,
  type Job,
  type Project,
} from "@/lib/api";
import { isUnauthorized, toProblem, type Problem } from "@/lib/errors";
import { initials } from "@/lib/format";
import { useVisibilityPolling } from "@/lib/use-visibility-polling";
import { authLabel, WorkspaceContext, type Flash, type WorkspaceValue } from "./context";

const NAVIGATION = [
  { href: "/", label: "Overview", icon: LayoutDashboard, key: "overview" },
  { href: "/projects", label: "Projects", icon: Folder, key: "projects" },
  { href: "/jobs", label: "Job history", icon: Clock3, key: "jobs" },
  { href: "/settings", label: "Settings", icon: Settings, key: "settings" },
] as const;

const REFRESH_MS = 5000;

function section(path: string): (typeof NAVIGATION)[number]["key"] {
  if (path.startsWith("/projects")) return "projects";
  if (path.startsWith("/jobs")) return "jobs";
  if (path.startsWith("/settings")) return "settings";
  return "overview";
}

function crumb(path: string): string {
  if (/^\/projects\/[^/]+/.test(path)) return "Project";
  if (/^\/jobs\/[^/]+/.test(path)) return "Job details";
  return NAVIGATION.find((item) => item.key === section(path))?.label ?? "Overview";
}

/** Signed-in application chrome and the shared session/workspace context. */
export function WorkspaceShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [account, setAccount] = useState<Account | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [flash, setFlash] = useState<Flash | null>(null);
  // A banner belongs to one page: leaving that page dismisses it.
  const [flashPath, setFlashPath] = useState(path);
  if (flashPath !== path) {
    setFlashPath(path);
    if (flash && flash.path !== path) setFlash(null);
  }
  // Incremented when the session ends, so responses for the old session are discarded.
  const generation = useRef(0);

  const forget = useCallback(() => {
    generation.current += 1;
    setAccount(null);
    setProjects([]);
    setJobs([]);
    setFlash(null);
  }, []);

  const handleUnauthorized = useCallback(
    (cause: unknown) => {
      if (!isUnauthorized(cause)) return false;
      forget();
      router.replace(
        (cause as ApiError).code === "session_required"
          ? "/sign-in"
          : "/sign-in?reason=expired",
      );
      return true;
    },
    [forget, router],
  );

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const current = generation.current;
      // The API sets and clears the readable CSRF cookie together with the session cookie:
      // without it this browser holds no session, so go to sign-in without a request.
      // When it is present the API stays the only authority on whether the session is valid.
      if (!readCsrfToken()) {
        forget();
        router.replace("/sign-in");
        setLoading(false);
        return;
      }
      try {
        const user = await api<Account>("/auth/session", { signal });
        const [ownedProjects, ownedJobs] = await Promise.all([
          api<Project[]>("/projects", { signal }),
          api<Job[]>("/jobs", { signal }),
        ]);
        if (signal?.aborted || current !== generation.current) return;
        setAccount(user);
        setProjects(ownedProjects);
        setJobs(ownedJobs);
        setProblem(null);
      } catch (cause) {
        if (signal?.aborted || current !== generation.current) return;
        if (!handleUnauthorized(cause)) setProblem(toProblem(cause));
      } finally {
        if (!signal?.aborted && current === generation.current) setLoading(false);
      }
    },
    [forget, handleUnauthorized, router],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useVisibilityPolling(() => load(), REFRESH_MS, account !== null);

  useEffect(() => {
    if (!navOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNavOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navOpen]);

  async function signOut() {
    setSigningOut(true);
    try {
      await api("/auth/sign-out", { method: "POST" });
    } catch (cause) {
      // An already-ended session is still a completed sign-out.
      if (!isUnauthorized(cause)) {
        setProblem(toProblem(cause));
        setSigningOut(false);
        return;
      }
    }
    forget();
    router.replace("/sign-in");
  }

  const value = useMemo<WorkspaceValue | null>(
    () =>
      account && {
        account,
        projects,
        jobs,
        loading,
        problem,
        refresh: () => load(),
        handleUnauthorized,
        showFlash: setFlash,
      },
    [account, projects, jobs, loading, problem, load, handleUnauthorized],
  );

  if (!value)
    return (
      <main className="status-page" aria-busy={loading}>
        <div className="status-card">
          <Brand />
          {problem ? (
            <ProblemNotice
              problem={problem}
              onRetry={() => {
                setProblem(null);
                setLoading(true);
                void load();
              }}
            />
          ) : (
            <p role="status">
              {loading ? "Opening your workspace…" : "Redirecting to sign in…"}
            </p>
          )}
          {!loading && <Link href="/sign-in">Go to sign in</Link>}
        </div>
      </main>
    );

  const active = section(path);
  const features = [
    value.account.analysis_enabled ? "Repository analysis on" : "Repository analysis off",
    value.account.video_enabled ? "narrated videos on" : "narrated videos off",
  ].join(" · ");

  return (
    <WorkspaceContext.Provider value={value}>
      <div className="app-shell" data-nav-open={navOpen ? "true" : "false"}>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <div className="sidebar" id="app-sidebar">
          <Brand />
          <nav aria-label="Primary">
            <span className="nav-section-label" aria-hidden="true">
              Workspace
            </span>
            <ul className="nav-list">
              {NAVIGATION.map((item) => (
                <li key={item.key}>
                  <Link
                    href={item.href}
                    className="nav-link"
                    title={item.label}
                    aria-current={active === item.key ? "page" : undefined}
                    onClick={() => setNavOpen(false)}
                  >
                    <item.icon size={18} aria-hidden="true" />
                    <span className="nav-label">{item.label}</span>
                    {item.key === "projects" && (
                      <span className="nav-count">
                        <span className="visually-hidden"> (</span>
                        {projects.length}
                        <span className="visually-hidden">)</span>
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="sidebar-footer">
            <div className="environment-card">
              <span className="env-badge">{value.account.environment}</span>
              <p>
                {authLabel(value.account)}. {features}.
              </p>
            </div>
            <div className="account">
              <span className="avatar" aria-hidden="true">
                {initials(value.account.display_name)}
              </span>
              <div className="account-text">
                <strong>{value.account.display_name}</strong>
                <small>{value.account.email}</small>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Sign out"
                title="Sign out"
                disabled={signingOut}
                onClick={() => void signOut()}
              >
                <LogOut size={18} aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
        <div className="nav-backdrop" aria-hidden="true" onClick={() => setNavOpen(false)} />
        <div className="app-main">
          <header className="topbar">
            <button
              type="button"
              className="icon-button menu-button"
              aria-label={navOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={navOpen}
              aria-controls="app-sidebar"
              onClick={() => setNavOpen((open) => !open)}
            >
              {navOpen ? <X size={20} aria-hidden="true" /> : <Menu size={20} aria-hidden="true" />}
            </button>
            <Brand className="brand topbar-brand" />
            <p className="breadcrumb">
              <span>Workspace</span>
              <ChevronRight size={14} aria-hidden="true" />
              <strong>{crumb(path)}</strong>
            </p>
            <span className="env-badge">{value.account.environment}</span>
          </header>
          <main id="main-content" className="content" tabIndex={-1}>
            {problem && (
              <ProblemNotice
                problem={problem}
                onRetry={() => {
                  setProblem(null);
                  void load();
                }}
              />
            )}
            {flash && flash.path === path && (
              <div className="notice flash-notice" data-tone="success" role="status">
                <CheckCircle2 size={16} aria-hidden="true" />
                <div className="flash-body">
                  <p>
                    <strong>{flash.title}.</strong> {flash.message}
                  </p>
                  {flash.reference && (
                    <small className="problem-meta">Reference: {flash.reference}</small>
                  )}
                </div>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Dismiss notice"
                  title="Dismiss notice"
                  onClick={() => setFlash(null)}
                >
                  <X size={16} aria-hidden="true" />
                </button>
              </div>
            )}
            {children}
          </main>
          <footer className="app-footer">
            <span>RepoVox</span>
            <span aria-hidden="true">·</span>
            <span>Evidence-grounded walkthroughs of public GitHub repositories</span>
          </footer>
        </div>
      </div>
    </WorkspaceContext.Provider>
  );
}
