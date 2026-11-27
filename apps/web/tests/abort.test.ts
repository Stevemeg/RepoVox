import { describe, expect, it, vi } from "vitest";
import { linkAbort } from "../src/lib/abort";

describe("linkAbort", () => {
  it("aborts when any parent aborts, with a standard AbortError reason", () => {
    const session = new AbortController();
    const owner = new AbortController();
    const link = linkAbort(session.signal, owner.signal);
    expect(link.signal.aborted).toBe(false);
    session.abort();
    expect(link.signal.aborted).toBe(true);
    expect((link.signal.reason as DOMException).name).toBe("AbortError");
    expect(owner.signal.aborted).toBe(false);
  });

  it("aborts locally without aborting any parent", () => {
    const session = new AbortController();
    const link = linkAbort(session.signal);
    link.abort();
    expect(link.signal.aborted).toBe(true);
    expect(session.signal.aborted).toBe(false);
  });

  it("starts aborted, adding no listener, when a parent has already aborted", () => {
    const session = new AbortController();
    session.abort();
    const add = vi.spyOn(session.signal, "addEventListener");
    const link = linkAbort(session.signal);
    expect(link.signal.aborted).toBe(true);
    expect(add).not.toHaveBeenCalled();
  });

  it("removes its listener from every parent on release, so a later abort no longer reaches it", () => {
    const session = new AbortController();
    const owner = new AbortController();
    const removeSession = vi.spyOn(session.signal, "removeEventListener");
    const removeOwner = vi.spyOn(owner.signal, "removeEventListener");
    const link = linkAbort(session.signal, owner.signal);
    link.release();
    expect(removeSession).toHaveBeenCalledOnce();
    expect(removeOwner).toHaveBeenCalledOnce();
    session.abort();
    expect(link.signal.aborted).toBe(false);
  });

  it("does not collect listeners on a long-lived session signal across many settled requests", () => {
    const session = new AbortController();
    const add = vi.spyOn(session.signal, "addEventListener");
    const remove = vi.spyOn(session.signal, "removeEventListener");
    for (let index = 0; index < 50; index += 1) {
      const link = linkAbort(session.signal);
      if (index % 2) link.abort();
      else link.release();
    }
    expect(add).toHaveBeenCalledTimes(50);
    expect(remove).toHaveBeenCalledTimes(50);
  });

  it("ignores missing parents", () => {
    const link = linkAbort(undefined, null);
    expect(link.signal.aborted).toBe(false);
    link.abort();
    expect(link.signal.aborted).toBe(true);
  });
});
