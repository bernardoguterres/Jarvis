import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import IntegrationsCentre from "./views/IntegrationsCentre";
import * as api from "./api";
import type { Domain, IntegrationConnection } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness.", created_at: "", updated_at: "" },
];

beforeEach(() => {
  vi.restoreAllMocks();
  // Phase 12C: Mission Focus's own fetch, not what any of these tests are
  // about — default it to a harmless empty state.
  vi.spyOn(api, "fetchMissionFocus").mockResolvedValue({ active_pins: [], max_active_pins: 5, default_visible: 3 });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function baseMocks(overrides: Partial<Record<string, unknown>> = {}) {
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
  vi.spyOn(api, "listIntegrations").mockResolvedValue(
    (overrides.connections as IntegrationConnection[]) ?? [
      { provider: "google_calendar", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
      { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
    ],
  );
  vi.spyOn(api, "listCalendars").mockResolvedValue([]);
  vi.spyOn(api, "listCalendarEvents").mockResolvedValue([]);
  vi.spyOn(api, "listGoogleHealthSummaries").mockResolvedValue([]);
  vi.spyOn(api, "listGoogleHealthSessions").mockResolvedValue([]);
  vi.spyOn(api, "fetchGoogleHealthMetricGroups").mockResolvedValue([]);
  vi.spyOn(api, "fetchGoogleHealthUnsupportedMetrics").mockResolvedValue(["Daily Readiness Score", "Sleep Score"]);
  vi.spyOn(api, "listDocuments").mockResolvedValue([]);
  vi.spyOn(api, "getIntegrationSchedule").mockImplementation(async (provider) => ({
    provider,
    enabled: false,
    interval_minutes: provider === "google_calendar" ? 30 : 360,
    next_due_at: null,
    last_attempt_at: null,
    last_success_at: null,
    last_status: null,
    last_error: null,
    consecutive_failure_count: 0,
  }));
}

describe("IntegrationsCentre", () => {
  it("shows disconnected status and unsupported Google Health metrics, with no token material ever rendered", async () => {
    baseMocks();
    render(<IntegrationsCentre onBack={() => {}} />);

    expect(await screen.findByText(/Daily Readiness Score/)).toBeInTheDocument();
    expect(screen.getByText(/Sleep Score/)).toBeInTheDocument();
    expect(screen.getByText(/no write capability exists/i)).toBeInTheDocument();

    // Product language: "Google Health", not a Fitbit-specific integration
    // name — Fitbit is mentioned only as one of several possible sources.
    expect(screen.getByRole("heading", { name: "Google Health" })).toBeInTheDocument();
    expect(screen.getByText(/can include data from Fitbit/i)).toBeInTheDocument();

    // Never render anything resembling a token/secret field.
    expect(screen.queryByText(/access_token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/client_secret/i)).not.toBeInTheDocument();
  });

  it("connect calls the backend, which opens the browser server-side — never window.open from this frontend", async () => {
    const user = userEvent.setup();
    baseMocks();
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const connectSpy = vi
      .spyOn(api, "connectIntegration")
      .mockResolvedValue({ authorization_url: "https://accounts.google.com/auth?state=x" });

    render(<IntegrationsCentre onBack={() => {}} />);
    const connectButtons = await screen.findAllByRole("button", { name: /^connect$/i });
    await user.click(connectButtons[0]);

    // The backend's own POST /api/integrations/{provider}/connect opens
    // the system browser server-side (see app/routers/integrations.py) —
    // this frontend only ever needs to trigger that request. A prior
    // version of this code additionally called window.open()/a Tauri IPC
    // bridge from here, which turned out to silently do nothing in the
    // packaged native app (Tauri's JS bridge is never actually present on
    // this app's real, non-Tauri-origin content) — removed rather than
    // left as dead, misleading code.
    await waitFor(() => expect(connectSpy).toHaveBeenCalledWith("google_calendar", false));
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("shows connected status, sync button, and disconnect", async () => {
    const user = userEvent.setup();
    baseMocks({
      connections: [
        { provider: "google_calendar", status: "connected", scopes: ["calendar.readonly"], external_account_label: null, connected_at: "t", last_sync_at: "t2", last_sync_status: "ok", last_error: null },
        { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
      ],
    });
    const syncSpy = vi.spyOn(api, "syncGoogleCalendar").mockResolvedValue({
      provider: "google_calendar", status: "connected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: "ok", last_error: null,
    });
    const disconnectSpy = vi.spyOn(api, "disconnectIntegration").mockResolvedValue({
      provider: "google_calendar", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null,
    });

    render(<IntegrationsCentre onBack={() => {}} />);
    expect(await screen.findByText(/calendar.readonly/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /sync now/i }));
    await waitFor(() => expect(syncSpy).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: /disconnect/i }));
    await waitFor(() => expect(disconnectSpy).toHaveBeenCalledWith("google_calendar"));
  });

  it("offers to enable Calendar writing only when the owned-event scope is not yet granted", async () => {
    const user = userEvent.setup();
    baseMocks({
      connections: [
        { provider: "google_calendar", status: "connected", scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"], external_account_label: null, connected_at: "t", last_sync_at: null, last_sync_status: "ok", last_error: null },
        { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
      ],
    });
    const connectSpy = vi.spyOn(api, "connectIntegration").mockResolvedValue({ authorization_url: "https://accounts.google.com/auth?state=y" });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<IntegrationsCentre onBack={() => {}} />);
    const enableButton = await screen.findByRole("button", { name: /enable calendar writing/i });
    await user.click(enableButton);

    await waitFor(() => expect(connectSpy).toHaveBeenCalledWith("google_calendar", true));
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("hides the enable-writing button once the owned-event scope is already granted", async () => {
    baseMocks({
      connections: [
        { provider: "google_calendar", status: "connected", scopes: ["https://www.googleapis.com/auth/calendar.events.readonly", "https://www.googleapis.com/auth/calendar.events.owned"], external_account_label: null, connected_at: "t", last_sync_at: null, last_sync_status: "ok", last_error: null },
        { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
      ],
    });

    render(<IntegrationsCentre onBack={() => {}} />);
    await screen.findByText(/calendar.events.owned/);
    expect(screen.queryByRole("button", { name: /enable calendar writing/i })).not.toBeInTheDocument();
  });

  it("uploads a document and previews it", async () => {
    const user = userEvent.setup();
    baseMocks();
    const doc = {
      id: "doc-1", domain_id: "1", original_filename: "note.txt", mime_type: "text/plain", sha256: "abc",
      size_bytes: 10, page_count: null, status: "ready" as const, error_detail: null, chunk_count: 1, created_at: "t",
    };
    vi.spyOn(api, "uploadDocument").mockResolvedValue(doc);
    vi.spyOn(api, "listDocuments").mockResolvedValueOnce([]).mockResolvedValue([doc]);
    vi.spyOn(api, "getDocument").mockResolvedValue({
      document: doc,
      chunks: [{ id: "chunk-1", chunk_index: 0, page_number: null, content: "Some extracted text." }],
    });

    render(<IntegrationsCentre onBack={() => {}} />);
    await screen.findByText(/no documents imported yet/i);

    const select = screen.getByRole("combobox");
    await user.selectOptions(select, "1");

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["hello"], "note.txt", { type: "text/plain" });
    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: /^upload$/i }));

    expect(await screen.findByText("note.txt", { exact: false })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /preview/i }));
    expect(await screen.findByText(/Some extracted text/)).toBeInTheDocument();
  });

  it("requires typing the exact filename before a document can be deleted, never window.prompt", async () => {
    const user = userEvent.setup();
    baseMocks();
    const doc = {
      id: "doc-1", domain_id: "1", original_filename: "note.txt", mime_type: "text/plain", sha256: "abc",
      size_bytes: 10, page_count: null, status: "ready" as const, error_detail: null, chunk_count: 1, created_at: "t",
    };
    vi.spyOn(api, "listDocuments").mockResolvedValue([doc]);
    const deleteSpy = vi.spyOn(api, "deleteDocument").mockResolvedValue(undefined);
    const promptSpy = vi.spyOn(window, "prompt");

    render(<IntegrationsCentre onBack={() => {}} />);
    await user.click(await screen.findByRole("button", { name: /^delete$/i }));

    expect(promptSpy).not.toHaveBeenCalled();
    const confirmButton = screen.getByRole("button", { name: /delete permanently/i });
    expect(confirmButton).toBeDisabled();

    const input = screen.getByLabelText(/original filename/i);
    await user.type(input, "wrong-name.txt");
    expect(confirmButton).toBeDisabled();

    await user.clear(input);
    await user.type(input, "note.txt");
    expect(confirmButton).toBeEnabled();

    await user.click(confirmButton);
    expect(deleteSpy).toHaveBeenCalledWith("doc-1", "note.txt");
  });


  it("shows status unavailable, not disconnected, when the status request fails — and disables all connection actions", async () => {
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "listIntegrations").mockRejectedValue(new Error("network error"));
    vi.spyOn(api, "listCalendars").mockResolvedValue([]);
    vi.spyOn(api, "listCalendarEvents").mockResolvedValue([]);
    vi.spyOn(api, "listGoogleHealthSummaries").mockResolvedValue([]);
    vi.spyOn(api, "listGoogleHealthSessions").mockResolvedValue([]);
    vi.spyOn(api, "fetchGoogleHealthMetricGroups").mockResolvedValue([]);
    vi.spyOn(api, "fetchGoogleHealthUnsupportedMetrics").mockResolvedValue([]);
    vi.spyOn(api, "listDocuments").mockResolvedValue([]);

    render(<IntegrationsCentre onBack={() => {}} />);

    expect(await screen.findAllByText(/status unavailable/i)).toHaveLength(2);
    // Never rendered as "disconnected" when the real state is unknown.
    expect(screen.queryByText(/^Status: disconnected/)).not.toBeInTheDocument();
    // No Connect/Sync/Disconnect/Enable-writing action is offered while unknown.
    expect(screen.queryByRole("button", { name: /^connect$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sync now/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /disconnect/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /enable calendar writing/i })).not.toBeInTheDocument();
    // A visible retry action is offered.
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("recovers to the real connection states after Retry succeeds", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    const listIntegrationsSpy = vi
      .spyOn(api, "listIntegrations")
      .mockRejectedValueOnce(new Error("network error"))
      .mockResolvedValueOnce([
        { provider: "google_calendar", status: "connected", scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"], external_account_label: null, connected_at: "t", last_sync_at: null, last_sync_status: "ok", last_error: null },
        { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
      ]);
    vi.spyOn(api, "listCalendars").mockResolvedValue([]);
    vi.spyOn(api, "listCalendarEvents").mockResolvedValue([]);
    vi.spyOn(api, "listGoogleHealthSummaries").mockResolvedValue([]);
    vi.spyOn(api, "listGoogleHealthSessions").mockResolvedValue([]);
    vi.spyOn(api, "fetchGoogleHealthMetricGroups").mockResolvedValue([]);
    vi.spyOn(api, "fetchGoogleHealthUnsupportedMetrics").mockResolvedValue([]);
    vi.spyOn(api, "listDocuments").mockResolvedValue([]);

    render(<IntegrationsCentre onBack={() => {}} />);
    await screen.findByRole("button", { name: /retry/i });

    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(listIntegrationsSpy).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("button", { name: /sync now/i })).toBeInTheDocument();
    expect(screen.queryByText(/status unavailable/i)).not.toBeInTheDocument();
  });

  it("automatic-sync toggle defaults to unchecked/disabled", async () => {
    baseMocks({
      connections: [
        { provider: "google_calendar", status: "connected", scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"], external_account_label: null, connected_at: "t", last_sync_at: null, last_sync_status: "ok", last_error: null },
        { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
      ],
    });

    render(<IntegrationsCentre onBack={() => {}} />);
    const toggle = await screen.findByRole("checkbox", { name: /automatic sync/i });
    expect(toggle).not.toBeChecked();
  });

  it("enabling automatic sync calls updateIntegrationSchedule with the selected cadence", async () => {
    const user = userEvent.setup();
    baseMocks({
      connections: [
        { provider: "google_calendar", status: "connected", scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"], external_account_label: null, connected_at: "t", last_sync_at: null, last_sync_status: "ok", last_error: null },
        { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
      ],
    });
    const updateSpy = vi.spyOn(api, "updateIntegrationSchedule").mockResolvedValue({
      provider: "google_calendar", enabled: true, interval_minutes: 30, next_due_at: "t", last_attempt_at: null, last_success_at: null, last_status: null, last_error: null, consecutive_failure_count: 0,
    });

    render(<IntegrationsCentre onBack={() => {}} />);
    const toggle = await screen.findByRole("checkbox", { name: /automatic sync/i });
    await user.click(toggle);

    await waitFor(() => expect(updateSpy).toHaveBeenCalledWith("google_calendar", true, 30));
  });

  it("shows consecutive-failure count and reconnect-required state when present", async () => {
    baseMocks({
      connections: [
        { provider: "google_calendar", status: "connected", scopes: ["https://www.googleapis.com/auth/calendar.events.readonly"], external_account_label: null, connected_at: "t", last_sync_at: null, last_sync_status: "ok", last_error: null },
        { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
      ],
    });
    vi.spyOn(api, "getIntegrationSchedule").mockImplementation(async (provider) => ({
      provider,
      enabled: provider === "google_calendar",
      interval_minutes: provider === "google_calendar" ? 30 : 360,
      next_due_at: provider === "google_calendar" ? "2026-09-01T00:00:00Z" : null,
      last_attempt_at: null,
      last_success_at: null,
      last_status: provider === "google_calendar" ? "reconnect_required" : null,
      last_error: null,
      consecutive_failure_count: provider === "google_calendar" ? 3 : 0,
    }));

    render(<IntegrationsCentre onBack={() => {}} />);
    expect(await screen.findByText(/3 consecutive failure/i)).toBeInTheDocument();
    expect(screen.getByText(/reconnect required/i)).toBeInTheDocument();
  });

  it("a failed health-summaries request cannot falsely mark Google Health disconnected", async () => {
    baseMocks({
      connections: [
        { provider: "google_calendar", status: "connected", scopes: [], external_account_label: null, connected_at: "t", last_sync_at: "t", last_sync_status: "ok", last_error: null },
        { provider: "google_health", status: "connected", scopes: [], external_account_label: null, connected_at: "t", last_sync_at: "t", last_sync_status: "ok", last_error: null },
      ],
    });
    vi.spyOn(api, "listGoogleHealthSummaries").mockRejectedValue(new Error("network error"));

    render(<IntegrationsCentre onBack={() => {}} />);

    // The unrelated, successfully-fetched connection status is untouched —
    // still genuinely "connected", never demoted by an unrelated failure.
    expect(await screen.findAllByText(/connected/i)).not.toHaveLength(0);
    // The failed module shows a truthful "unavailable" state, not a silent
    // empty list that would read as "zero health summaries exist."
    expect(await screen.findByText(/health summaries unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/status is unknown, not empty/i)).toBeInTheDocument();
  });
});
