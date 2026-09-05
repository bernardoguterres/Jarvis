import { useEffect } from "react";
import { createPortal } from "react-dom";

interface ConfirmDialogProps {
  heading: string;
  warning: string;
  busy?: boolean;
  /** "danger" gets a red accent border/glow — reserved for an action that
   * actually severs a connection or otherwise can't be trivially undone,
   * never applied just to make a dialog look more serious. */
  tone?: "default" | "danger";
  onConfirm: () => void;
  onCancel: () => void;
}

/** A real confirmation gate (CLAUDE.md §12 "Confirm" tier) for a
 * consequential local configuration change named by a typed or spoken
 * command (disconnect an integration, export data, etc.) — the command
 * registry only ever identifies *which* action was requested; nothing
 * executes until a person explicitly accepts it here. */
function ConfirmDialog({ heading, warning, busy = false, tone = "default", onConfirm, onCancel }: ConfirmDialogProps) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return createPortal(
    <div className="confirm-dialog-overlay" role="presentation" onClick={onCancel}>
      <div
        className={`confirm-dialog${tone === "danger" ? " tone-danger" : ""}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-heading"
        aria-describedby="confirm-dialog-warning"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-dialog-heading">{heading}</h2>
        <p id="confirm-dialog-warning">{warning}</p>
        <div className="confirm-dialog-actions">
          <button
            type="button"
            className={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            disabled={busy}
            autoFocus
          >
            {busy ? "Working…" : "Confirm"}
          </button>
          <button type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default ConfirmDialog;
