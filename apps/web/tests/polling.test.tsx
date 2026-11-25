import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVisibilityPolling } from "../src/lib/use-visibility-polling";

let hidden = false;
function setHidden(value: boolean) {
  hidden = value;
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

beforeEach(() => {
  hidden = false;
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  delete (document as { hidden?: boolean }).hidden;
});

describe("useVisibilityPolling", () => {
  it("polls on the interval while the tab is visible", async () => {
    const poll = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useVisibilityPolling(poll, 1000));
    expect(poll).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(poll).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(poll).toHaveBeenCalledTimes(3);
  });

  it("pauses immediately when document.hidden becomes true", async () => {
    const poll = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useVisibilityPolling(poll, 1000));
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(poll).toHaveBeenCalledTimes(1);
    setHidden(true);
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(poll).toHaveBeenCalledTimes(1);
  });

  it("refreshes at once on becoming visible, then resumes the interval", async () => {
    const poll = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useVisibilityPolling(poll, 1000));
    setHidden(true);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(poll).not.toHaveBeenCalled();
    setHidden(false);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(poll).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it("does not start while the page is hidden at mount", async () => {
    hidden = true;
    const poll = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useVisibilityPolling(poll, 1000));
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(poll).not.toHaveBeenCalled();
  });

  it("never overlaps a slow poll with the next one", async () => {
    let finish: () => void = () => {};
    const poll = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    renderHook(() => useVisibilityPolling(poll, 1000));
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(poll).toHaveBeenCalledTimes(1);
    await act(async () => finish());
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it("stops when disabled and on unmount", async () => {
    const poll = vi.fn().mockResolvedValue(undefined);
    const { rerender, unmount } = renderHook(
      ({ enabled }) => useVisibilityPolling(poll, 1000, enabled),
      { initialProps: { enabled: false } },
    );
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(poll).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(poll).toHaveBeenCalledTimes(1);
    unmount();
    setHidden(true);
    setHidden(false);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(poll).toHaveBeenCalledTimes(1);
  });

  it("keeps polling after a failed poll", async () => {
    const poll = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
    renderHook(() => useVisibilityPolling(poll, 1000));
    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(poll).toHaveBeenCalledTimes(2);
  });
});
