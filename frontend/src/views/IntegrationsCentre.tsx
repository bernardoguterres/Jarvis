import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  connectIntegration,
  deleteDocument,
  disconnectIntegration,
  fetchDomains,
  fetchGoogleHealthMetricGroups,
  fetchGoogleHealthUnsupportedMetrics,
  fetchMissionFocus,
  getDocument,
  getIntegrationSchedule,
  listCalendarEvents,
  listCalendars,
  listDocuments,
  listGoogleHealthSessions,
  listGoogleHealthSummaries,
  listIntegrations,
  selectCalendar,
  syncGoogleHealth,
  syncGoogleCalendar,
  updateIntegrationSchedule,
  uploadDocument,
  type CalendarCalendarInfo,
  type CalendarEventInfo,
  type DocumentChunkInfo,
  type DocumentInfo,
  type Domain,
  type GoogleHealthDailySummaryInfo,
  type GoogleHealthMetricGroupStatus,
  type GoogleHealthSessionInfo,
  type IntegrationConnection,
  type IntegrationProvider,
  type IntegrationSchedule,
  type MissionFocusPin,
} from "../api";
import AddToMissionFocusButton from "../components/AddToMissionFocusButton";
import StatusChip, { type ChipTone } from "../components/StatusChip";
import { ConsoleHeader, ConsoleModule, MiniCoreIndicator, TechnicalDetails } from "../components/console/Console";
import { ModuleErrorState } from "../components/diagnostic/Diagnostic";
import { formatDateTime } from "../formatDateTime";

const CONNECTION_STATUS_TONE: Record<string, ChipTone> = {
  connected: "ok",
  disconnected: "neutral",
  error: "error",
};

const DOCUMENT_STATUS_TONE: Record<string, ChipTone> = {
  ready: "ok",
  processing: "warn",
  error: "error",
  encrypted: "warn",
  unsupported: "neutral",
};

const CADENCE_OPTIONS: Record<IntegrationProvider, number[]> = {
  google_calendar: [15, 30, 60],
  google_health: [60, 180, 360, 1440],
};

function formatCadence(minutes: number): string {
  if (minutes < 60) return `${minutes} minutes`;
  if (minutes === 60) return "1 hour";
  if (minutes < 1440) return `${minutes / 60} hours`;
  return "daily";
}

interface IntegrationsCentreProps {
  onBack: () => void;
}

