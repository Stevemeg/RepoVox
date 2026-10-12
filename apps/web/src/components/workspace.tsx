"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowRight,
  Box,
  ChevronRight,
  Clock3,
  Code2,
  Folder,
  LayoutDashboard,
  LogOut,
  Plus,
  Settings,
  Sparkles,
  Workflow,
} from "lucide-react";
import { Account, api, ApiError, errorMessage, Job, Project } from "@/lib/api";

export function Badge({ state }: { state: string }) {
  return (
    <span className={`badge ${state}`}>
      <span className="status-dot" />
      {state.replaceAll("_", " ")}
    </span>
  );
}
export function Empty({
  kind,
  action,
}: {
  kind: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Box size={32} />
      <h3>No {kind} yet</h3>
      <p>
        {kind === "projects"
          ? "Add a GitHub repository to organize your workspace."
          : "Synthetic jobs will appear here when you run a development fixture."}
      </p>
      {action}
    </div>
  );
}
export function GenerationNotice() {
  return (
    <div className="generation-note">
      <Sparkles size={22} />
      <div>
        <strong>Your code has a story to tell</strong>
        <p>
          Video generation arrives in a later phase. This workspace stores
          repository locators and trusted development fixtures.
        </p>
      </div>
      <button
        disabled
        title="Secure repository acquisition is not implemented yet"
      >
        Generate video <ArrowRight size={15} />
      </button>
    </div>
  );
}
function date(value: string) {
  return new Date(value).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
  });
}

