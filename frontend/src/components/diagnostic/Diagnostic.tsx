import type { ReactNode } from "react";

/** Shared diagnostic-fault system. Every full-page fault state (404,
 * controller offline, unexpected interface failure) and the compact
 * inline states (Hermes degraded, a single failed module) are built from
 * these few pieces, so a fault always reads as "Jarvis diagnosing itself"
 * in one consistent visual language — never a generic broken-website
 * screen, and never the same treatment for genuinely different faults.
 * Color is load-bearing here: `tone="critical"` (red) means something is
 * actually unavailable; `tone="degraded"` (amber) means reduced but
 * usable; `tone="neutral"` (violet/cyan) means a navigation condition,
 * not a system fault. */

export type DiagnosticTone = "critical" | "degraded" | "neutral" | "recovered";
export type DiagnosticRingVariant = "gap" | "interrupted" | "dual" | "reconnecting";

interface DiagnosticCoreProps {
  tone: DiagnosticTone;
  /** "gap": a static ring with one missing segment (404 — the system
   * itself isn't broken). "interrupted": a slow, stuttering rotation with
   * a connector line that fades before reaching the core (a terminal,
   * non-retrying fault — the interface crash). "dual": a healthy-looking
   * outer ring with only the inner ring gapped (Hermes degraded while the
   * backend stays up). "reconnecting": Controller Offline's own variant —
   * a smooth continuous outer rotation, a counter-rotating inner
   * diagnostic trace, a breathing core, and a probe that extends/retracts
   * as if attempting a handshake; visibly accelerates during `scanning`. */
  variant: DiagnosticRingVariant;
  /** True only while a real retry attempt is in flight — briefly
   * brightens the ring, then decays back. Never a permanent decoration. */
  scanning?: boolean;
  /** True only for the brief one-shot success transition after a retry
   * has genuinely succeeded — reconnects the missing segment and plays
   * one controlled sweep. Never shown before the health check actually
   * resolves true. */
  recovering?: boolean;
  /** ~10% larger overall — used only where a caller wants this specific
   * core to read as the primary focus of the page. */
  large?: boolean;
}

export function DiagnosticCore({ tone, variant, scanning = false, recovering = false, large = false }: DiagnosticCoreProps) {
  const hasConnector = variant === "interrupted" || variant === "reconnecting";
  const hasInnerRing = variant === "dual" || variant === "reconnecting";

  return (
    <div
      className={`diag-core tone-${tone} variant-${variant}${scanning ? " is-scanning" : ""}${
        recovering ? " is-recovering" : ""
      }${large ? " is-large" : ""}`}
      role="img"
      aria-hidden="true"
    >
      {hasConnector && <span className="diag-connector" />}
      <span className="diag-ring diag-ring-outer">
        <span className="diag-ring diag-ring-gap" />
      </span>
      {hasInnerRing && (
        <span className={`diag-ring diag-inner-ring${variant === "dual" ? " is-interrupted" : ""}`}>
          {variant === "dual" && <span className="diag-ring diag-ring-gap" />}
        </span>
      )}
      <span className="diag-core-face" />
    </div>
  );
}

/** The short monospace status code shown near the core — "404", "OFFLINE",
 * "DEGRADED". Not printed inside the core itself, so the ring visuals
 * never have to make room for dense text. */
export function DiagnosticCode({ tone, children }: { tone: DiagnosticTone; children: ReactNode }) {
  return <span className={`diag-code tone-${tone}`}>{children}</span>;
}

interface DiagnosticPageProps {
  microLabel: string;
  heading: string;
  explanation: string;
  tone: DiagnosticTone;
  variant: DiagnosticRingVariant;
  scanning?: boolean;
  recovering?: boolean;
  large?: boolean;
  /** A short, non-secret local reference (e.g. an interface-fault ID) —
   * omit entirely when there is nothing truthful to show. */
  meta?: string;
  actions?: ReactNode;
  children?: ReactNode;
}

/** One full-height diagnostic screen, mounted in place of ordinary page
 * content inside the existing Jarvis shell (top bar stays). Every prop
 * here must come from real state — this component has no fallback
 * copy of its own, so a caller can never accidentally render a fault
 * screen with placeholder text. */
export function DiagnosticPage({
  microLabel,
  heading,
  explanation,
  tone,
  variant,
  scanning,
  recovering,
  large,
  meta,
  actions,
  children,
}: DiagnosticPageProps) {
  return (
    <main className="diagnostic-page" aria-labelledby="diagnostic-heading">
      <DiagnosticCore tone={tone} variant={variant} scanning={scanning} recovering={recovering} large={large} />
      <div className="diagnostic-text" role="status" aria-live="polite">
        <DiagnosticCode tone={tone}>{microLabel}</DiagnosticCode>
        <h1 id="diagnostic-heading" className="diagnostic-heading">
          {heading}
        </h1>
        <p className="diagnostic-explanation">{explanation}</p>
        {meta && <p className="diagnostic-meta">{meta}</p>}
      </div>
      {actions && <div className="recovery-actions">{actions}</div>}
      {children}
    </main>
  );
}

/** A row of recovery actions — always real navigable/callable actions,
 * never a decorative button that does nothing. */
export function RecoveryActions({ children }: { children: ReactNode }) {
  return <div className="recovery-actions">{children}</div>;
}

interface ModuleErrorStateProps {
  /** Which module failed — shown verbatim, e.g. "Sync history". */
  label: string;
  onRetry?: () => void;
  /** Sanitized, optional — never a raw exception or stack trace. */
  detail?: string;
}

/** A single failed supplementary request/panel — must never replace an
 * otherwise-healthy page, and must never be mistaken for a truthful empty
 * state ("no records") when the real answer is "unknown, request failed". */
export function ModuleErrorState({ label, onRetry, detail }: ModuleErrorStateProps) {
  return (
    <div className="module-error-state" role="alert">
      <div className="module-error-state-head">
        <span className="module-error-state-dot" aria-hidden="true" />
        <span>{label} unavailable</span>
      </div>
      <p className="module-error-state-body">
        This couldn't be loaded right now — status is unknown, not empty.
        {detail ? ` ${detail}` : ""}
      </p>
      {onRetry && (
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
