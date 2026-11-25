"use client";
import { useMemo, useRef } from "react";

export const newIdempotencyKey = (): string => crypto.randomUUID();

export type IdempotencyKey = {
  /** The key for the current submission, created on first use. */
  current: () => string;
  /** Start a new submission: the next `current()` returns a fresh key. */
  rotate: () => void;
};

/**
 * One stable `Idempotency-Key` per submission. Retrying the same action (after a timeout,
 * a dropped connection or a temporary error) reuses the key, so the API returns the job it
 * already admitted instead of creating a second one. Call `rotate()` only after the
 * submission succeeds, or when the user deliberately starts a new one.
 */
export function useIdempotencyKey(): IdempotencyKey {
  const key = useRef<string | null>(null);
  return useMemo(
    () => ({
      current: () => (key.current ??= newIdempotencyKey()),
      rotate: () => {
        key.current = null;
      },
    }),
    [],
  );
}
