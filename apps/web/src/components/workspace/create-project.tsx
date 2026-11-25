"use client";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { Dialog } from "@/components/ui/dialog";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { safeGitHubRepoUrl } from "@/lib/security";
import { useWorkspace } from "./context";
import { useAction } from "./use-action";

export function NewProjectButton({ className = "button-primary" }: { className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>
        <Plus size={16} aria-hidden="true" /> New project
      </button>
      {open && <CreateProjectDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function CreateProjectDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const { refresh } = useWorkspace();
  const { busy, problem, run } = useAction("create-project");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [urlInvalid, setUrlInvalid] = useState(false);
  const titleId = useId();
  const descriptionId = useId();
  const urlHintId = useId();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const locator = url.trim();
    // Defence in depth: the API validates too, but an obviously wrong URL never leaves here.
    if (!safeGitHubRepoUrl(locator)) {
      setUrlInvalid(true);
      return;
    }
    setUrlInvalid(false);
    const created = await run(() =>
      api("/projects", {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), repository_url: locator }),
      }),
    );
    if (!created) return;
    await refresh();
    onClose();
    router.push("/projects");
  }

  return (
    <Dialog
      labelledBy={titleId}
      describedBy={descriptionId}
      onClose={onClose}
      dismissible={!busy}
    >
      <h2 id={titleId}>Add a project</h2>
      <p id={descriptionId} className="dialog-description">
        Save a public GitHub repository to your workspace. Nothing is downloaded or analysed
        until you start a job.
      </p>
      <form className="dialog-body" onSubmit={(event) => void submit(event)} noValidate>
        <div className="field">
          <label htmlFor="project-title">Project name</label>
          <input
            id="project-title"
            type="text"
            className="input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={100}
            required
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="repository-url">GitHub repository URL</label>
          <input
            id="repository-url"
            type="url"
            className="input"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
              setUrlInvalid(false);
            }}
            placeholder="https://github.com/owner/repository"
            maxLength={250}
            required
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={urlInvalid || undefined}
            aria-describedby={urlHintId}
          />
          <small id={urlHintId} className="field-hint">
            {urlInvalid
              ? describeError(422, "invalid_repository_url")
              : "A canonical public repository URL, for example https://github.com/owner/repository."}
          </small>
        </div>
        {problem && <ProblemNotice problem={problem} />}
        <div className="dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            className="button-primary"
            disabled={busy || !title.trim() || !url.trim()}
            type="submit"
          >
            {busy ? "Saving…" : "Create project"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
