/*
 * Request cancellation shared by a request's owner and the signed-in session.
 *
 * A workspace read is cancelled by whichever comes first: its own owner (unmounting, or a
 * newer load replacing it) or the session ending (sign-out aborts the session signal
 * before the sign-out request is sent). Written with plain event listeners rather than
 * `AbortSignal.any`, so it behaves the same in every browser and in jsdom, and so the
 * listeners it adds to a long-lived session signal are removed as soon as each request
 * settles instead of accumulating with every poll.
 */

export type AbortLink = {
  /** Aborts when `abort()` is called or when any parent signal aborts. */
  readonly signal: AbortSignal;
  /** Cancels this request only. The parents are never aborted from here. */
  abort: () => void;
  /** Detaches from the parents without aborting. Call once the request has settled. */
  release: () => void;
};

/**
 * A new abortable scope linked to `parents`. Missing parents are ignored. When a parent has
 * already aborted, the returned signal starts aborted, so no request should be sent with
 * it. The signal's reason is always a standard `AbortError`, which `api()` rethrows as is.
 */
export function linkAbort(...parents: readonly (AbortSignal | null | undefined)[]): AbortLink {
  const controller = new AbortController();
  const detach: (() => void)[] = [];
  const release = () => {
    for (const remove of detach.splice(0)) remove();
  };
  const abort = () => {
    release();
    controller.abort();
  };
  for (const parent of parents) {
    if (!parent) continue;
    if (parent.aborted) {
      abort();
      break;
    }
    parent.addEventListener("abort", abort, { once: true });
    detach.push(() => parent.removeEventListener("abort", abort));
  }
  return { signal: controller.signal, abort, release };
}
