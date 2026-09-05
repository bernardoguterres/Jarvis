import { useState } from "react";
import { createMissionFocusPin, unpinMissionFocusPin, type MissionFocusPin, type MissionFocusSourceType } from "../api";

interface AddToMissionFocusButtonProps {
  sourceType: MissionFocusSourceType;
  sourceId: string;
  /** The matching active pin, if the caller's own already-fetched pin
   * list contains one for this exact source — never re-derived here, so
   * every eligible-source screen shares one source of truth (`GET
   * /api/mission-focus`) rather than each button polling independently. */
  existingPin?: MissionFocusPin;
  /** Called after a successful pin/unpin so the parent can refetch its
   * own pin list — this component never caches pin state itself. */
  onChanged: () => void;
}

/** A restrained, single-purpose control for eligible source screens
 * (DomainView's structured records, Actions Centre's proposals,
 * Integrations Centre's Calendar events) — never a large form, never
 * editable beyond Mission Focus's own metadata, and truthful about the
 * 5-pin limit rather than silently replacing another pin. */
function AddToMissionFocusButton({ sourceType, sourceId, existingPin, onChanged }: AddToMissionFocusButtonProps) {
  const [expanded, setExpanded] = useState(false);
  const [nextAction, setNextAction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (existingPin) {
    return (
      <span className="mission-focus-pin-state">
        <span className="pinned-badge" title={`Mission Focus #${existingPin.rank}`}>
          PINNED #{existingPin.rank}
        </span>
        <button
          type="button"
          className="briefing-item-control"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await unpinMissionFocusPin(existingPin.id);
              onChanged();
            } catch {
              setError("Could not remove this pin.");
            } finally {
              setBusy(false);
            }
          }}
        >
          Remove from focus
        </button>
        {error && <span className="error-banner">{error}</span>}
      </span>
    );
  }

  if (!expanded) {
    return (
      <button type="button" className="briefing-item-control action-note" onClick={() => setExpanded(true)}>
        Add to Mission Focus
      </button>
    );
  }

  return (
    <form
      className="mission-focus-add-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!nextAction.trim()) {
          setError("A next action is required.");
          return;
        }
        setBusy(true);
        setError(null);
        try {
          await createMissionFocusPin({ source_type: sourceType, source_id: sourceId, next_action: nextAction.trim() });
          setExpanded(false);
          setNextAction("");
          onChanged();
        } catch (err) {
          setError(err instanceof Error ? err.message : "Could not pin this item — Mission Focus may already be full.");
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        Next action
        <input
          type="text"
          value={nextAction}
          onChange={(e) => setNextAction(e.target.value)}
          placeholder="What's the next concrete step?"
          maxLength={300}
        />
      </label>
      <span className="mission-focus-add-actions">
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Pinning…" : "Pin to Mission Focus"}
        </button>
        <button type="button" onClick={() => setExpanded(false)} disabled={busy}>
          Cancel
        </button>
      </span>
      {error && <p className="error-banner">{error}</p>}
    </form>
  );
}

export default AddToMissionFocusButton;
