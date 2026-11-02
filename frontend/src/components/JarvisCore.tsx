import type { ReactNode } from "react";

export type CoreState = "idle" | "listening" | "transcribing" | "thinking" | "speaking" | "error";

interface JarvisCoreProps {
  state: CoreState;
  label?: string;
  /** When provided, the core becomes a real interactive control: pointer
   * click or Enter/Space while focused calls this (the core is
   * the entry point into a general Jarvis conversation, not a seventh
   * domain). Omitted entirely elsewhere, where the core stays the
   * non-interactive status indicator it always was. */
  onActivate?: () => void;
  /** True for the brief moment between activation and the general
   * conversation view actually mounting. Mirrors DomainNode's
   * "is-focusing" energize-before-navigate treatment so this reads the
   * same way a domain selection does. */
  activating?: boolean;
  /** Replaces the "JARVIS"/substate label with real content (the
   * audio-reactive waveform). The surrounding rings dim automatically
   * while this is present, so the waveform reads as the primary signal
   * without losing the core's structural identity. */
  waveformSlot?: ReactNode;
  /** True while a Mission Control focus session is active. Adds a
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

/** The central Jarvis HUD element: two quiet rings around the core, an arc
 * that turns only while Jarvis is transcribing or thinking, and level bars
 * while it listens or speaks. Everything is driven purely by the `state-*`
 * class from the real `state` prop; the "JARVIS" label and substate text
 * never rotate, so they always stay upright and readable. Purely presentational: callers
 * own what `state` actually is (project rules §9: "every status indicator must
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
      <div className="jc-layer jc-inner-ring" aria-hidden="true" />
      <div className="jc-layer jc-sweep jc-spin-cw-sweep" aria-hidden="true" />
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
