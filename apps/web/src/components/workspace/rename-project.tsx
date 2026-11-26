"use client";
import { useId, useRef, useState, type FormEvent } from "react";
import { Dialog } from "@/components/ui/dialog";
import { ProblemNotice } from "@/components/ui/problem-notice";
import { api, type Project } from "@/lib/api";
import { useAction } from "./use-action";

/** The API's `ProjectUpdate.title` bound, counted in characters after trimming. */
export const TITLE_MAX = 100;
// The API refuses a title containing any character below U+0020 (line breaks, tabs ...).
const hasControl = (value: string) => [...value].some((char) => char.charCodeAt(0) < 0x20);

/**
 * Why `raw` is not an acceptable project name, or null when it is. Mirrors the API's
 * `ProjectUpdate` validation so an obviously invalid name never leaves the browser; the API
 * still validates independently.
 */
export function titleProblem(raw: string): string | null {
  const title = raw.trim();
  if (!title) return "Enter a project name.";
  if ([...title].length > TITLE_MAX)
    return `Use at most ${TITLE_MAX} characters for the project name.`;
  if (hasControl(title)) return "Remove line breaks, tabs and other control characters.";
  return null;
}

/** Rename a project with `PATCH /projects/{id}`; focus returns to the opener on close. */
export function RenameProjectDialog({
  project,
  onClose,
  onRenamed,
}: {
  project: Project;
  onClose: () => void;
  onRenamed: (project: Project) => void;
}) {
  const { busy, problem, run } = useAction("rename-project");
  const [title, setTitle] = useState(project.title);
  const [invalid, setInvalid] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const hintId = useId();
  const unchanged = title.trim() === project.title;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const reason = titleProblem(title);
    if (reason) {
      setInvalid(reason);
      input.current?.focus();
      return;
    }
    if (unchanged) return;
    let updated: Project | undefined;
    const ok = await run(async () => {
      updated = await api<Project>(`/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title: title.trim() }),
      });
    });
    if (ok && updated) onRenamed(updated);
  }

  return (
    <Dialog labelledBy={titleId} describedBy={descriptionId} onClose={onClose} dismissible={!busy}>
      <h2 id={titleId}>Rename project</h2>
      <p id={descriptionId} className="dialog-description">
        Only the name changes. The repository locator and every job stay as they are.
      </p>
      <form className="dialog-body" onSubmit={(event) => void submit(event)} noValidate>
        <div className="field">
          <label htmlFor="rename-project-title">Project name</label>
          <input
            ref={input}
            id="rename-project-title"
            type="text"
            className="input"
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              setInvalid(null);
            }}
            onFocus={(event) => event.currentTarget.select()}
            maxLength={TITLE_MAX}
            required
            autoComplete="off"
            data-autofocus
            aria-invalid={invalid ? true : undefined}
            aria-describedby={hintId}
          />
          <small id={hintId} className="field-hint" data-invalid={invalid ? "true" : undefined}>
            {invalid ?? `1 to ${TITLE_MAX} characters.`}
          </small>
        </div>
        {problem && <ProblemNotice problem={problem} />}
        <div className="dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="button-primary" type="submit" disabled={busy || unchanged}>
            {busy ? "Saving…" : "Save name"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
