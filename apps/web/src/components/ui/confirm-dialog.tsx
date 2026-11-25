"use client";
import { useId, type ReactNode } from "react";
import type { Problem } from "@/lib/errors";
import { Dialog } from "./dialog";
import { ProblemNotice } from "./problem-notice";

/**
 * An accessible replacement for the browser's native confirm prompt: an `alertdialog` with a labelled title,
 * a described consequence, focus starting on Cancel, Escape to cancel, and focus returned
 * to the control that opened it.
 */
export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  busyLabel,
  cancelLabel = "Cancel",
  tone = "danger",
  busy = false,
  problem,
  onConfirm,
  onCancel,
}: {
  title: string;
  description: ReactNode;
  confirmLabel: string;
  busyLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "primary";
  busy?: boolean;
  problem?: Problem | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  return (
    <Dialog
      role="alertdialog"
      labelledBy={titleId}
      describedBy={descriptionId}
      onClose={onCancel}
      dismissible={!busy}
    >
      <h2 id={titleId}>{title}</h2>
      <div id={descriptionId} className="dialog-description">
        {description}
      </div>
      {problem && (
        <div className="dialog-body">
          <ProblemNotice problem={problem} />
        </div>
      )}
      <div className="dialog-actions">
        <button type="button" data-autofocus onClick={onCancel} disabled={busy}>
          {cancelLabel}
        </button>
        <button
          type="button"
          className={tone === "danger" ? "button-danger" : "button-primary"}
          onClick={onConfirm}
          disabled={busy}
        >
          {busy ? (busyLabel ?? confirmLabel) : confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}
