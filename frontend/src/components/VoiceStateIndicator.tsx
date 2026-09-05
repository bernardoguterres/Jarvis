interface VoiceStateIndicatorProps {
  state: string;
}

/** Restyled wrapper around the existing voice-state text. Renders exactly
 * the same text content as before (tests match on the raw state word, e.g.
 * "listening") — this only adds a colored dot and container, driven by the
 * same real `state` value, never a decorative animation of its own. */
function VoiceStateIndicator({ state }: VoiceStateIndicatorProps) {
  if (state === "idle") {
    return (
      <span className="voice-state" aria-live="polite">
        {null}
      </span>
    );
  }
  return (
    <span className={`voice-state-indicator voice-${state}`}>
      <span className="voice-state-dot" aria-hidden="true" />
      <span className="voice-state" aria-live="polite">
        {state}
      </span>
    </span>
  );
}

export default VoiceStateIndicator;
