import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "../src/components/ui/confirm-dialog";

function Harness({ onConfirm = vi.fn() }: { onConfirm?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Delete project
      </button>
      <button type="button">Elsewhere</button>
      {open && (
        <ConfirmDialog
          title="Delete this project?"
          description={<p>This cannot be undone.</p>}
          confirmLabel="Delete project"
          onConfirm={() => {
            onConfirm();
            setOpen(false);
          }}
          onCancel={() => setOpen(false)}
        />
      )}
    </>
  );
}

describe("ConfirmDialog", () => {
  it("is a labelled, described modal alert dialog that starts on Cancel", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete this project?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("This cannot be undone.");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("closes on Escape and returns focus to the control that opened it", async () => {
    const confirm = vi.fn();
    render(<Harness onConfirm={confirm} />);
    const trigger = screen.getByRole("button", { name: "Delete project" });
    await userEvent.click(trigger);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("traps Tab and Shift+Tab inside the dialog", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Delete project" }));
    const dialog = screen.getByRole("alertdialog");
    const cancel = screen.getByRole("button", { name: "Cancel" });
    const confirm = dialog.querySelector("button.button-danger") as HTMLElement;
    await userEvent.tab();
    expect(confirm).toHaveFocus();
    await userEvent.tab();
    expect(cancel).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(confirm).toHaveFocus();
    expect(screen.getByRole("button", { name: "Elsewhere" })).not.toHaveFocus();
  });

  it("confirms only through its own button and never uses window.confirm", async () => {
    const native = vi.spyOn(window, "confirm");
    const confirm = vi.fn();
    render(<Harness onConfirm={confirm} />);
    const trigger = screen.getByRole("button", { name: "Delete project" });
    await userEvent.click(trigger);
    const dialog = screen.getByRole("alertdialog");
    await userEvent.click(dialog.querySelector("button.button-danger") as HTMLElement);
    expect(confirm).toHaveBeenCalledOnce();
    expect(native).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    native.mockRestore();
  });

  it("cannot be dismissed while its action is running", async () => {
    const cancel = vi.fn();
    render(
      <ConfirmDialog
        title="Delete this project?"
        description="Removing…"
        confirmLabel="Delete project"
        busyLabel="Deleting…"
        busy
        onConfirm={vi.fn()}
        onCancel={cancel}
      />,
    );
    await userEvent.keyboard("{Escape}");
    expect(cancel).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Deleting…" })).toBeDisabled();
  });
});