function IntegrationsCentre({ onBack }: IntegrationsCentreProps) {
  const [connections, setConnections] = useState<IntegrationConnection[]>([]);
  const [calendars, setCalendars] = useState<CalendarCalendarInfo[]>([]);
  const [events, setEvents] = useState<CalendarEventInfo[]>([]);
  const [missionFocusPins, setMissionFocusPins] = useState<MissionFocusPin[]>([]);
  const [googleHealthSummaries, setGoogleHealthSummaries] = useState<GoogleHealthDailySummaryInfo[]>([]);
  const [googleHealthSessions, setGoogleHealthSessions] = useState<GoogleHealthSessionInfo[]>([]);
  const [metricGroups, setMetricGroups] = useState<GoogleHealthMetricGroupStatus[]>([]);
  const [unsupportedMetrics, setUnsupportedMetrics] = useState<string[]>([]);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [calendarSchedule, setCalendarSchedule] = useState<IntegrationSchedule | null>(null);
  const [healthSchedule, setHealthSchedule] = useState<IntegrationSchedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // True only when the connection-status request itself has never
  // succeeded (or most recently failed) — actual connect/disconnect state
  // is unknown, so it must never be presented (or defaulted) as
  // "disconnected", and every action that depends on knowing the real
  // state must be disabled until this clears.
  const [statusUnknown, setStatusUnknown] = useState(true);
  // Per-module failure flags (Phase 6 diagnostic pass): a supplementary
  // request failing must render a truthful "unavailable" ModuleErrorState,
  // never be conflated with "genuinely zero records" by silently leaving
  // the corresponding list at its previous/empty value.
  const [healthSummariesFailed, setHealthSummariesFailed] = useState(false);
  const [healthSessionsFailed, setHealthSessionsFailed] = useState(false);

  const [uploadDomainId, setUploadDomainId] = useState("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<{ document: DocumentInfo; chunks: DocumentChunkInfo[] } | null>(null);
  const [docPendingDelete, setDocPendingDelete] = useState<DocumentInfo | null>(null);
  const [deleteFilenameInput, setDeleteFilenameInput] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    // The connection-status fetch is intentionally isolated from every
    // other, supplementary request below: a failure in, say, Google
    // Health's summaries endpoint must never be able to make Calendar or
    // Google Health look "disconnected" — that combination is exactly what
    // caused a real, confirmed incident (docs/DECISIONS.md D66).
    try {
      const conns = await listIntegrations();
      setConnections(conns);
      setStatusUnknown(false);
      setError(null);
    } catch {
      setStatusUnknown(true);
      setError("Unable to verify connection status. Actual connect/disconnect state is unknown — try again.");
    }

    const results = await Promise.allSettled([
      listCalendars(),
      listCalendarEvents(),
      listGoogleHealthSummaries(),
      listGoogleHealthSessions(),
      fetchGoogleHealthMetricGroups(),
      fetchGoogleHealthUnsupportedMetrics(),
      listDocuments(),
      getIntegrationSchedule("google_calendar"),
      getIntegrationSchedule("google_health"),
      fetchMissionFocus(),
    ]);
    const [cals, evs, googleHealth, sessions, groups, unsupported, docs, calSchedule, healthSched, missionFocus] = results;
    if (cals.status === "fulfilled") setCalendars(cals.value);
    if (evs.status === "fulfilled") setEvents(evs.value);
    setMissionFocusPins(missionFocus.status === "fulfilled" ? missionFocus.value.active_pins ?? [] : []);
    setHealthSummariesFailed(googleHealth.status === "rejected");
    if (googleHealth.status === "fulfilled") setGoogleHealthSummaries(googleHealth.value);
    setHealthSessionsFailed(sessions.status === "rejected");
    if (sessions.status === "fulfilled") setGoogleHealthSessions(sessions.value);
    if (groups.status === "fulfilled") setMetricGroups(groups.value);
    if (unsupported.status === "fulfilled") setUnsupportedMetrics(unsupported.value);
    if (docs.status === "fulfilled") setDocuments(docs.value);
    if (calSchedule.status === "fulfilled") setCalendarSchedule(calSchedule.value);
    if (healthSched.status === "fulfilled") setHealthSchedule(healthSched.value);
  }, []);

  async function handleScheduleToggle(provider: IntegrationProvider, enabled: boolean, intervalMinutes: number) {
    setError(null);
    try {
      const schedule = await updateIntegrationSchedule(provider, enabled, intervalMinutes);
      if (provider === "google_calendar") setCalendarSchedule(schedule);
      else setHealthSchedule(schedule);
    } catch {
      setError(`Could not update the automatic-sync schedule for ${provider}.`);
    }
  }

  useEffect(() => {
    refresh();
    fetchDomains().then(setDomains).catch(() => {});
  }, [refresh]);

  const googleConn = connections.find((c) => c.provider === "google_calendar");
  const googleHealthConn = connections.find((c) => c.provider === "google_health");

  async function handleConnect(provider: "google_calendar" | "google_health", includeWrite = false) {
    setError(null);
    try {
      // The backend itself opens the system browser server-side (see
      // POST /api/integrations/{provider}/connect) — not this frontend.
      // Tauri only injects its JS/IPC bridge into content loaded from its
      // own trusted origin, and this app's real content loads from the
      // same plain http://127.0.0.1 origin as everything else, so
      // window.__TAURI__ is never actually available here; a prior
      // version of this code tried to open the URL from here via that
      // bridge and silently did nothing. Opening it server-side works
      // identically for the packaged native app and the `jarvisctl.sh`
      // dev-mode browser workflow, so nothing extra happens here.
      await connectIntegration(provider, includeWrite);
    } catch {
      setError(`Could not start the ${provider} connection — is it configured? See README.md.`);
    }
  }

  async function handleDisconnect(provider: "google_calendar" | "google_health") {
    setError(null);
    try {
      await disconnectIntegration(provider);
      await refresh();
    } catch {
      setError(`Could not disconnect ${provider}.`);
    }
  }

  async function handleSyncCalendar() {
    setBusy(true);
    setError(null);
    try {
      await syncGoogleCalendar();
      await refresh();
    } catch {
      setError("Calendar sync failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSyncGoogleHealth() {
    setBusy(true);
    setError(null);
    try {
      await syncGoogleHealth(7);
      await refresh();
    } catch {
      setError("Google Health sync failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleCalendar(calendarId: string, selected: boolean) {
    setError(null);
    try {
      await selectCalendar(calendarId, selected);
      await refresh();
    } catch {
      setError("Could not update calendar selection.");
    }
  }

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    const file = fileInputRef.current?.files?.[0];
    if (!file || !uploadDomainId) return;
    setError(null);
    try {
      await uploadDocument(uploadDomainId, file);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not upload this document.");
    }
  }

  async function handleViewDocument(id: string) {
    try {
      const detail = await getDocument(id);
      setSelectedDoc(detail);
    } catch {
      setError("Could not load this document.");
    }
  }

  function handleDeleteDocument(doc: DocumentInfo) {
    // An in-app confirmation panel, not window.prompt() — a native
    // WebView (this app's own packaged window) doesn't reliably support
    // JS prompt dialogs the way a real browser tab does, so this is both
    // the fix for that and a UI more consistent with the rest of the app
    // (matches Data Management's own guarded-restore confirmation).
    setDocPendingDelete(doc);
    setDeleteFilenameInput("");
    setDeleteError(null);
  }

  function cancelDeleteDocument() {
    setDocPendingDelete(null);
    setDeleteFilenameInput("");
    setDeleteError(null);
  }

  async function confirmDeleteDocument() {
    if (!docPendingDelete) return;
    try {
      await deleteDocument(docPendingDelete.id, deleteFilenameInput);
      setSelectedDoc(null);
      setDocPendingDelete(null);
      setDeleteFilenameInput("");
      setDeleteError(null);
      await refresh();
    } catch {
      setDeleteError("Could not delete this document — check the filename matches exactly.");
    }
  }

  const connectedCount = connections.filter((c) => c.status === "connected").length;

  return (
    <div className="domain-view">
      <button type="button" className="back-button" onClick={onBack}>
        ← Back to Jarvis
      </button>

      <ConsoleHeader
        indicator={<MiniCoreIndicator active={busy} />}
        eyebrow="Centre"
        title="Integrations Centre"
        description="Google Calendar, Google Health (read-only), and imported local documents. No credentials or tokens ever appear here — those live only in the macOS Keychain."
        meta={
          !statusUnknown ? (
            <span>
              {connectedCount} of {connections.length || 2} providers connected
            </span>
          ) : undefined
        }
      />

      {error && (
        <p className="error-banner" role="alert">
          {error}
          {statusUnknown && (
            <>
              {" "}
              <button type="button" onClick={() => refresh()}>
                Retry
              </button>
            </>
          )}
        </p>
      )}

      <section aria-label="Google Calendar">
        <div className="status-cluster-item-head">
          <h2>Google Calendar</h2>
          {!statusUnknown && (
            <StatusChip
              label={googleConn?.status ?? "disconnected"}
              tone={CONNECTION_STATUS_TONE[googleConn?.status ?? "disconnected"]}
            />
          )}
        </div>

        {statusUnknown ? (
          <p>Status unavailable — actual connection state could not be verified.</p>
        ) : (
          <>
            <div className="ledger" style={{ margin: "0.4rem 0" }}>
              {googleConn?.last_sync_at && (
                <div className="ledger-row">
                  <span className="ledger-row-meta">Last synced</span>
                  <span className="ledger-row-main">{formatDateTime(googleConn.last_sync_at)}</span>
                </div>
              )}
              {googleConn?.last_error && (
                <div className="ledger-row">
                  <span className="ledger-row-meta">Error</span>
                  <span className="ledger-row-main">{googleConn.last_error}</span>
                </div>
              )}
              {!googleConn?.last_sync_at && !googleConn?.last_error && (
                <div className="ledger-row">
                  <span className="ledger-row-meta">Sync</span>
                  <span className="ledger-row-main">Never synced yet.</span>
                </div>
              )}
            </div>
            {googleConn?.scopes && googleConn.scopes.length > 0 && (
              <TechnicalDetails summary="OAuth scopes">
                <p>{googleConn.scopes.join(", ")}</p>
              </TechnicalDetails>
            )}
            {googleConn?.status === "connected" && !googleConn.scopes.includes("https://www.googleapis.com/auth/calendar.events.owned") && (
              <p className="notice">
                Calendar writing is not yet enabled — create/update/delete a single event still requires your explicit
                approval through the Actions Centre after this.
              </p>
            )}
          </>
        )}
        <div className="message-form-actions">
          {statusUnknown ? null : googleConn?.status === "connected" ? (
            <>
              <button type="button" className="primary" disabled={busy} onClick={handleSyncCalendar}>
                Sync now
              </button>
              {!googleConn.scopes.includes("https://www.googleapis.com/auth/calendar.events.owned") && (
                <button type="button" data-command-target="google_calendar.enable_writing" onClick={() => handleConnect("google_calendar", true)}>
                  Enable Calendar writing
                </button>
              )}
              <button type="button" className="danger" data-command-target="google_calendar.disconnect" onClick={() => handleDisconnect("google_calendar")}>
                Disconnect
              </button>
            </>
          ) : (
            <button type="button" className="primary" data-command-target="google_calendar.connect" onClick={() => handleConnect("google_calendar")}>
              Connect
            </button>
          )}
        </div>

        {!statusUnknown && googleConn?.status === "connected" && (
          <div className="message-form-actions">
            <label data-command-target="google_calendar.auto_sync_toggle">
              <input
                type="checkbox"
                checked={calendarSchedule?.enabled ?? false}
                onChange={(e) => handleScheduleToggle("google_calendar", e.target.checked, calendarSchedule?.interval_minutes ?? 30)}
              />
              Automatic sync
            </label>
            <select
              aria-label="Google Calendar automatic sync interval"
              value={calendarSchedule?.interval_minutes ?? 30}
              disabled={!calendarSchedule?.enabled}
              onChange={(e) => handleScheduleToggle("google_calendar", true, Number(e.target.value))}
            >
              {CADENCE_OPTIONS.google_calendar.map((m) => (
                <option key={m} value={m}>
                  every {formatCadence(m)}
                </option>
              ))}
            </select>
            {calendarSchedule && (
              <span>
                {calendarSchedule.last_success_at && ` · last synced ${formatDateTime(calendarSchedule.last_success_at)}`}
                {calendarSchedule.enabled && calendarSchedule.next_due_at && ` · next sync ${formatDateTime(calendarSchedule.next_due_at)}`}
                {calendarSchedule.consecutive_failure_count > 0 && ` · ${calendarSchedule.consecutive_failure_count} consecutive failure(s)`}
                {calendarSchedule.last_status === "reconnect_required" && " · reconnect required"}
              </span>
            )}
          </div>
        )}
        <p className="notice">
          Automatic sync only runs while Jarvis is running, and catches up with at most one sync after downtime — it
          never replays every missed interval.
        </p>

        {calendars.length > 0 && (
          <>
            <h3>Selected calendars</h3>
            <div className="ledger">
              {calendars.map((cal) => (
                <label key={cal.id} className="ledger-row" style={{ cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={cal.selected}
                    onChange={(e) => handleToggleCalendar(cal.id, e.target.checked)}
                  />
                  <span className="ledger-row-main">{cal.summary}</span>
                  <span className="ledger-row-meta">
                    {cal.access_role}
                    {cal.is_owned ? ", owned" : ""}
                  </span>
                </label>
              ))}
            </div>
          </>
        )}

        {events.length > 0 && (
          <>
            <h3>Upcoming events (cached)</h3>
            <div className="ledger">
              {events.map((ev) => (
                <div key={ev.id} className="ledger-row">
                  <span className="ledger-row-meta">{ev.all_day ? ev.start_date : ev.start_datetime}</span>
                  <span className="ledger-row-main">
                    {ev.title}
                    {ev.location && ` @ ${ev.location}`}
                  </span>
                  <AddToMissionFocusButton
                    sourceType="calendar_event"
                    sourceId={ev.id}
                    existingPin={missionFocusPins.find((p) => p.source_type === "calendar_event" && p.source_id === ev.id)}
                    onChanged={refresh}
                  />
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      <section aria-label="Google Health">
        <div className="status-cluster-item-head">
          <h2>Google Health</h2>
          {!statusUnknown && (
            <StatusChip
              label={googleHealthConn?.status ?? "disconnected"}
              tone={CONNECTION_STATUS_TONE[googleHealthConn?.status ?? "disconnected"]}
            />
          )}
        </div>
        <p className="notice">
          Reads consented data through the Google Health API — this can include data from Fitbit,
          Pixel Watch, Health Connect, Google Fit, and other sources you've connected in Google
          Health, depending on your account, granted scopes, and device capabilities. Not every
          metric or source is guaranteed to be present.
        </p>
        {statusUnknown ? (
          <p>Status unavailable — actual connection state could not be verified.</p>
        ) : (
          <>
            <div className="ledger" style={{ margin: "0.4rem 0" }}>
              <div className="ledger-row">
                <span className="ledger-row-meta">Write access</span>
                <span className="ledger-row-main">read-only — no write capability exists</span>
              </div>
              {googleHealthConn?.last_sync_at && (
                <div className="ledger-row">
                  <span className="ledger-row-meta">Last synced</span>
                  <span className="ledger-row-main">{formatDateTime(googleHealthConn.last_sync_at)}</span>
                </div>
              )}
              {googleHealthConn?.last_error && (
                <div className="ledger-row">
                  <span className="ledger-row-meta">Error</span>
                  <span className="ledger-row-main">{googleHealthConn.last_error}</span>
                </div>
              )}
            </div>
            {googleHealthConn?.scopes && googleHealthConn.scopes.length > 0 && (
              <TechnicalDetails summary="OAuth scopes">
                <p>{googleHealthConn.scopes.join(", ")}</p>
              </TechnicalDetails>
            )}
          </>
        )}
        <div className="message-form-actions">
          {statusUnknown ? null : googleHealthConn?.status === "connected" ? (
            <>
              <button type="button" className="primary" disabled={busy} onClick={handleSyncGoogleHealth}>
                Sync now
              </button>
              <button type="button" className="danger" data-command-target="google_health.disconnect" onClick={() => handleDisconnect("google_health")}>
                Disconnect
              </button>
            </>
          ) : (
            <button type="button" className="primary" data-command-target="google_health.connect" onClick={() => handleConnect("google_health")}>
              Connect
            </button>
          )}
        </div>

        {!statusUnknown && googleHealthConn?.status === "connected" && (
          <div className="message-form-actions">
            <label data-command-target="google_health.auto_sync_toggle">
              <input
                type="checkbox"
                checked={healthSchedule?.enabled ?? false}
                onChange={(e) => handleScheduleToggle("google_health", e.target.checked, healthSchedule?.interval_minutes ?? 360)}
              />
              Automatic sync
            </label>
            <select
              aria-label="Google Health automatic sync interval"
              value={healthSchedule?.interval_minutes ?? 360}
              disabled={!healthSchedule?.enabled}
              onChange={(e) => handleScheduleToggle("google_health", true, Number(e.target.value))}
            >
              {CADENCE_OPTIONS.google_health.map((m) => (
                <option key={m} value={m}>
                  every {formatCadence(m)}
                </option>
              ))}
            </select>
            {healthSchedule && (
              <span>
                {healthSchedule.last_success_at && ` · last synced ${formatDateTime(healthSchedule.last_success_at)}`}
                {healthSchedule.enabled && healthSchedule.next_due_at && ` · next sync ${formatDateTime(healthSchedule.next_due_at)}`}
                {healthSchedule.consecutive_failure_count > 0 && ` · ${healthSchedule.consecutive_failure_count} consecutive failure(s)`}
                {healthSchedule.last_status === "reconnect_required" && " · reconnect required"}
              </span>
            )}
          </div>
        )}
        <p className="notice">
          Automatic sync only runs while Jarvis is running, and catches up with at most one sync after downtime — it
          never replays every missed interval.
        </p>

        {metricGroups.length > 0 && (
          <>
            <h3>Metric groups</h3>
            <div className="ledger">
              {metricGroups.map((g) => (
                <div key={g.category} className="ledger-row">
                  <span className="ledger-row-main">{g.category}</span>
                  <span className="ledger-row-meta">{g.has_data ? "has data" : "no data available"}</span>
                </div>
              ))}
            </div>
          </>
        )}

        {healthSummariesFailed ? (
          <ModuleErrorState label="Health summaries" onRetry={refresh} />
        ) : (
          googleHealthSummaries.length > 0 && (
            <>
              <h3>
                Recent daily summaries (synced {googleHealthSummaries[googleHealthSummaries.length - 1].date} to{" "}
                {googleHealthSummaries[0].date})
              </h3>
              <div className="ledger">
                {googleHealthSummaries.map((s) => (
                  <div key={s.date} className="ledger-row">
                    <span className="ledger-row-meta">{s.date}</span>
                    <span className="ledger-row-main">
                      steps={s.steps ?? "—"} resting_hr={s.resting_heart_rate ?? "—"} sleep_min=
                      {s.sleep_minutes_asleep ?? "—"} weight_kg={s.weight_kg ?? "—"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )
        )}

        {healthSessionsFailed ? (
          <ModuleErrorState label="Sleep and exercise sessions" onRetry={refresh} />
        ) : (
          googleHealthSessions.length > 0 && (
            <>
              <h3>Recent sleep &amp; exercise sessions</h3>
              <div className="ledger">
                {googleHealthSessions.map((s) => (
                  <div key={`${s.session_type}-${s.start_time}`} className="ledger-row">
                    <span className="ledger-row-meta">{s.session_type}</span>
                    <span className="ledger-row-main">
                      {s.start_time} → {s.end_time}
                      {s.session_type === "sleep" && s.minutes_asleep != null && ` · ${s.minutes_asleep}m asleep`}
                      {s.session_type === "exercise" && s.activity_type && ` · ${s.activity_type}`}
                      {s.source_platform && ` · via ${s.source_platform}`}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )
        )}

        <TechnicalDetails summary="Unsupported metrics (not exposed by the Google Health API)">
          <ul>
            {unsupportedMetrics.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </TechnicalDetails>
      </section>

      <ConsoleModule title="Documents" ariaLabel="Documents">
        <form onSubmit={handleUpload} className="memory-create-form">
          <select aria-label="Domain for uploaded document" value={uploadDomainId} onChange={(e) => setUploadDomainId(e.target.value)}>
            <option value="">Choose a domain…</option>
            {domains.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt,.md,.markdown"
            aria-label="Document to upload"
          />
          <button type="submit" className="primary" disabled={!uploadDomainId}>
            Upload
          </button>
        </form>

        <div className="ledger" style={{ marginTop: "0.6rem" }}>
          {documents.map((doc) => (
            <div key={doc.id} className="ledger-row" style={{ flexWrap: "wrap" }}>
              <div className="ledger-row-main">
                <strong>{doc.original_filename}</strong>
                <StatusChip label={doc.status} tone={DOCUMENT_STATUS_TONE[doc.status]} />
                <span className="ledger-row-meta">
                  {doc.page_count ? `${doc.page_count} pages · ` : ""}
                  {doc.chunk_count} chunk(s)
                </span>
              </div>
              {doc.error_detail && <p className="error-banner">{doc.error_detail}</p>}
              <div className="ledger-row-actions">
                <button type="button" onClick={() => handleViewDocument(doc.id)}>
                  Preview
                </button>
                <button type="button" className="danger" onClick={() => handleDeleteDocument(doc)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
          {documents.length === 0 && <p className="ledger-empty">No documents imported yet.</p>}
        </div>

        {docPendingDelete && (
          <div className="vault-tier">
            <p role="alert" className="error-banner">
              Type the exact original filename to permanently delete{" "}
              <strong>{docPendingDelete.original_filename}</strong>. This cannot be undone.
            </p>
            <label htmlFor="delete-doc-filename-input">Original filename</label>
            <input
              id="delete-doc-filename-input"
              type="text"
              value={deleteFilenameInput}
              onChange={(e) => setDeleteFilenameInput(e.target.value)}
              autoFocus
            />
            {deleteError && (
              <p className="error-banner" role="alert">
                {deleteError}
              </p>
            )}
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.6rem" }}>
              <button
                type="button"
                className="danger"
                onClick={confirmDeleteDocument}
                disabled={deleteFilenameInput !== docPendingDelete.original_filename}
              >
                Delete permanently
              </button>
              <button type="button" onClick={cancelDeleteDocument}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {selectedDoc && (
          <div className="context-used-panel">
            <h3>{selectedDoc.document.original_filename}</h3>
            {selectedDoc.chunks.map((chunk) => (
              <p key={chunk.id} className="message-content">
                [chunk {chunk.chunk_index}
                {chunk.page_number ? `, page ${chunk.page_number}` : ""}] {chunk.content.slice(0, 400)}
              </p>
            ))}
          </div>
        )}
      </ConsoleModule>
    </div>
  );
}

export default IntegrationsCentre;
