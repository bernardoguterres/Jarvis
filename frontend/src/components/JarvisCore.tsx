import type { ReactNode } from "react";

export type CoreState = "idle" | "listening" | "transcribing" | "thinking" | "speaking" | "error";

interface JarvisCoreProps {
  state: CoreState;
  label?: string;
  /** When provided, the core becomes a real interactive control — pointer
   * click or Enter/Space while focused calls this (Phase 6: the core is
   * the entry point into a general Jarvis conversation, not a seventh
   * domain). Omitted entirely elsewhere, where the core stays the
   * non-interactive status indicator it always was. */
  onActivate?: () => void;
  /** True for the brief moment between activation and the general
   * conversation view actually mounting — mirrors DomainNode's
   * "is-focusing" energize-before-navigate treatment so this reads the
   * same way a domain selection does. */
  activating?: boolean;
  /** Replaces the "JARVIS"/substate label with real content (the
   * audio-reactive waveform) — the surrounding rings dim automatically
   * while this is present, so the waveform reads as the primary signal
   * without losing the core's structural identity (Phase 6 voice pass). */
  waveformSlot?: ReactNode;
  /** True while a Mission Control focus session is active — adds a
   * restrained, non-animating cyan tint to the idle core only. This is
   * deliberately NOT part of `CoreState`: applying it only alongside
   * "idle" (see the className logic below) means it can never visually
   * compete with or override listening/transcribing/thinking/speaking/
   * error, which always take a real `state` value of their own and so
   * always render without this modifier. */
  focusActive?: boolean;
}

const SUBSTATE_TEXT: Record<CoreState, string | null> = {
  idle: null,
  listening: "Listening…",
  transcribing: "Transcribing…",
  thinking: "Thinking…",
  speaking: "Speaking…",
  error: "Error",
};

/** The central Jarvis HUD element — a layered, state-driven ring system
 * (CLAUDE.md §9's central-state requirement, Phase 6's cinematic-HUD
 * direction). Every layer is a decorative CSS transform/opacity animation
 * driven purely by the `state-*` class from the real `state` prop; the
 * "JARVIS" label and substate text live in their own non-rotating layer so
 * they always stay upright and readable. Purely presentational — callers
 * own what `state` actually is (CLAUDE.md §9: "every status indicator must
 * correspond to real application state"), and every animation here is
 * globally disabled under prefers-reduced-motion (index.css). */
function JarvisCore({
  state,
  label = "JARVIS",
  onActivate,
  activating = false,
  waveformSlot,
  focusActive = false,
}: JarvisCoreProps) {
  const substate = SUBSTATE_TEXT[state];
  const rings = (
    <>
      <div className="jc-layer jc-boundary" aria-hidden="true" />
      <div className="jc-layer jc-segmented jc-spin-cw" aria-hidden="true" />
      <div className="jc-layer jc-ticks jc-spin-ccw" aria-hidden="true" />
      <div className="jc-layer jc-inner-ring jc-spin-cw-fast" aria-hidden="true" />
      <div className="jc-layer jc-sweep jc-spin-cw-sweep" aria-hidden="true" />
      <div className="jc-halo" aria-hidden="true" />
      <div className="jc-bars" aria-hidden="true">
        {Array.from({ length: 8 }).map((_, i) => (
          <span key={i} className="jc-bar" style={{ transform: `rotate(${i * 45}deg) translateY(calc(-1 * var(--core-size) * 0.62))`, animationDelay: `${i * 90}ms` }} />
        ))}
      </div>
      <div className="jc-core">
        {waveformSlot ?? (
          <>
            <span aria-hidden="true">{label}</span>
            {substate && (
              <span className="jarvis-core-substate" aria-hidden="true">
                {substate}
              </span>
            )}
          </>
        )}
      </div>
    </>
  );

  const hudClassName = `jarvis-hud state-${state}${state === "idle" && focusActive ? " is-focus-active" : ""}${waveformSlot ? " has-waveform" : ""}`;

  if (onActivate) {
    return (
      <button
        type="button"
        className={`${hudClassName} jarvis-hud-interactive${activating ? " is-activating" : ""}`}
        onClick={onActivate}
        aria-label="Talk to Jarvis"
      >
        {rings}
      </button>
    );
  }

  return (
    <div className={hudClassName} role="status" aria-label={substate ? `Jarvis: ${substate}` : "Jarvis: idle"}>
      {rings}
    </div>
  );
}

export default JarvisCore;
