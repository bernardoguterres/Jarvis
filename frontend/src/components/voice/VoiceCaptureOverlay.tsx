import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import JarvisCore from "../JarvisCore";
import Waveform, { useWaveformBars } from "./Waveform";
import { useAudioLevels, type AudioLevelSource } from "../../hooks/useAudioLevels";
import { useReducedMotion } from "../../hooks/useReducedMotion";
import type { VoiceState } from "../../voiceState";

/** "cancelled" is a brief transient display state (not a real VoiceState —
 * callers flash it for ~500ms via handleCancel before settling to "idle")
 * purely so screen readers get the "Cancelled" announcement the spec
 * requires, without idle needing to become an announceable state. */
export type VoiceDisplayState = VoiceState | "cancelled";

interface VoiceCaptureOverlayProps {
  voiceState: VoiceDisplayState;
  /** "GENERAL", "BODY", "BUILD", "COMMAND", etc. — whichever surface
   * push-to-talk was started from. Never fabricated: the caller passes
   * the real active scope. */
  scope: string;
  /** The exact MediaStream push-to-talk already acquired — reused
   * directly, never a second getUserMedia call. */
  micStream: MediaStream | null;
  /** The exact <audio> element already playing synthesized speech —
   * reused directly, never a duplicate playback path. */
  ttsAudioElement: HTMLAudioElement | null;
  errorMessage?: string | null;
  /** Called when the viewer clicks/taps anywhere on the overlay while it is
   * showing "error" — the only state with nothing left to release into, so
   * it's the only state where this layer briefly accepts pointer events at
   * all (see the `state === "error"` guard on `pointer-events` below).
   * Every other state stays fully click-through, exactly as before, so a
   * push-to-talk release/cancel gesture always still reaches the real
   * control underneath. */
  onDismiss?: () => void;
}

const MICRO_LABEL: Record<VoiceDisplayState, string | null> = {
  idle: null,
  listening: "LISTENING",
  transcribing: "TRANSCRIBING LOCALLY",
  thinking: "THINKING",
  speaking: "JARVIS · SPEAKING",
  error: "VOICE ERROR",
  cancelled: "CANCELLED",
};

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/** A lightweight cinematic capture overlay, mounted over whatever page is
 * already showing (Home, a domain conversation, the general conversation,
 * or a Centre) — it never navigates away, never intercepts pointer events
 * (entirely `pointer-events: none`, so the release gesture that stops
 * recording always reaches the real push-to-talk control underneath,
 * for mouse, touch, and keyboard alike), and never causes the page to
 * scroll. Renders nothing at all in the "idle" state. */
function VoiceCaptureOverlay({ voiceState, scope, micStream, ttsAudioElement, errorMessage, onDismiss }: VoiceCaptureOverlayProps) {
  const reducedMotion = useReducedMotion();
  const { barRefs, gains } = useWaveformBars(9);
  const [elapsedMs, setElapsedMs] = useState(0);

  const isListening = voiceState === "listening";
  const isSpeaking = voiceState === "speaking";

  const micSource: AudioLevelSource | null = isListening && micStream ? { kind: "stream", stream: micStream } : null;
  const ttsSource: AudioLevelSource | null =
    isSpeaking && ttsAudioElement ? { kind: "element", element: ttsAudioElement } : null;

  const micLevels = useAudioLevels({
    source: micSource,
    barRefs,
    active: isListening,
    gains,
    reducedMotion,
    highlightStrongLevels: true,
  });
  const ttsLevels = useAudioLevels({
    source: ttsSource,
    barRefs,
    active: isSpeaking,
    gains,
    reducedMotion,
  });

  useEffect(() => {
    if (!isListening) {
      setElapsedMs(0);
      return;
    }
    const startedAt = Date.now();
    setElapsedMs(0);
    const interval = setInterval(() => setElapsedMs(Date.now() - startedAt), 250);
    return () => clearInterval(interval);
  }, [isListening]);

  if (voiceState === "idle") return null;

  const coreState = voiceState === "cancelled" ? "idle" : voiceState;
  const microLabel = MICRO_LABEL[voiceState];

  let waveformSlot: React.ReactNode = null;
  if (isListening) {
    waveformSlot = <Waveform barRefs={barRefs} tone="violet" fallback={!micLevels.supported} />;
  } else if (voiceState === "transcribing") {
    waveformSlot = <span className="voice-transcribe-scan" aria-hidden="true" />;
  } else if (isSpeaking) {
    waveformSlot = <Waveform barRefs={barRefs} tone="cyan" fallback={!ttsLevels.supported || !ttsAudioElement} />;
  }
  // "thinking" and "error" deliberately show no waveform at all — the
  // existing JarvisCore ring states carry those on their own.

  const announcement =
    voiceState === "error" && errorMessage ? `Voice error: ${errorMessage}` : microLabel ? `Jarvis: ${microLabel.toLowerCase()}` : "";

  const isError = voiceState === "error";

  return createPortal(
    <div
      className={`voice-capture-overlay state-${voiceState}${isError ? " is-dismissible" : ""}`}
      onClick={isError ? onDismiss : undefined}
    >
      <span className="voice-capture-scope">{scope}</span>
      <JarvisCore state={coreState} waveformSlot={waveformSlot ?? undefined} />
      <div className="voice-capture-text">
        {microLabel && <span className="voice-capture-label">{microLabel}</span>}
        {isListening && (
          <span className="voice-capture-mic-indicator">
            <span className="voice-capture-mic-dot" aria-hidden="true" />
            MIC ACTIVE
          </span>
        )}
        {isListening && (
          <>
            <span className="voice-capture-hint">Release to send</span>
            <span className="voice-capture-timer">{formatElapsed(elapsedMs)}</span>
          </>
        )}
        {isError && errorMessage && <span className="voice-capture-hint">{errorMessage}</span>}
        {isError && (
          <button
            type="button"
            className="voice-capture-dismiss-button"
            onClick={(event) => {
              // Redundant with the overlay's own click-anywhere-to-dismiss
              // above, deliberately: a real, focusable, unambiguous hit
              // target for anyone whose click on empty space didn't
              // register the way tapping a labeled button reliably does.
              event.stopPropagation();
              onDismiss?.();
            }}
          >
            Dismiss
          </button>
        )}
      </div>
      <span className="sr-only" role="status" aria-live="assertive">
        {announcement}
      </span>
    </div>,
    document.body,
  );
}

export default VoiceCaptureOverlay;
