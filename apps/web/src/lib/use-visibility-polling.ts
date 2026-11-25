"use client";
import { useEffect, useRef } from "react";

/**
 * Calls `poll` every `intervalMs` while `enabled` and the tab is visible.
 *
 * - Pauses immediately when `document.hidden` becomes true; no request is made from a
 *   hidden tab.
 * - On becoming visible again it refreshes once immediately, then resumes the interval.
 * - Never overlaps: the next tick is scheduled only after the previous poll settles, so a
 *   slow API cannot pile up concurrent requests.
 *
 * Polling only refreshes the display. Jobs advance on the server whether or not a page is
 * open. The initial load is the caller's own effect; this hook schedules the refreshes.
 */
export function useVisibilityPolling(
  poll: () => unknown,
  intervalMs: number,
  enabled = true,
): void {
  const latest = useRef(poll);
  useEffect(() => {
    latest.current = poll;
  });

  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let running = false;
    let stopped = false;

    const clear = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
    };
    const schedule = () => {
      clear();
      if (!stopped && !document.hidden) timer = setTimeout(tick, intervalMs);
    };
    async function tick() {
      timer = undefined;
      if (stopped || document.hidden || running) return;
      running = true;
      try {
        await latest.current();
      } catch {
        // The caller reports its own errors; polling simply continues.
      } finally {
        running = false;
        schedule();
      }
    }
    const onVisibilityChange = () => {
      if (document.hidden) clear();
      else if (!running) void tick();
    };

    schedule();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      stopped = true;
      clear();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [enabled, intervalMs]);
}
