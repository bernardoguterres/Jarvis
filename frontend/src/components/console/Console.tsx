import type { ReactNode } from "react";

/** Shared internal-console primitives (Phase 6 Part 3). Every domain
 * conversation and every Centre is built from this small set of pieces so
 * they read as one interior of the same machine — near-black canvas, matte
 * module surfaces, thin violet borders, cyan reserved for something that
 * is actually live right now. None of these fabricate data: every prop
 * that renders as a number or a status must come from the caller's real
 * state, never a placeholder. */

interface ConsolePageProps {
  children: ReactNode;
  className?: string;
}

/** The near-black canvas every internal page renders onto, with the
 * faint fixed circuit-line texture and the shared entrance transition
 * (240-280ms fade/translate — see .console-page in index.css). */
export function ConsolePage({ children, className = "" }: ConsolePageProps) {
  return <div className={`console-page ${className}`.trim()}>{children}</div>;
}

interface ConsoleHeaderProps {
  /** Compact circular system/domain indicator — a MiniCoreIndicator or a
   * domain glyph. */
  indicator?: ReactNode;
  eyebrow?: string;
  title: string;
  subtitle?: string;
  /** Full description, kept in secondary text rather than a large hero
   * paragraph. */
  description?: string;
  /** Truthful metadata only — omit entirely rather than showing a zero or
   * placeholder the API didn't actually supply. */
  meta?: ReactNode;
  actions?: ReactNode;
}

export function ConsoleHeader({ indicator, eyebrow, title, subtitle, description, meta, actions }: ConsoleHeaderProps) {
  return (
    <header className="console-header">
      {indicator && <div className="console-header-indicator">{indicator}</div>}
      <div className="console-header-text">
        {eyebrow && <span className="console-eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {subtitle && <p className="console-subtitle">{subtitle}</p>}
        {description && <p className="console-description">{description}</p>}
        {meta && <div className="console-header-meta">{meta}</div>}
      </div>
      {actions && <div className="console-header-actions">{actions}</div>}
    </header>
  );
}

interface ConsoleModuleProps {
  children: ReactNode;
  title?: string;
  /** Renders the cyan "live" treatment — reserve strictly for something
   * actually listening/syncing/executing/connected right now. */
  live?: boolean;
  className?: string;
  actions?: ReactNode;
  as?: "section" | "div";
  ariaLabel?: string;
}

/** The one reusable module surface. Deliberately plain — callers vary size
 * and internal layout freely via className/children rather than this
 * primitive trying to anticipate every shape a module might need. */
export function ConsoleModule({ children, title, live = false, className = "", actions, as = "section", ariaLabel }: ConsoleModuleProps) {
  const Tag = as;
  return (
    <Tag className={`console-module${live ? " is-live" : ""} ${className}`.trim()} aria-label={ariaLabel ?? title}>
      {(title || actions) && (
        <div className="console-module-head">
          {title && <ConsoleSectionLabel>{title}</ConsoleSectionLabel>}
          {actions}
        </div>
      )}
      {children}
    </Tag>
  );
}

/** Small uppercase/monospace section divider label — used both standalone
 * and inside ConsoleModule's head. */
export function ConsoleSectionLabel({ children }: { children: ReactNode }) {
  return <span className="console-section-label">{children}</span>;
}

interface TelemetryRowProps {
  label: string;
  value: ReactNode;
  /** A small status point next to the value — only for a real state, never
   * decorative. */
  tone?: "ok" | "warn" | "error" | "active" | "neutral";
}

/** One compact label/value line — the building block of a provider's
 * status header, a routine's config summary, an action's audit entry. */
export function TelemetryRow({ label, value, tone }: TelemetryRowProps) {
  return (
    <div className="telemetry-row">
      <span className="telemetry-label">{label}</span>
      <span className="telemetry-value">
        {tone && <span className={`telemetry-dot tone-${tone}`} aria-hidden="true" />}
        {value}
      </span>
    </div>
  );
}

interface MiniCoreIndicatorProps {
  /** Only "live" states (listening/syncing/executing/thinking/speaking)
   * get the moving ring segment — everything else is static, per Phase 6's
   * "no permanently-rotating decoration" rule. */
  active?: boolean;
  tone?: "violet" | "cyan";
  size?: "sm" | "md";
}

/** The small circular Jarvis-system glyph used in console headers in place
 * of a giant decorative core — a quiet echo of JarvisCore's ring language,
 * not a competing centerpiece. Purely presentational; callers decide
 * `active` from real state only. */
export function MiniCoreIndicator({ active = false, tone = "violet", size = "md" }: MiniCoreIndicatorProps) {
  return (
    <span className={`mini-core mini-core-${size} mini-core-${tone}${active ? " is-active" : ""}`} aria-hidden="true">
      <span className="mini-core-ring" />
      <span className="mini-core-dot" />
    </span>
  );
}

interface ContextRailProps {
  children: ReactNode;
  className?: string;
}

/** The secondary column in a cockpit layout (conversation main + context
 * rail) — collapsible modules stacked vertically. On narrow viewports the
 * page layout moves this below the main column (see index.css). */
export function ContextRail({ children, className = "" }: ContextRailProps) {
  return (
    <aside className={`context-rail ${className}`.trim()} aria-label="Context">
      {children}
    </aside>
  );
}

interface TechnicalDetailsProps {
  children: ReactNode;
  summary?: string;
}

/** A `<details>`-based disclosure for raw/technical content (OAuth scopes,
 * raw JSON, workflow definitions) that shouldn't compete with the primary
 * humanized view. */
export function TechnicalDetails({ children, summary = "Technical details" }: TechnicalDetailsProps) {
  return (
    <details className="technical-details">
      <summary>{summary}</summary>
      <div className="technical-details-body">{children}</div>
    </details>
  );
}
