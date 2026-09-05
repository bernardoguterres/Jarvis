import { useEffect, useRef, useState } from "react";
import {
  computeElapsedSeconds,
  computeRemainingSeconds,
  FOCUS_DURATION_MAX_MINUTES,
  FOCUS_DURATION_MIN_MINUTES,
  FOCUS_DURATION_PRESETS_MINUTES,
  type FocusSession,
  type MissionCandidate,
  type MissionCandidates,
} from "../api";
import { DOMAIN_SLUG_ORDER, type DomainSlug } from "../domainOrder";
import DomainGlyph from "./DomainGlyph";

interface MissionControlStripProps {
  candidates: MissionCandidates | null;
  candidatesLoading: boolean;
  candidatesError: string | null;
  currentMission: FocusSession | null;
  currentMissionLoading: boolean;
  currentMissionError: string | null;
  onStartFromCandidate: (candidate: MissionCandidate, minutes: number) => void;
  onStartManual: (title: string, domainSlug: DomainSlug | null, minutes: number) => void;
  onPause: () => void;
  onResume: () => void;
  onComplete: (completionNote: string | null, whatChangedNote: string | null) => void;
  onAbandon: () => void;
  /** True while a lifecycle call (start/pause/resume/complete/abandon) is
   * in flight — disables controls so a double-click can't double-submit,
   * never a page-wide loading flag. */
  busy: boolean;
  actionError: string | null;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function CandidateRow({
  candidate,
  emphasized,
  onStart,
}: {
  candidate: MissionCandidate;
  emphasized: boolean;
  onStart: (candidate: MissionCandidate) => void;
}) {
  return (
    <li className="briefing-item-row">
      <button type="button" className={`briefing-item tone-neutral${emphasized ? " mc-candidate-recommended" : ""}`} onClick={() => onStart(candidate)}>
        {candidate.domain_slug && (
          <span className="mc-candidate-glyph" aria-hidden="true">
            <DomainGlyph slug={candidate.domain_slug} />
          </span>
        )}
        <span className="briefing-item-body">
          <span className="briefing-item-title">{candidate.title}</span>
          <span className="briefing-item-subtitle">{candidate.reason}</span>
        </span>
        {(candidate.freshness === "stale" || candidate.freshness === "unavailable") && (
          <span className="briefing-item-freshness">{candidate.freshness}</span>
        )}
      </button>
    </li>
  );
}

function DurationPicker({ minutes, onChange }: { minutes: number; onChange: (minutes: number) => void }) {
  const [customOpen, setCustomOpen] = useState(!FOCUS_DURATION_PRESETS_MINUTES.includes(minutes as 25 | 45 | 60));
  return (
    <span className="mc-duration-picker" role="group" aria-label="Focus duration">
      {FOCUS_DURATION_PRESETS_MINUTES.map((preset) => (
        <button
          key={preset}
          type="button"
          className={`briefing-item-control${!customOpen && minutes === preset ? " mc-duration-selected" : ""}`}
          aria-pressed={!customOpen && minutes === preset}
          onClick={() => {
            setCustomOpen(false);
            onChange(preset);
          }}
        >
          {preset} min
        </button>
      ))}
      <button
        type="button"
        className={`briefing-item-control${customOpen ? " mc-duration-selected" : ""}`}
        aria-pressed={customOpen}
        onClick={() => setCustomOpen(true)}
      >
        Custom
      </button>
      {customOpen && (
        <label className="mc-duration-custom">
          <span className="sr-only">Custom duration in minutes</span>
          <input
            type="number"
            min={FOCUS_DURATION_MIN_MINUTES}
            max={FOCUS_DURATION_MAX_MINUTES}
            value={minutes}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v)) onChange(Math.min(FOCUS_DURATION_MAX_MINUTES, Math.max(FOCUS_DURATION_MIN_MINUTES, v)));
            }}
          />
          <span>min</span>
        </label>
      )}
    </span>
  );
}

function ManualStartForm({
  busy,
  onStart,
}: {
  busy: boolean;
  onStart: (title: string, domainSlug: DomainSlug | null, minutes: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [domainSlug, setDomainSlug] = useState<DomainSlug | "">("");
  const [minutes, setMinutes] = useState(25);

  if (!open) {
    return (
      <button type="button" className="briefing-strip-button action-note" onClick={() => setOpen(true)}>
        Start a custom focus session
      </button>
    );
  }

  return (
    <form
      className="mission-focus-add-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!title.trim()) return;
        onStart(title.trim(), domainSlug || null, minutes);
        setOpen(false);
        setTitle("");
        setDomainSlug("");
      }}
    >
      <label>
        What are you focusing on?
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Draft the UCL personal statement"
          maxLength={300}
          autoFocus
        />
      </label>
      <fieldset className="mc-domain-picker">
        <legend>Domain (optional)</legend>
        <span role="radiogroup" aria-label="Domain">
          {DOMAIN_SLUG_ORDER.map((slug) => (
            <button
              key={slug}
              type="button"
              role="radio"
              aria-checked={domainSlug === slug}
              className={`briefing-item-control${domainSlug === slug ? " mc-duration-selected" : ""}`}
              onClick={() => setDomainSlug(domainSlug === slug ? "" : slug)}
            >
              <DomainGlyph slug={slug} />
              {slug.toUpperCase()}
            </button>
          ))}
        </span>
      </fieldset>
      <DurationPicker minutes={minutes} onChange={setMinutes} />
      <span className="mission-focus-add-actions">
        <button type="submit" className="primary" disabled={busy || !title.trim()}>
          {busy ? "Starting…" : "Start focus session"}
        </button>
        <button type="button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </span>
    </form>
  );
}