export function Workspace() {
  const path = usePathname();
  const router = useRouter();
  const [account, setAccount] = useState<Account | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [expired, setExpired] = useState(false);
  const signIn = path === "/sign-in";
  const projectId = path.startsWith("/projects/") ? path.split("/")[2] : null;
  const jobId = path.startsWith("/jobs/") ? path.split("/")[2] : null;
  const section = path.startsWith("/projects")
    ? "projects"
    : path.startsWith("/jobs")
      ? "jobs"
      : path === "/settings"
        ? "settings"
        : "dashboard";

  const handleError = useCallback(
    (cause: unknown) => {
      setError(errorMessage(cause));
      if (cause instanceof ApiError && cause.status === 401) {
        setAccount(null);
        setProjects([]);
        setJobs([]);
        setSelectedJob(null);
        setExpired(true);
        router.replace("/sign-in");
      }
    },
    [router],
  );

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const user = await api<Account>("/auth/session", { signal });
        const [ownedProjects, ownedJobs] = await Promise.all([
          api<Project[]>("/projects", { signal }),
          api<Job[]>("/jobs", { signal }),
        ]);
        if (signal?.aborted) return;
        setAccount(user);
        setProjects(ownedProjects);
        setJobs(ownedJobs);
        if (jobId) setSelectedJob(await api<Job>(`/jobs/${jobId}`, { signal }));
        if (signIn) router.replace("/");
      } catch (cause) {
        if (
          !signal?.aborted &&
          !(signIn && cause instanceof ApiError && cause.status === 401)
        )
          handleError(cause);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [jobId, signIn, router, handleError],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  useEffect(() => {
    if (!account || signIn) return;
    const timer = setInterval(() => {
      void load();
    }, 5000);
    return () => clearInterval(timer);
  }, [account, signIn, load]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (cause) {
      handleError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (signIn)
    return (
      <main className="sign-in">
        <div className="sign-in-art">
          <Brand />
          <div>
            <span className="eyebrow">FROM REPOSITORY TO REVELATION</span>
            <h1>
              Every codebase
              <br />
              has a story.
            </h1>
            <p>A clearer way to see how software fits together.</p>
            <div className="code-art">
              <span>&lt; repository /&gt;</span>
              <i />
              <span>architecture</span>
              <i />
              <span>your next story</span>
            </div>
          </div>
          <small>Bring source code to life visually.</small>
        </div>
        <div className="sign-in-panel">
          <span className="environment">
            <span /> LOCAL DEVELOPMENT
          </span>
          <h2>Welcome to your workspace</h2>
          <p>Choose a seeded test identity to explore RepoVox.</p>
          {expired && (
            <p role="status">Your session expired. Sign in to continue.</p>
          )}
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {["alex", "sam"].map((subject, i) => (
            <button
              className="identity"
              disabled={busy}
              key={subject}
              onClick={() =>
                void act(async () => {
                  await api("/auth/development/sign-in", {
                    method: "POST",
                    body: JSON.stringify({ subject }),
                  });
                  setExpired(false);
                  router.replace("/");
                })
              }
            >
              <span className={`avatar ${i ? "mint" : ""}`}>
                {i ? "SR" : "AC"}
              </span>
              <span>
                <strong>{i ? "Sam Rivera" : "Alex Chen"}</strong>
                <small>{subject}@example.test</small>
              </span>
              <ArrowRight size={18} />
            </button>
          ))}
          <p className="fine-print">
            Development identities only. No password or production account is
            created. Sessions expire after one hour.
          </p>
        </div>
      </main>
    );

  if (!account)
    return (
      <main className="fatal" aria-busy={loading}>
        <Brand />
        <p role="status">
          {loading
            ? "Opening your workspace…"
            : error || "Redirecting to sign in…"}
        </p>
        {!loading && <Link href="/sign-in">Sign in</Link>}
      </main>
    );
  const project = projects.find((p) => p.id === projectId);
  const active = jobs.filter((j) =>
    ["queued", "running", "retry_wait"].includes(j.state),
  ).length;
  const heading = projectId
    ? project?.title || "Project"
    : jobId
      ? "Job details"
      : {
          dashboard: "Overview",
          projects: "Projects",
          jobs: "Job history",
          settings: "Settings",
        }[section];
  const createButton = (
    <button className="primary" onClick={() => setShowForm(true)}>
      <Plus size={17} /> New project
    </button>
  );
  const jobRows = (items: Job[]) =>
    items.length ? (
      <div className="job-list">
        {items.map((j) => (
          <Link className="job-row" href={`/jobs/${j.id}`} key={j.id}>
            <span className="job-icon">
              <Workflow size={19} />
            </span>
            <div>
              <strong>{j.project_title || "Development fixture"}</strong>
              <small>
                Synthetic · {j.id.slice(0, 8)} · {date(j.created_at)}
              </small>
            </div>
            <Badge state={j.state} />
            <ChevronRight size={16} />
          </Link>
        ))}
      </div>
    ) : (
      <Empty kind="jobs" />
    );

  return (
    <div className="workspace">
      <aside className="sidebar">
        <Brand />
        <div className="workspace-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {[
            {
              href: "/",
              label: "Overview",
              icon: LayoutDashboard,
              key: "dashboard",
            },
            {
              href: "/projects",
              label: "Projects",
              icon: Folder,
              key: "projects",
            },
            { href: "/jobs", label: "Job history", icon: Clock3, key: "jobs" },
            {
              href: "/settings",
              label: "Settings",
              icon: Settings,
              key: "settings",
            },
          ].map((item) => (
            <Link
              key={item.key}
              href={item.href}
              className={section === item.key ? "active" : ""}
              aria-current={section === item.key ? "page" : undefined}
            >
              <item.icon size={18} />
              {item.label}
              {item.key === "projects" && (
                <span className="nav-count">{projects.length}</span>
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className="environment">
              <span /> DEVELOPMENT
            </span>
            <p>
              Your local workspace.
              <br />
              Generation is coming later.
            </p>
          </div>
          <div className="account">
            <span className="avatar">
              {account.display_name
                .split(" ")
                .map((n) => n[0])
                .join("")}
            </span>
            <div>
              <strong>{account.display_name}</strong>
              <small>Personal workspace</small>
            </div>
            <button
              className="icon-button"
              aria-label="Sign out"
              onClick={() =>
                void act(async () => {
                  await api("/auth/sign-out", { method: "POST" });
                  setAccount(null);
                  router.replace("/sign-in");
                })
              }
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-wrap">
        <header className="topbar">
          <span>
            Workspace <ChevronRight size={14} /> <strong>{heading}</strong>
          </span>
          <span className="environment">
            <span /> LOCAL ENVIRONMENT
          </span>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">YOUR WORKSPACE, AT A GLANCE</span>
              <h1>{heading}</h1>
              <p>
                {section === "dashboard"
                  ? `Welcome back, ${account.display_name.split(" ")[0]}. Let's bring a little clarity to your code.`
                  : section === "projects"
                    ? "A home for the repositories you want to understand."
                    : section === "jobs"
                      ? "Durable records of your local development workflows."
                      : "Your account and development environment."}
              </p>
            </div>
            {section === "projects" && !projectId && createButton}
          </div>
          {error && (
            <div role="alert" className="error">
              {error}
              <button
                onClick={() => {
                  setError("");
                  void load();
                }}
              >
                Retry
              </button>
            </div>
          )}
          {loading && <p role="status">Loading records…</p>}
          {section === "dashboard" && (
            <>
              <div className="stats">
                <Stat
                  label="Projects"
                  value={projects.length}
                  icon={<Folder />}
                  note="Repository locators"
                />
                <Stat
                  label="Active jobs"
                  value={active}
                  icon={<Workflow />}
                  note="Persisted development workflows"
                />
                <Stat
                  label="Videos generated"
                  value={0}
                  icon={<Sparkles />}
                  note="Available in a later phase"
                />
              </div>
              <GenerationNotice />
              <section className="panel">
                <div className="panel-heading">
                  <h2>
                    Your projects <span>{projects.length}</span>
                  </h2>
                  <Link href="/projects">
                    View all <ArrowRight size={14} />
                  </Link>
                </div>
                {projects.length ? (
                  <div className="project-grid">
                    {projects.slice(0, 3).map((p) => (
                      <ProjectCard key={p.id} project={p} />
                    ))}
                  </div>
                ) : (
                  <Empty kind="projects" action={createButton} />
                )}
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Recent activity</h2>
                  <Link href="/jobs">
                    Job history <ArrowRight size={14} />
                  </Link>
                </div>
                {jobRows(jobs.slice(0, 5))}
              </section>
            </>
          )}
          {section === "projects" &&
            !projectId &&
            (projects.length ? (
              <div className="project-grid">
                {projects.map((p) => (
                  <ProjectCard key={p.id} project={p} />
                ))}
              </div>
            ) : (
              <section className="panel">
                <Empty kind="projects" action={createButton} />
              </section>
            ))}
          {projectId &&
            (project ? (
              <>
                <section className="panel details">
                  <div className="project-icon">
                    <Code2 />
                  </div>
                  <h2>{project.title}</h2>
                  <a
                    href={project.repository_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {project.repository_url} <ArrowRight size={14} />
                  </a>
                  <p>
                    <Badge state={project.status} />
                  </p>
                  <p>
                    This is an unprocessed repository locator. No repository
                    contents or ownership have been verified.
                  </p>
                  <div className="actions">
                    {account.fixtures_enabled && (
                      <button
                        disabled={busy}
                        onClick={() =>
                          void act(() =>
                            api(
                              `/development/projects/${project.id}/fixture-jobs`,
                              {
                                method: "POST",
                                headers: {
                                  "Idempotency-Key": crypto.randomUUID(),
                                },
                                body: JSON.stringify({ fixture: "normal" }),
                              },
                            ),
                          )
                        }
                      >
                        Run synthetic fixture
                      </button>
                    )}
                    <button
                      className="danger"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            "Delete this project and revoke access to its jobs?",
                          )
                        )
                          void act(async () => {
                            await api(`/projects/${project.id}`, {
                              method: "DELETE",
                            });
                            router.push("/projects");
                          });
                      }}
                    >
                      Delete project
                    </button>
                  </div>
                </section>
                <GenerationNotice />
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Project jobs</h2>
                  </div>
                  {jobRows(jobs.filter((j) => j.project_id === project.id))}
                </section>
              </>
            ) : (
              <section className="panel">
                <h2>Project unavailable</h2>
                <p>This record is unavailable in your workspace.</p>
                <Link href="/projects">Back to projects</Link>
              </section>
            ))}
          {section === "jobs" && !jobId && (
            <>
              <div className="notice">
                All Phase 1 jobs are synthetic fixtures. They do not analyze
                repositories or generate videos.
              </div>
              <section className="panel">{jobRows(jobs)}</section>
            </>
          )}
          {jobId && selectedJob && (
            <>
              <section className="panel details">
                <div className="panel-heading">
                  <h2>
                    Synthetic fixture <span>{selectedJob.id.slice(0, 8)}</span>
                  </h2>
                  <Badge state={selectedJob.state} />
                </div>
                <p>
                  Trusted development fixture · No repository acquisition, AI,
                  audio or video processing.
                </p>
                {selectedJob.error_code && (
                  <p className="notice">
                    {selectedJob.error_code === "phase1_fixture_boundary"
                      ? "The fixture finished its infrastructure demonstration. The generation pipeline is unavailable in Phase 1."
                      : `Status code: ${selectedJob.error_code}`}
                  </p>
                )}
                <div className="actions">
                  {["queued", "running", "retry_wait"].includes(
                    selectedJob.state,
                  ) && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        void act(() =>
                          api(`/jobs/${selectedJob.id}/cancel`, {
                            method: "POST",
                          }),
                        )
                      }
                    >
                      Cancel fixture
                    </button>
                  )}
                  {["failed", "cancelled"].includes(selectedJob.state) && (
                    <button
                      disabled={busy}
                      onClick={() =>
                        void act(() =>
                          api(`/development/jobs/${selectedJob.id}/retry`, {
                            method: "POST",
                            headers: { "Idempotency-Key": crypto.randomUUID() },
                          }),
                        )
                      }
                    >
                      Retry as a new fixture
                    </button>
                  )}
                </div>
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Pipeline stages</h2>
                  <span>14 durable identifiers</span>
                </div>
                <ol className="stages">
                  {selectedJob.stages?.map((s) => (
                    <li key={s.id}>
                      <span className="stage-number">
                        {s.ordinal.toString().padStart(2, "0")}
                      </span>
                      <strong>{s.stage_key}</strong>
                      <small>{s.attempt_count} attempts</small>
                      <Badge state={s.state} />
                    </li>
                  ))}
                </ol>
              </section>
              <section className="panel details">
                <h2>State history</h2>
                <ul className="history">
                  {selectedJob.history?.map((h) => (
                    <li key={h.version}>
                      <span>v{h.version}</span>
                      <Badge state={h.state} />
                      <time>{date(h.created_at)}</time>
                    </li>
                  ))}
                </ul>
                <h2>Attempt history</h2>
                {selectedJob.attempts?.map((a, i) => (
                  <p key={i}>
                    Attempt {a.attempt_no} · {a.outcome.replaceAll("_", " ")}
                    {a.error_code && ` · ${a.error_code}`}
                  </p>
                ))}
                <h2>Usage ledger</h2>
                {selectedJob.usage?.map((u, i) => (
                  <p key={i}>
                    {u.event_type} · {u.units} fixture unit
                  </p>
                ))}
              </section>
            </>
          )}
          {section === "settings" && (
            <section className="panel details">
              <h2>Account</h2>
              <dl>
                <dt>Name</dt>
                <dd>{account.display_name}</dd>
                <dt>Email</dt>
                <dd>{account.email}</dd>
                <dt>Environment</dt>
                <dd>{account.environment} · Development authentication</dd>
              </dl>
              <div className="notice">
                Your identity is one of two seeded local users. Managed
                production identity and video generation remain later-phase
                features.
              </div>
            </section>
          )}
          <footer>
            RepoVox <span>·</span> Bring source code to life visually{" "}
            <span className="footer-phase">Phase 1 · Local foundation</span>
          </footer>
        </main>
      </div>
      {showForm && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="new-project"
          >
            <h2 id="new-project">Add a project</h2>
            <p>Save a GitHub repository locator to your workspace.</p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void act(async () => {
                  await api("/projects", {
                    method: "POST",
                    body: JSON.stringify({ title, repository_url: url }),
                  });
                  setShowForm(false);
                  setUrl("");
                  setTitle("");
                  router.push("/projects");
                });
              }}
            >
              <label htmlFor="project-title">Project name</label>
              <input
                id="project-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={100}
                required
                autoFocus
              />
              <label htmlFor="repository-url">GitHub repository URL</label>
              <input
                id="repository-url"
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://github.com/owner/repo"
                maxLength={250}
                required
              />
              <p className="fine-print">
                RepoVox saves the locator only. Nothing is cloned or analyzed.
              </p>
              {error && (
                <p role="alert" className="error">
                  {error}
                </p>
              )}
              <div className="actions">
                <button type="button" onClick={() => setShowForm(false)}>
                  Cancel
                </button>
                <button className="primary" disabled={busy} type="submit">
                  {busy ? "Saving…" : "Create project"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
function Brand() {
  return (
    <Link href="/" className="brand">
      <span className="brand-mark">
        <Code2 size={22} />
      </span>
      RepoVox<span className="brand-period">.</span>
    </Link>
  );
}
function Stat({
  label,
  value,
  icon,
  note,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  note: string;
}) {
  return (
    <div className="stat">
      <div>
        <span>{label}</span>
        {icon}
      </div>
      <strong>{value.toString().padStart(2, "0")}</strong>
      <small>{note}</small>
    </div>
  );
}
function ProjectCard({ project }: { project: Project }) {
  return (
    <Link className="project-card" href={`/projects/${project.id}`}>
      <div className="project-card-top">
        <span className="project-icon">
          <Code2 size={21} />
        </span>
        <ChevronRight size={17} />
      </div>
      <h3>{project.title}</h3>
      <p>{project.repository_url.replace("https://github.com/", "")}</p>
      <div className="project-card-bottom">
        <Badge state={project.status} />
        <small>{date(project.created_at)}</small>
      </div>
    </Link>
  );
}
