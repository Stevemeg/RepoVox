"use client";
import { useEffect, useState } from "react";

/**
 * The current time, refreshed every `intervalMs` while `enabled`. It drives the expiry
 * countdown only: no request is made, so it keeps ticking in a hidden tab, and a video turns
 * "Expired" on time even when the page has been left open.
 */
export function useNow(intervalMs: number, enabled = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return;
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs, enabled]);
  return now;
}
