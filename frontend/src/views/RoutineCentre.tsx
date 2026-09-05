import { useCallback, useEffect, useState } from "react";
import {
  createConversation,
  fetchDomains,
  getRoutineSchedule,
  listRoutineHistory,
  recordCheckinResponses,
  runRoutineNow,
  sendTurn,
  updateRoutineSchedule,
  type Domain,
  type RoutineRunInfo,
  type RoutineSchedule,
  type RoutineType,
} from "../api";
import StatusChip, { type ChipTone } from "../components/StatusChip";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator } from "../components/console/Console";
import { formatDateTime } from "../formatDateTime";

interface RoutineCentreProps {
  onBack: () => void;
}

const ROUTINE_TYPES: RoutineType[] = ["morning_briefing", "evening_checkin", "weekly_review"];

const ROUTINE_LABELS: Record<RoutineType, string> = {
  morning_briefing: "Morning Briefing",
  evening_checkin: "Evening Check-in",
  weekly_review: "Weekly Review",
};

const SENSITIVE_DOMAINS = ["body", "mind", "people"];
const WEEKLY_REVIEW_DOMAINS = ["body", "mind", "people", "path", "build", "life"];
const WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

// Deliberately distinct from ROUTINE_LABELS — the schedule-overview strip
// shows a shorter tag for each routine so its text never collides with the
// full routine-name heading rendered below it (both would otherwise be
// exact-match ambiguous for anything querying visible text by name).
const ROUTINE_TAGS: Record<RoutineType, string> = {
  morning_briefing: "AM briefing",
  evening_checkin: "PM check-in",
  weekly_review: "Weekly",
};

const RUN_STATUS_TONE: Record<string, ChipTone> = {
  succeeded: "ok",
  failed: "error",
  skipped: "neutral",
};

