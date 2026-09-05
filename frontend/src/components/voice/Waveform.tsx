import { useMemo, useRef, type RefObject } from "react";

export type WaveformTone = "violet" | "cyan";

/** Odd bar counts only — a real center bar, symmetric on both sides, per
 * the Phase 6 voice-interface spec. */
export type WaveformBarCount = 7 | 9;

// Center bars react more strongly than outer ones — a fixed symmetric
// gain profile, peak at the center index, applied by useAudioLevels.
const GAIN_PROFILES: Record<WaveformBarCount, number[]> = {
  7: [0.45, 0.65, 0.85, 1, 0.85, 0.65, 0.45],
  9: [0.4, 0.55, 0.72, 0.88, 1, 0.88, 0.72, 0.55, 0.4],
};

export function useWaveformBars(barCount: WaveformBarCount) {
  const barRefs = useMemo<RefObject<HTMLDivElement | null>[]>(
    () => Array.from({ length: barCount }, () => ({ current: null })),
    [barCount],
  );
  const gains = GAIN_PROFILES[barCount];
  return { barRefs, gains };
}

interface WaveformProps {
  barRefs: RefObject<HTMLDivElement | null>[];
  tone: WaveformTone;
  /** A restrained CSS "breathing" fallback when Web Audio analysis isn't
   * available — still a truthful listening/speaking indicator, never a
   * fake fine-grained reactive waveform. */
  fallback?: boolean;
}

/** A compact vertical waveform — narrow rounded bars, symmetric around the
 * center. Bar heights are driven imperatively by useAudioLevels (direct
 * ref transforms, not React state) so a live 60fps waveform never forces
 * a re-render; this component only lays the bars out. */
function Waveform({ barRefs, tone, fallback = false }: WaveformProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  return (
    <div
      ref={containerRef}
      className={`voice-waveform tone-${tone}${fallback ? " is-fallback" : ""}`}
      aria-hidden="true"
    >
      {barRefs.map((ref, i) => (
        <div key={i} ref={ref} className="voice-waveform-bar" style={{ animationDelay: fallback ? `${i * 70}ms` : undefined }} />
      ))}
    </div>
  );
}

export default Waveform;