function NoActiveMission({
  candidates,
  loading,
  error,
  onStartFromCandidate,
  onStartManual,
  busy,
}: Pick<
  MissionControlStripProps,
  "candidates" | "candidatesLoading" | "candidatesError" | "onStartFromCandidate" | "onStartManual" | "busy"
> & { loading: boolean; error: string | null }) {
  const [pendingCandidate, setPendingCandidate] = useState<MissionCandidate | null>(null);
  const [minutes, setMinutes] = useState(25);

  const recommended = candidates?.recommended ?? null;
  const alternatives = candidates?.alternatives ?? [];
  const watch = candidates?.watch ?? [];
  const hasAny = recommended || alternatives.length > 0;

  return (
    <>
      <div aria-live="polite">
        {error && (
          <p className="briefing-strip-error" role="alert">
            {error}
          </p>
        )}
        {!error && !loading && !hasAny && <p className="briefing-strip-empty">No suggested focus candidates right now.</p>}
      </div>

      {!error && hasAny && (
        <>
          <p className="briefing-strip-note">Suggested from current information — not a claim about what matters most.</p>
          <ul className="briefing-strip-list">
            {recommended && <CandidateRow candidate={recommended} emphasized onStart={setPendingCandidate} />}
            {alternatives.map((c) => (
              <CandidateRow key={c.stable_key} candidate={c} emphasized={false} onStart={setPendingCandidate} />
            ))}
          </ul>
        </>
      )}

      {pendingCandidate && (
        <div className="mc-start-confirm" role="group" aria-label={`Start focus on ${pendingCandidate.title}`}>
          <span className="briefing-item-title">{pendingCandidate.title}</span>
          <DurationPicker minutes={minutes} onChange={setMinutes} />
          <span className="mission-focus-add-actions">
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => {
                onStartFromCandidate(pendingCandidate, minutes);
                setPendingCandidate(null);
              }}
            >
              {busy ? "Starting…" : `Start (${minutes} min)`}
            </button>
            <button type="button" onClick={() => setPendingCandidate(null)} disabled={busy}>
              Choose another
            </button>
          </span>
        </div>
      )}

      {watch.length > 0 && (
        <details className="briefing-history">
          <summary>{watch.length} item{watch.length === 1 ? "" : "s"} to watch</summary>
          <ul className="mission-focus-list">
            {watch.map((c) => (
              <li key={c.stable_key} className="mission-focus-row">
                <span className="mission-focus-body">
                  <span className="mission-focus-title">{c.title}</span>
                  <span className="mission-focus-next-action">{c.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <ManualStartForm busy={busy} onStart={onStartManual} />
    </>
  );
}

function ActiveMission({
  session,
  onPause,
  onResume,
  onComplete,
  onAbandon,
  busy,
}: {
  session: FocusSession;
  onPause: () => void;
  onResume: () => void;
  onComplete: (completionNote: string | null, whatChangedNote: string | null) => void;
  onAbandon: () => void;
  busy: boolean;
}) {
  const [now, setNow] = useState(() => new Date());
  const [completing, setCompleting] = useState(false);
  const [completionNote, setCompletionNote] = useState("");
  const [whatChangedNote, setWhatChangedNote] = useState("");
  const headingRef = useRef<HTMLSpanElement>(null);

  // Starting a mission unmounts the manual-entry/candidate form and mounts
  // this component in its place — without this, keyboard/screen-reader
  // focus was silently dropped back to <body> (found during the Phase 12C
  // real-Mac acceptance pass), losing the user's place entirely. Moving
  // focus to this panel's own heading on mount keeps it inside Mission
  // Control and lets a screen reader announce the new active state
  // immediately, without stealing focus on every ordinary status re-render
  // (a plain useEffect with no session-identity dependency would refocus
  // on every elapsed-time tick, which is not the goal here).
  useEffect(() => {
    headingRef.current?.focus();
  }, [session.id]);

  // A setInterval tick purely to force a re-render every second while
  // active — elapsed/remaining are always re-derived from the session's
  // own persisted timestamps (computeElapsedSeconds), never held or
  // decremented by this interval itself. Paused/completed sessions don't
  // need a live tick at all — their elapsed time is already frozen.
  useEffect(() => {
    if (session.status !== "active") return;
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, [session.status]);

  const elapsed = computeElapsedSeconds(session, now);
  const remaining = computeRemainingSeconds(session, now);
  // Announced to screen readers only at a coarse (minute) granularity —
  // an aria-live region updated every second would be unusably noisy.
  const announcedMinute = Math.floor(elapsed / 60);

  return (
    <div className={`mc-active mc-active-${session.status}`}>
      <div className="mc-active-head">
        {session.domain_slug && (
          <span className="mc-candidate-glyph" aria-hidden="true">
            <DomainGlyph slug={session.domain_slug} />
          </span>
        )}
        <span className="briefing-item-title" ref={headingRef} tabIndex={-1}>
          {session.title}
        </span>
        <span className={`change-badge state-${session.status === "paused" ? "changed" : "ongoing"}`}>
          {session.status.toUpperCase()}
        </span>
      </div>

      <div className="mc-active-timer" aria-live="off">
        <span className="mc-timer-elapsed">{formatDuration(elapsed)}</span>
        <span className="mc-timer-sep"> / </span>
        <span className="mc-timer-target">{session.target_duration_minutes} min target</span>
        <span className="mc-timer-remaining">{formatDuration(remaining)} remaining</span>
      </div>
      {/* A separate, visually-hidden region carries the same information at
         a coarse, screen-reader-appropriate cadence (once per elapsed
         minute) rather than the second-by-second display above. */}
      <span className="sr-only" aria-live="polite">
        {announcedMinute} minute{announcedMinute === 1 ? "" : "s"} elapsed, {session.status}.
      </span>

      {session.source_title_snapshot && <p className="briefing-item-subtitle">Source: {session.source_title_snapshot}</p>}

      {!completing && (
        <span className="mission-focus-add-actions">
          {session.status === "active" && (
            <button type="button" className="briefing-strip-button" onClick={onPause} disabled={busy}>
              Pause
            </button>
          )}
          {session.status === "paused" && (
            <button type="button" className="briefing-strip-button" onClick={onResume} disabled={busy}>
              Resume
            </button>
          )}
          <button type="button" className="primary" onClick={() => setCompleting(true)} disabled={busy}>
            Complete
          </button>
          <button
            type="button"
            className="briefing-strip-button"
            onClick={() => {
              onAbandon();
            }}
            disabled={busy}
          >
            Abandon
          </button>
        </span>
      )}

      {completing && (
        <form
          className="mission-focus-add-form"
          onSubmit={(e) => {
            e.preventDefault();
            onComplete(completionNote.trim() || null, whatChangedNote.trim() || null);
            setCompleting(false);
            setCompletionNote("");
            setWhatChangedNote("");
          }}
        >
          <label>
            Completion note (optional)
            <input type="text" value={completionNote} onChange={(e) => setCompletionNote(e.target.value)} maxLength={1000} />
          </label>
          <label>
            What changed? (optional)
            <input type="text" value={whatChangedNote} onChange={(e) => setWhatChangedNote(e.target.value)} maxLength={1000} />
          </label>
          <span className="mission-focus-add-actions">
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Completing…" : "Mark complete"}
            </button>
            <button type="button" onClick={() => setCompleting(false)} disabled={busy}>
              Cancel
            </button>
          </span>
        </form>
      )}
    </div>
  );
}

/** Mission Control / Current Focus — reuses Home's own briefing candidates
 * (never a second prioritization engine) to suggest one thing to focus on
 * at a time, and a small local timer built entirely from the backend's
 * persisted session state (never a frontend countdown as source of
 * truth). Matches BriefingStrip's established visual register — this is
 * Home's own cinematic surface, not an internal-console screen — and
 * never claims a suggestion is definitively "the" priority. */
function MissionControlStrip({
  candidates,
  candidatesLoading,
  candidatesError,
  currentMission,
  currentMissionLoading,
  currentMissionError,
  onStartFromCandidate,
  onStartManual,
  onPause,
  onResume,
  onComplete,
  onAbandon,
  busy,
  actionError,
}: MissionControlStripProps) {
  return (
    <section className="briefing-strip mission-control-strip" aria-label="Mission Control">
      <div className="briefing-strip-head">
        <span className="briefing-strip-title">Mission Control</span>
      </div>

      {currentMissionError && (
        <p className="briefing-strip-error" role="alert">
          {currentMissionError}
        </p>
      )}

      {!currentMissionError && currentMissionLoading && !currentMission && (
        <p className="briefing-strip-empty">Loading current mission…</p>
      )}

      {!currentMissionError && !currentMissionLoading && currentMission && (
        <ActiveMission
          session={currentMission}
          onPause={onPause}
          onResume={onResume}
          onComplete={onComplete}
          onAbandon={onAbandon}
          busy={busy}
        />
      )}

      {!currentMissionError && !currentMissionLoading && !currentMission && (
        <NoActiveMission
          candidates={candidates}
          candidatesLoading={candidatesLoading}
          candidatesError={candidatesError}
          loading={candidatesLoading}
          error={candidatesError}
          onStartFromCandidate={onStartFromCandidate}
          onStartManual={onStartManual}
          busy={busy}
        />
      )}

      {actionError && (
        <p className="briefing-strip-error" role="alert">
          {actionError}
        </p>
      )}
    </section>
  );
}

export default MissionControlStrip;