function RoutineCentre({ onBack }: RoutineCentreProps) {
  const [schedules, setSchedules] = useState<Partial<Record<RoutineType, RoutineSchedule>>>({});
  const [history, setHistory] = useState<Partial<Record<RoutineType, RoutineRunInfo[]>>>({});
  const [domains, setDomains] = useState<Domain[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<RoutineType | null>(null);
  const [checkinAnswers, setCheckinAnswers] = useState<Record<string, string>>({});
  const [discussReply, setDiscussReply] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    for (const routineType of ROUTINE_TYPES) {
      try {
        const [schedule, hist] = await Promise.all([getRoutineSchedule(routineType), listRoutineHistory(routineType)]);
        setSchedules((prev) => ({ ...prev, [routineType]: schedule }));
        setHistory((prev) => ({ ...prev, [routineType]: hist }));
      } catch {
        // Leave that routine's panel showing its previous state rather than
        // crash the whole page over one failed fetch.
      }
    }
  }, []);

  useEffect(() => {
    refresh();
    fetchDomains().then(setDomains).catch(() => {});
  }, [refresh]);

  async function handleToggle(routineType: RoutineType, enabled: boolean) {
    setError(null);
    const current = schedules[routineType];
    if (!current) return;
    try {
      const updated = await updateRoutineSchedule(routineType, {
        enabled,
        local_time: current.local_time,
        timezone: current.timezone,
        weekday: current.weekday,
        selected_domains: current.selected_domains,
      });
      setSchedules((prev) => ({ ...prev, [routineType]: updated }));
    } catch {
      setError(`Could not update the ${ROUTINE_LABELS[routineType]} schedule.`);
    }
  }

  async function handleFieldChange(routineType: RoutineType, field: "local_time" | "timezone" | "weekday", value: string) {
    const current = schedules[routineType];
    if (!current) return;
    const next: RoutineSchedule = {
      ...current,
      local_time: field === "local_time" ? value : current.local_time,
      timezone: field === "timezone" ? value : current.timezone,
      weekday: field === "weekday" ? Number(value) : current.weekday,
    };
    setSchedules((prev) => ({ ...prev, [routineType]: next })); // optimistic local edit
    try {
      const updated = await updateRoutineSchedule(routineType, {
        enabled: next.enabled,
        local_time: next.local_time,
        timezone: next.timezone,
        weekday: next.weekday,
        selected_domains: next.selected_domains,
      });
      setSchedules((prev) => ({ ...prev, [routineType]: updated }));
    } catch {
      setError(`Could not update the ${ROUTINE_LABELS[routineType]} schedule.`);
    }
  }

  async function handleDomainToggle(routineType: RoutineType, slug: string, included: boolean) {
    const current = schedules[routineType];
    if (!current) return;
    const nextDomains = included
      ? [...current.selected_domains, slug]
      : current.selected_domains.filter((s) => s !== slug);
    try {
      const updated = await updateRoutineSchedule(routineType, {
        enabled: current.enabled,
        local_time: current.local_time,
        timezone: current.timezone,
        weekday: current.weekday,
        selected_domains: nextDomains,
      });
      setSchedules((prev) => ({ ...prev, [routineType]: updated }));
    } catch {
      setError(`Could not update ${ROUTINE_LABELS[routineType]}'s domain selection.`);
    }
  }

  async function handleRunNow(routineType: RoutineType) {
    setBusy(routineType);
    setError(null);
    try {
      await runRoutineNow(routineType);
      await refresh();
    } catch {
      setError(`Could not run ${ROUTINE_LABELS[routineType]} now.`);
    } finally {
      setBusy(null);
    }
  }

  async function handleSaveCheckinResponses(runId: string) {
    setError(null);
    try {
      await recordCheckinResponses(runId, checkinAnswers);
      await refresh();
    } catch {
      setError("Could not save your check-in responses.");
    }
  }

  async function handleDiscuss(routineType: RoutineType, run: RoutineRunInfo) {
    setError(null);
    setDiscussReply(null);
    try {
      const lifeDomain = domains.find((d) => d.slug === "life");
      if (!lifeDomain) throw new Error("no life domain");
      const conversation = await createConversation("life", `${ROUTINE_LABELS[routineType]} discussion`);
      const text = run.sections
        .map((s) => `${s.title}:\n` + s.lines.map((l) => `- ${l.text}`).join("\n"))
        .join("\n\n");
      const result = await sendTurn(
        conversation.id,
        `Here is my ${ROUTINE_LABELS[routineType]} output. Can you discuss it with me?\n\n${text}`,
        `routine-discuss-${run.id}`,
      );
      setDiscussReply(result.assistant_message?.content ?? "(no reply)");
    } catch {
      setError("Could not send this to Jarvis for discussion.");
    }
  }

  function renderLatestOutput(routineType: RoutineType) {
    const runs = history[routineType] ?? [];
    const latest = runs[0];
    if (!latest || latest.outcome !== "succeeded") return null;
    return (
      <div className="ledger" style={{ margin: "0.6rem 0" }}>
        <div className="ledger-row" style={{ flexDirection: "column", alignItems: "flex-start" }}>
          <span className="ledger-row-meta">Latest output (generated locally — not a model response)</span>
        </div>
        {latest.sections.map((section) => (
          <div key={section.title} className="ledger-row" style={{ flexDirection: "column", alignItems: "flex-start" }}>
            <strong>{section.title}</strong>
            <ul style={{ margin: "0.2rem 0 0" }}>
              {section.lines.map((line, i) => (
                <li key={i}>
                  {line.text}
                  {line.source_ref && ` (source: ${line.source_ref})`}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {routineType === "evening_checkin" && (
          <div className="ledger-row" style={{ flexDirection: "column", alignItems: "flex-start" }}>
            {latest.sections[0]?.lines.map((line, i) => (
              <label key={i} style={{ display: "block", width: "100%" }}>
                {line.text}
                <input
                  type="text"
                  value={checkinAnswers[line.text] ?? latest.responses[line.text] ?? ""}
                  onChange={(e) => setCheckinAnswers((prev) => ({ ...prev, [line.text]: e.target.value }))}
                />
              </label>
            ))}
            <button type="button" onClick={() => handleSaveCheckinResponses(latest.id)}>
              Save responses (local only — never auto-added to memory)
            </button>
          </div>
        )}
        <div className="ledger-row">
          <button type="button" className="action-note" onClick={() => handleDiscuss(routineType, latest)}>
            Discuss with Jarvis
          </button>
          {discussReply && (
            <span className="ledger-row-main">
              <strong>Jarvis (model response):</strong> {discussReply}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator active={busy !== null} />}
        eyebrow="Centre"
        title="Routine Centre"
        subtitle="Morning Briefing, Evening Check-in, and Weekly Review — a fixed set, each disabled until you enable it."
        description="Every routine only assembles a local, source-referenced summary; it never mutates Calendar or Health data, edits a memory, sends a notification, speaks aloud, or makes a model call on its own. Automatic runs only happen while Jarvis is running, and catch up with at most one run after downtime."
      />

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      <ConsoleModule title="Schedule overview" ariaLabel="Routine schedule overview">
        <div className="status-cluster">
          {ROUTINE_TYPES.map((routineType) => {
            const schedule = schedules[routineType];
            return (
              <div key={routineType} className={`status-cluster-item${schedule?.enabled ? " is-live" : ""}`}>
                <div className="status-cluster-item-head">
                  <span>{ROUTINE_TAGS[routineType]}</span>
                  <StatusChip
                    label={schedule?.enabled ? "enabled" : "disabled"}
                    tone={schedule?.enabled ? "ok" : "neutral"}
                  />
                </div>
                {schedule && (
                  <span className="ledger-row-meta">
                    {schedule.local_time} {schedule.timezone}
                    {schedule.enabled && schedule.next_due_at && ` · next ${formatDateTime(schedule.next_due_at)}`}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </ConsoleModule>

      {ROUTINE_TYPES.map((routineType) => {
        const schedule = schedules[routineType];
        return (
          <section aria-label={ROUTINE_LABELS[routineType]} key={routineType}>
            <div className="status-cluster-item-head">
              <h2>{ROUTINE_LABELS[routineType]}</h2>
              {schedule && (
                <StatusChip
                  label={schedule.last_status ?? "never run"}
                  tone={RUN_STATUS_TONE[schedule.last_status ?? ""] ?? "neutral"}
                />
              )}
            </div>
            {schedule && (
              <>
                <div className="message-form-actions">
                  <label>
                    <input type="checkbox" checked={schedule.enabled} onChange={(e) => handleToggle(routineType, e.target.checked)} />
                    Enabled
                  </label>
                  <label>
                    Time:{" "}
                    <input
                      type="time"
                      value={schedule.local_time}
                      onChange={(e) => handleFieldChange(routineType, "local_time", e.target.value)}
                    />
                  </label>
                  <label>
                    Timezone:{" "}
                    <input
                      type="text"
                      value={schedule.timezone}
                      onChange={(e) => handleFieldChange(routineType, "timezone", e.target.value)}
                    />
                  </label>
                  {routineType === "weekly_review" && (
                    <label>
                      Day:{" "}
                      <select
                        value={schedule.weekday ?? 6}
                        onChange={(e) => handleFieldChange(routineType, "weekday", e.target.value)}
                      >
                        {WEEKDAY_LABELS.map((label, i) => (
                          <option key={label} value={i}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <button type="button" className="primary" disabled={busy === routineType} onClick={() => handleRunNow(routineType)}>
                    Run now
                  </button>
                </div>

                {(routineType === "morning_briefing" ? SENSITIVE_DOMAINS : routineType === "weekly_review" ? WEEKLY_REVIEW_DOMAINS : []).length > 0 && (
                  <div className="control-rail-row">
                    <span className="ledger-row-meta">
                      {routineType === "weekly_review"
                        ? "Select which domains to include (each is opt-in):"
                        : "Sensitive domains require explicit inclusion:"}
                    </span>
                    {(routineType === "morning_briefing" ? SENSITIVE_DOMAINS : WEEKLY_REVIEW_DOMAINS).map((slug) => (
                      <label key={slug}>
                        <input
                          type="checkbox"
                          checked={schedule.selected_domains.includes(slug)}
                          onChange={(e) => handleDomainToggle(routineType, slug, e.target.checked)}
                        />
                        {slug.toUpperCase()}
                      </label>
                    ))}
                  </div>
                )}

                <p className="notice" style={{ marginTop: "0.5rem" }}>
                  {schedule.last_run_at && `Last run ${formatDateTime(schedule.last_run_at)}. `}
                  {schedule.consecutive_failure_count > 0 && `${schedule.consecutive_failure_count} consecutive failure(s). `}
                </p>
              </>
            )}

            {renderLatestOutput(routineType)}

            {(history[routineType] ?? []).length > 0 && (
              <ul className="timeline" style={{ marginTop: "0.6rem" }}>
                {(history[routineType] ?? []).map((run) => (
                  <li key={run.id} className={`timeline-item tone-${RUN_STATUS_TONE[run.outcome] ?? "neutral"}`}>
                    {formatDateTime(run.started_at)} · {run.trigger} · {run.outcome}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

export default RoutineCentre;
