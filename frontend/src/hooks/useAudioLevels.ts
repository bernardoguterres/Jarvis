import { useEffect, useRef, useState, type RefObject } from "react";

/** Real audio-reactive bar levels for the voice waveform (Phase 6). Two
 * genuine sources only — never a randomized/decorative substitute:
 *
 * - `{ kind: "stream", stream }`: the exact MediaStream push-to-talk
 *   already acquired via getUserMedia. Never requests permission again;
 *   never routes the microphone to speakers (the analyser tap has no
 *   output connection).
 * - `{ kind: "element", element }`: the exact <audio> element already
 *   playing synthesized speech. Reuses the existing audio element/blob —
 *   never a second copy, never duplicate playback. A `MediaElementAudioSourceNode`
 *   can only ever be created once per <audio> element for its lifetime
 *   (the browser throws on a second attempt even across a new
 *   AudioContext) — `elementGraphCache` remembers the one already made so
 *   repeated calls (one per assistant reply) reuse it instead of erroring.
 *
 * No amplitude/frequency sample is ever retained past the current
 * animation frame, nothing is uploaded, and no additional audio file is
 * ever written — this hook only ever reads live analyser data into DOM
 * transforms.
 */

export type AudioLevelSource = { kind: "stream"; stream: MediaStream } | { kind: "element"; element: HTMLAudioElement };

interface UseAudioLevelsOptions {
  source: AudioLevelSource | null;
  /** Refs to the bar elements to update directly via scaleY — updated
   * imperatively every animation frame, never through React state, so a
   * live waveform never forces a 60fps re-render. */
  barRefs: RefObject<HTMLDivElement | null>[];
  /** Only runs the analyser loop while true (e.g. the "listening" or
   * "speaking" state specifically) — never a background loop left running
   * through other states. */
  active: boolean;
  /** Center bars react more strongly than outer ones — one gain multiplier
   * per bar, same length as barRefs. */
  gains: number[];
  reducedMotion: boolean;
  /** Only the listening (violet) waveform gets a restrained cyan
   * highlight at stronger input levels — the speaking waveform is already
   * cyan throughout, so this stays off there. */
  highlightStrongLevels?: boolean;
}

const FFT_SIZE = 256;
const SMOOTHING_TIME_CONSTANT = 0.8;
const MIN_SCALE = 0.16;
const MAX_SCALE = 1;
const INTERPOLATION_ALPHA = 0.35;
const OVERALL_GAIN = 1.7;

interface ElementGraph {
  context: AudioContext;
  source: MediaElementAudioSourceNode;
}

// Keyed by the actual <audio> element so its one-time-only source node is
// created exactly once for the element's whole lifetime, then reused for
// every subsequent utterance play.
const elementGraphCache = new WeakMap<HTMLAudioElement, ElementGraph>();

function getOrCreateElementGraph(element: HTMLAudioElement): ElementGraph {
  const cached = elementGraphCache.get(element);
  if (cached) return cached;
  const context = new AudioContext();
  const source = context.createMediaElementSource(element);
  // Permanent — this is what keeps the element's audio actually audible.
  // The analyser tap below is a separate fan-out from this same source and
  // never needs its own connection to destination.
  source.connect(context.destination);
  const graph = { context, source };
  elementGraphCache.set(element, graph);
  return graph;
}

/** Returns whether the Web Audio analyser loop is genuinely active right
 * now — false means the caller should fall back to a restrained CSS
 * breathing waveform instead (Web Audio unavailable, or nothing to
 * analyze yet). */
const STRONG_LEVEL_THRESHOLD = 0.62;

export function useAudioLevels({
  source,
  barRefs,
  active,
  gains,
  reducedMotion,
  highlightStrongLevels = false,
}: UseAudioLevelsOptions): {
  supported: boolean;
} {
  const [supported, setSupported] = useState(true);
  const rafRef = useRef<number | null>(null);
  const displayedRef = useRef<number[]>(gains.map(() => MIN_SCALE));
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.AudioContext === "undefined") {
      setSupported(false);
      return;
    }
    if (!active || !source) return;

    let analyser: AnalyserNode | null = null;
    let ownContext: AudioContext | null = null;
    let micSource: MediaStreamAudioSourceNode | null = null;
    let cancelled = false;

    try {
      if (source.kind === "stream") {
        ownContext = new AudioContext();
        analyser = ownContext.createAnalyser();
        analyser.fftSize = FFT_SIZE;
        analyser.smoothingTimeConstant = SMOOTHING_TIME_CONSTANT;
        micSource = ownContext.createMediaStreamSource(source.stream);
        // Analysis only — deliberately never connected onward, so the
        // microphone is never routed to speakers.
        micSource.connect(analyser);
      } else {
        const graph = getOrCreateElementGraph(source.element);
        analyser = graph.context.createAnalyser();
        analyser.fftSize = FFT_SIZE;
        analyser.smoothingTimeConstant = SMOOTHING_TIME_CONSTANT;
        // A second fan-out from the same permanent source — does not
        // touch the existing source->destination connection, so playback
        // is unaffected either way.
        graph.source.connect(analyser);
      }
    } catch {
      setSupported(false);
      return;
    }

    setSupported(true);
    const bufferLength = analyser.frequencyBinCount;
    const data = new Uint8Array(bufferLength);
    const bucketSize = Math.max(1, Math.floor(bufferLength / barRefs.length));

    function frame() {
      if (cancelled || !analyser) return;
      analyser.getByteFrequencyData(data);

      for (let i = 0; i < barRefs.length; i++) {
        const start = i * bucketSize;
        const end = Math.min(start + bucketSize, bufferLength);
        let sum = 0;
        for (let j = start; j < end; j++) sum += data[j];
        const raw = end > start ? sum / (end - start) / 255 : 0;
        const target = Math.min(MAX_SCALE, Math.max(MIN_SCALE, raw * OVERALL_GAIN * gains[i]));

        const displayed = displayedRef.current;
        displayed[i] = reducedMotion ? target : displayed[i] + (target - displayed[i]) * INTERPOLATION_ALPHA;

        const el = barRefs[i]?.current;
        if (el) {
          el.style.transform = `scaleY(${displayed[i].toFixed(3)})`;
          if (highlightStrongLevels) {
            el.style.background = displayed[i] > STRONG_LEVEL_THRESHOLD ? "var(--accent-cyan-strong)" : "";
          }
        }
      }

      rafRef.current = requestAnimationFrame(frame);
    }

    rafRef.current = requestAnimationFrame(frame);

    cleanupRef.current = () => {
      cancelled = true;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      try {
        micSource?.disconnect();
      } catch {
        /* already disconnected */
      }
      try {
        analyser?.disconnect();
      } catch {
        /* already disconnected */
      }
      if (ownContext) {
        ownContext.close().catch(() => {});
      }
      // Reset bars to resting height/color once analysis stops.
      for (const ref of barRefs) {
        if (ref.current) {
          ref.current.style.transform = `scaleY(${MIN_SCALE})`;
          ref.current.style.background = "";
        }
      }
      displayedRef.current = gains.map(() => MIN_SCALE);
    };

    return () => cleanupRef.current?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, active, reducedMotion]);

  return { supported };
}
