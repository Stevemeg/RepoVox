"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/**
 * A modal dialog rendered while mounted. It moves focus inside on open (to the first
 * `[data-autofocus]` element, else the first control), keeps Tab and Shift+Tab inside,
 * closes on Escape, and returns focus to the element that opened it.
 */
export function Dialog({
  labelledBy,
  describedBy,
  onClose,
  dismissible = true,
  role = "dialog",
  children,
}: {
  labelledBy: string;
  describedBy?: string;
  onClose: () => void;
  /** False while an action is in flight: Escape and the backdrop then do nothing. */
  dismissible?: boolean;
  role?: "dialog" | "alertdialog";
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  const canDismiss = useRef(dismissible);
  useEffect(() => {
    close.current = onClose;
    canDismiss.current = dismissible;
  });

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const returnTo =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusables = () =>
      Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
    (
      dialog.querySelector<HTMLElement>("[data-autofocus]") ??
      focusables()[0] ??
      dialog
    ).focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (canDismiss.current) close.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const items = focusables();
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = overflow;
      if (returnTo?.isConnected) returnTo.focus();
    };
  }, []);

  return createPortal(
    <div
      className="dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && canDismiss.current) close.current();
      }}
    >
      <div
        ref={ref}
        className="dialog"
        role={role}
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
