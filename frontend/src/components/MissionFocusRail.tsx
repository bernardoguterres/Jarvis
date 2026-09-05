import type { MissionFocusEntry } from "../api";
import { CHANGE_LABEL } from "./changeState";
import { formatDateTime } from "../formatDateTime";

interface MissionFocusRailProps {
  entries: MissionFocusEntry[];
  defaultVisible: number;
  maxActivePins: number;
  loading: boolean;
  error: string | null;
  onViewSource: (entry: MissionFocusEntry) => void;
  onRemove: (pinId: string) => void;
  onDiscuss: () => void;
  discussing: boolean;
  discussReply: string | null;
  discussError: string | null;
  /** The pin currently mid-remove, so only its own row disables. */
  busyPinId?: string | null;
}

function formatTarget(iso: string | null): string | null {
  if (!iso) return null;
  try {
    return formatDateTime(iso);
  } catch {
    return iso;
  }
}

function MissionFocusRow({
  entry,
  onViewSource,
  onRemove,
  busy,
}: {
  entry: MissionFocusEntry;
  onViewSource: (entry: MissionFocusEntry) => void;
  onRemove: (pinId: string) => void;
  busy: boolean;
}) {
  const target = formatTarget(entry.target_at);
  return (
    <li className="mission-focus-row">
      <span className="mission-focus-rank" aria-hidden="true">
        #{entry.rank}
      </span>
      <span className="mission-focus-body">
        <span className="mission-focus-title-line">
          <span className="mission-focus-title">{entry.title}</span>
          {entry.change_state && (
            <span className={`change-badge state-${entry.change_state}`}>{CHANGE_LABEL[entry.change_state]}</span>
          )}
        </span>
        <span className="mission-focus-next-action">{entry.next_action}</span>
        <span className="mission-focus-meta">
          {entry.domain_slug && <span className="mission-focus-domain">{entry.domain_slug.toUpperCase()}</span>}
          {target && <span>Target: {target}</span>}
          {entry.blocker && <span className="mission-focus-blocker">Blocked: {entry.blocker}</span>}
          {!entry.available && <span className="mission-focus-unavailable">Source unavailable</span>}
          {entry.available && entry.resolved && <span className="mission-focus-resolved">Source resolved</span>}
        </span>
      </span>
      <span className="mission-focus-actions">
        <button
          type="button"
          className="briefing-item-control"
          onClick={() => onViewSource(entry)}
          disabled={!entry.link_target}
        >
          View source
        </button>
        <button type="button" className="briefing-item-control" onClick={() => onRemove(entry.pin_id)} disabled={busy}>
          Remove from focus
        </button>
      </span>
    </li>
  );
}

/** Mission Focus (Phase 12C) — a small, deliberate, Bernardo-owned
 * watchlist, rendered as a compact ledger beside the situational
 * briefing rather than a generic grid of cards. The default view shows
 * only the top-ranked entries (`defaultVisible`, normally 3); the
 * remainder sit behind a closed-by-default disclosure so Home never
 * feels cluttered even at the full 5-pin limit. Every pin references a
 * real existing source — this component never invents or copies
 * content, only displays what the backend already resolved. */
function MissionFocusRail({
  entries,
  defaultVisible,
  maxActivePins,
  loading,
  error,
  onViewSource,
  onRemove,
  onDiscuss,
  discussing,
  discussReply,
  discussError,
  busyPinId = null,
}: MissionFocusRailProps) {
  const primary = entries.slice(0, defaultVisible);
  const rest = entries.slice(defaultVisible);

  return (
    <section className="mission-focus-rail" aria-label="Mission Focus">
      <div className="briefing-strip-head">
        <span className="briefing-strip-title">
          Mission Focus ({entries.length}/{maxActivePins})
        </span>
        <span className="briefing-strip-actions">
          <button
            type="button"
            className="briefing-strip-button action-note"
            onClick={onDiscuss}
            disabled={entries.length === 0 || discussing}
          >
            {discussing ? "Asking Jarvis…" : "Discuss Mission Focus with Jarvis"}
          </button>
        </span>
      </div>

      {error && (
        <p className="briefing-strip-error" role="alert">
          {error}
        </p>
      )}
      {!error && !loading && entries.length === 0 && (
        <p className="briefing-strip-empty">No pins yet — add one from LIFE, PATH, BUILD, Calendar, or Actions.</p>
      )}

      {primary.length > 0 && (
        <ul className="mission-focus-list">
          {primary.map((entry) => (
            <MissionFocusRow key={entry.pin_id} entry={entry} onViewSource={onViewSource} onRemove={onRemove} busy={busyPinId === entry.pin_id} />
          ))}
        </ul>
      )}

      {rest.length > 0 && (
        <details className="briefing-history">
          <summary>{rest.length} more pinned</summary>
          <ul className="mission-focus-list">
            {rest.map((entry) => (
              <MissionFocusRow key={entry.pin_id} entry={entry} onViewSource={onViewSource} onRemove={onRemove} busy={busyPinId === entry.pin_id} />
            ))}
          </ul>
        </details>
      )}

      {discussError && (
        <p className="briefing-strip-error" role="alert">
          {discussError}
        </p>
      )}
      {discussReply && (
        <p className="briefing-strip-reply">
          <strong>Jarvis (model response):</strong> {discussReply}
        </p>
      )}
    </section>
  );
}

export default MissionFocusRail;
