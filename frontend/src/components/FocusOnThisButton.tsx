import { useState } from "react";
import { startMission, type FocusSessionSourceType } from "../api";

interface FocusOnThisButtonProps {
  sourceType: FocusSessionSourceType;
  sourceId: string;
  /** Default 25 minutes (the shortest Mission Control preset) — a domain
   * page's own "focus on this" is a quick single action, not the full
   * duration picker Home's Mission Control strip offers; a longer
   * session is always still available from Home once this one starts. */
  targetDurationMinutes?: number;
}

/** A lightweight per-record entry point into Mission Control (item 4 of
 * the spec: "starting a mission from ... a domain page"). Deliberately
 * doesn't duplicate Home's own candidate/duration UI — if a session is
 * already active or paused elsewhere, the backend's own 400 (see
 * app/mission_control_service.py's MissionControlError) is shown
 * verbatim rather than guessing what to do about it. */
function FocusOnThisButton({ sourceType, sourceId, targetDurationMinutes = 25 }: FocusOnThisButtonProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);

  if (started) {
    return <span className="mission-focus-resolved">Focus session started — see Home.</span>;
  }

  return (
    <span className="mission-focus-pin-state">
      <button
        type="button"
        className="briefing-item-control action-note"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await startMission({ source_type: sourceType, source_id: sourceId, target_duration_minutes: targetDurationMinutes });
            setStarted(true);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Could not start a focus session for this item.");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Starting…" : `Focus on this for ${targetDurationMinutes} min`}
      </button>
      {error && <span className="error-banner">{error}</span>}
    </span>
  );
}

export default FocusOnThisButton;
