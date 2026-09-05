import { DiagnosticCore } from "./Diagnostic";

interface ModelLinkBannerProps {
  onRetry: () => void;
  retrying?: boolean;
  /** Shown only where dismissing genuinely means "keep using Jarvis
   * without the model right now" — Home. */
  onDismiss?: () => void;
  /** Shown only in a conversation composer, where saving a note is a real
   * available action. */
  onSaveAsNote?: () => void;
}

/** Hermes/model gateway unavailable while the local controller stays up —
 * deliberately never a full-page takeover. Amber, not red: local notes,
 * memories, records, and saved data all remain available; only model
 * responses and spoken replies are affected. The outer ring stays a
 * healthy, intact rotation (the controller link is fine) — only the
 * inner "cognitive" ring is shown interrupted. */
function ModelLinkBanner({ onRetry, retrying = false, onDismiss, onSaveAsNote }: ModelLinkBannerProps) {
  return (
    <div className="model-link-banner" role="status">
      <DiagnosticCore tone="degraded" variant="dual" scanning={retrying} />
      <div className="model-link-banner-text">
        <div className="model-link-banner-heading">Model link unavailable</div>
        <p className="model-link-banner-body">
          Local notes, memories, records and saved data remain available. Model responses and spoken
          replies are temporarily unavailable.
        </p>
      </div>
      <div className="model-link-banner-actions">
        <button type="button" onClick={onRetry} disabled={retrying}>
          {retrying ? "Retrying…" : "Retry model connection"}
        </button>
        {onSaveAsNote && (
          <button type="button" onClick={onSaveAsNote}>
            Save as note
          </button>
        )}
        {onDismiss && (
          <button type="button" onClick={onDismiss}>
            Continue without model
          </button>
        )}
      </div>
    </div>
  );
}

export default ModelLinkBanner;
