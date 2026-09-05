import type { BriefingAcknowledgedOrSnoozedEntry, BriefingItem, BriefingSnoozeDuration, HomeBriefing } from "../api";
import { CHANGE_LABEL } from "./changeState";
import { formatDateTime } from "../formatDateTime";

interface BriefingStripProps {
  briefing: HomeBriefing | null;
  loading: boolean;
  error: string | null;
  onSelectItem: (item: BriefingItem) => void;
  onRefresh: () => void;
  onDiscuss: () => void;
  discussing: boolean;
  discussError: string | null;
  discussReply: string | null;
  onReadAloud?: () => void;
  reading?: boolean;
  onAcknowledge: (stableKey: string) => void;
  onSnooze: (stableKey: string, duration: BriefingSnoozeDuration) => void;
  onRestore: (stableKey: string) => void;
  /** The stable_key currently mid-action (acknowledge/snooze/restore),
   * so its controls disable rather than allow a double-submit — never a
   * global loading flag, so unrelated rows stay interactive. */
  busyKey?: string | null;
  actionError?: string | null;
}

const CATEGORY_LABEL: Record<string, string> = { now: "NOW", next: "NEXT", watch: "WATCH" };
const SNOOZE_OPTIONS: { duration: BriefingSnoozeDuration; label: string }[] = [
  { duration: "1h", label: "1 hour" },
  { duration: "4h", label: "4 hours" },
  { duration: "tomorrow_morning", label: "Until tomorrow morning" },
  { duration: "1w", label: "1 week" },
];

function formatSince(iso: string): string {
  try {
    return formatDateTime(iso);
  } catch {
    return iso;
  }
}

/** The compact, real-state-only "mission strip" version of a situational
 * briefing (Phase 12A/12B) — deliberately not another generic rounded
 * card full of bullet points (CLAUDE.md's frontend aesthetics doctrine).
 * Every item here comes straight from the backend's deterministic
 * assembler (app/briefing_service.py) with real provenance and a real
 * change-state classification; nothing is invented, decorative, or
 * computed client-side. Acknowledge/snooze only ever change what this
 * strip shows — never the underlying Calendar/task/action/integration/
 * routine/Health record itself. */
function BriefingStrip({
  briefing,
  loading,
  error,
  onSelectItem,
  onRefresh,
  onDiscuss,
  discussing,
  discussError,
  discussReply,
  onReadAloud,
  reading = false,
  onAcknowledge,
  onSnooze,
  onRestore,
  busyKey = null,
  actionError = null,
}: BriefingStripProps) {
  const items = briefing?.items ?? [];
  const hasItems = items.length > 0;
  const unavailableSources = briefing?.sources?.filter((s) => s.status === "unavailable") ?? [];
  const history = briefing?.acknowledged_and_snoozed ?? [];

  return (
    <section className="briefing-strip" aria-label="Situational briefing">
      <div className="briefing-strip-head">
        <span className="briefing-strip-title">Situational briefing</span>
        <span className="briefing-strip-actions">
          <button type="button" className="briefing-strip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          {onReadAloud && (
            <button
              type="button"
              className="briefing-strip-button"
              onClick={onReadAloud}
              disabled={!hasItems || reading}
            >
              {reading ? "Reading…" : "Read aloud"}
            </button>
          )}
          <button
            type="button"
            className="briefing-strip-button action-note"
            onClick={onDiscuss}
            disabled={!hasItems || discussing}
          >
            {discussing ? "Asking Jarvis…" : "Discuss with Jarvis"}
          </button>
        </span>
      </div>

      <div aria-live="polite">
        {error && (
          <p className="briefing-strip-error" role="alert">
            {error}
          </p>
        )}
        {!error && briefing && !hasItems && <p className="briefing-strip-empty">No immediate items.</p>}
      </div>

      {!error && hasItems && (
        <ul className="briefing-strip-list">
          {items.map((item) => {
            const isBusy = busyKey === item.id;
            const isResolved = item.change_state === "resolved";
            return (
              <li key={item.id} className="briefing-item-row">
                <button
                  type="button"
                  className={`briefing-item tone-${item.tone}`}
                  onClick={() => onSelectItem(item)}
                  disabled={!item.link_target}
                >
                  <span className={`briefing-item-category cat-${item.category}`}>{CATEGORY_LABEL[item.category]}</span>
                  <span className={`change-badge state-${item.change_state}`}>{CHANGE_LABEL[item.change_state]}</span>
                  {item.pinned && (
                    <span className="pinned-badge" title={`Mission Focus #${item.pin_rank}`}>
                      PINNED
                    </span>
                  )}
                  <span className="briefing-item-body">
                    <span className="briefing-item-title">{item.title}</span>
                    {item.subtitle && <span className="briefing-item-subtitle">{item.subtitle}</span>}
                  </span>
                  {(item.freshness === "stale" || item.freshness === "unavailable") && (
                    <span className="briefing-item-freshness">{item.freshness}</span>
                  )}
                </button>
                {!isResolved && (
                  <span className="briefing-item-controls">
                    <button
                      type="button"
                      className="briefing-item-control"
                      onClick={() => onAcknowledge(item.id)}
                      disabled={isBusy}
                      title="Hide this version from the briefing — never marks the underlying item complete."
                    >
                      Acknowledge
                    </button>
                    <details className="snooze-menu">
                      <summary className="briefing-item-control">Snooze</summary>
                      <div className="snooze-menu-options" role="group" aria-label={`Snooze duration for ${item.title}`}>
                        {SNOOZE_OPTIONS.map((opt) => (
                          <button
                            key={opt.duration}
                            type="button"
                            disabled={isBusy}
                            onClick={(e) => {
                              // Close the native disclosure before firing —
                              // otherwise it stays open over the next render.
                              (e.currentTarget.closest("details") as HTMLDetailsElement | null)?.removeAttribute("open");
                              onSnooze(item.id, opt.duration);
                            }}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </details>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {actionError && (
        <p className="briefing-strip-error" role="alert">
          {actionError}
        </p>
      )}

      {unavailableSources.length > 0 && (
        <p className="briefing-strip-note">
          Some sources are unavailable right now ({unavailableSources.map((s) => s.source_type).join(", ")}) — see
          Integrations Centre.
        </p>
      )}

      {history.length > 0 && (
        <details className="briefing-history">
          <summary>Acknowledged &amp; snoozed ({history.length})</summary>
          <ul className="briefing-history-list">
            {history.map((entry: BriefingAcknowledgedOrSnoozedEntry) => (
              <li key={`${entry.kind}:${entry.stable_key}`} className="briefing-history-row">
                <span className={`change-badge state-${entry.kind === "acknowledged" ? "ongoing" : "changed"}`}>
                  {entry.kind === "acknowledged" ? "ACKNOWLEDGED" : "SNOOZED"}
                </span>
                <span className="briefing-history-text">
                  <span className="briefing-item-title">{entry.title}</span>
                  <span className="briefing-item-subtitle">
                    {entry.kind === "acknowledged"
                      ? `Hidden since ${formatSince(entry.since)}`
                      : `Hidden until ${entry.until ? formatSince(entry.until) : "?"}`}
                  </span>
                </span>
                <button type="button" className="briefing-item-control" onClick={() => onRestore(entry.stable_key)}>
                  Restore
                </button>
              </li>
            ))}
          </ul>
          <p className="briefing-strip-note">
            Acknowledging or snoozing only changes what this briefing shows — it never modifies the underlying
            Calendar event, task, action, integration, routine, or Health data.
          </p>
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

export default BriefingStrip;
