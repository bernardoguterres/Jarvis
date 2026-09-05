import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import * as api from "./api";
import type { Conversation, Domain, IntegrationConnection, TurnResult } from "./api";

// Phase 6 global-voice acceptance: Home/Centre voice push-to-talk, the
// deterministic command hierarchy (safe / confirm-required / ordinary
// question), and the single shared microphone/state machine.

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness and health.", created_at: "", updated_at: "" },
  { id: "2", slug: "mind", name: "MIND", description: "Mood and habits.", created_at: "", updated_at: "" },
  { id: "3", slug: "people", name: "PEOPLE", description: "Relationships.", created_at: "", updated_at: "" },
  { id: "4", slug: "path", name: "PATH", description: "Career and education.", created_at: "", updated_at: "" },
  { id: "5", slug: "build", name: "BUILD", description: "Projects and code.", created_at: "", updated_at: "" },
  { id: "6", slug: "life", name: "LIFE", description: "Calendar and finances.", created_at: "", updated_at: "" },
];

const AMBIENT_CONVERSATION: Conversation = {
  id: "ambient-1",
  domain_id: null,
  title: "Quick questions (voice)",
  created_at: "",
  updated_at: "",
  archived_at: null,
};

class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = [];
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(public stream: MediaStream) {
    FakeMediaRecorder.instances.push(this);
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["fake-audio"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

function mockAgentStatusUnavailable() {
  vi.spyOn(api, "fetchAgentStatus").mockResolvedValue({
    hermes_available: false,
    model_configured: false,
    model: null,
    provider: "hermes",
  });
}

function baseMocks() {
  vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
  mockAgentStatusUnavailable();
}

beforeEach(() => {
  vi.restoreAllMocks();
  FakeMediaRecorder.instances = [];
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder as unknown as typeof MediaRecorder);

  const fakeTrack = { stop: vi.fn() };
  const fakeStream = { getTracks: () => [fakeTrack] } as unknown as MediaStream;
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
  });

  vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:fake"), revokeObjectURL: vi.fn() });
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// userEvent's `{Space}` DSL key produces `code: "Unknown"` in this
// environment (real browsers, and the production handlers this exercises,
// use `event.code === "Space"`) — fireEvent dispatches the exact
// KeyboardEvent shape a genuine physical Space press produces.
async function pressAndReleaseSpace() {
  fireEvent.keyDown(window, { code: "Space", key: " " });
  await waitFor(() => expect(FakeMediaRecorder.instances).toHaveLength(1));
  fireEvent.keyUp(window, { code: "Space", key: " " });
}

describe("Global voice — Home (acceptance #2, #8, #10, #11, #12)", () => {
  it("sends an ordinary question spoken from Home to the ambient general conversation, with no domain included", async () => {
    baseMocks();
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    vi.spyOn(api, "createGeneralConversation").mockResolvedValue(AMBIENT_CONVERSATION);
    vi.spyOn(api, "transcribeAudio").mockResolvedValue("What's on my calendar this week?");
    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockResolvedValue({
      run_id: "run-1",
      status: "succeeded",
      user_message: { id: "m1", conversation_id: "ambient-1", role: "user", content: "What's on my calendar this week?", created_at: "", model_used: null },
      assistant_message: { id: "m2", conversation_id: "ambient-1", role: "assistant", content: "Nothing scheduled yet.", created_at: "", model_used: "openai-codex/gpt-5.6-terra" },
      provider: "hermes",
      model: "openai-codex/gpt-5.6-terra",
      latency_ms: 400,
      usage: null,
      context_snapshot_id: null,
      error: null,
    } satisfies TurnResult);
    vi.spyOn(api, "synthesizeSpeech").mockResolvedValue(new Blob(["fake-mp3"], { type: "audio/mpeg" }));

    render(<App />);
    await screen.findByText("BODY");

    await pressAndReleaseSpace();

    await waitFor(() => expect(sendTurnSpy).toHaveBeenCalledTimes(1));
    // Empty domain array: never mixes in a domain automatically.
    expect(sendTurnSpy).toHaveBeenCalledWith("ambient-1", "What's on my calendar this week?", expect.any(String), []);
    expect(api.createGeneralConversation).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalled());
    // Exactly one capture for the one gesture.
    expect(FakeMediaRecorder.instances).toHaveLength(1);
  });

  it("cancels the ambient capture on Escape without sending anything", async () => {
    baseMocks();
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    const sendTurnSpy = vi.spyOn(api, "sendTurn");

    render(<App />);
    await screen.findByText("BODY");

    fireEvent.keyDown(window, { code: "Space", key: " " });
    await waitFor(() => expect(FakeMediaRecorder.instances).toHaveLength(1));
    fireEvent.keyDown(window, { key: "Escape", code: "Escape" });
    fireEvent.keyUp(window, { code: "Space", key: " " });

    expect(sendTurnSpy).not.toHaveBeenCalled();
  });
});

describe("Global voice — Centre pages (acceptance #3, #4)", () => {
  it("executes a spoken navigation command deterministically from a Centre page", async () => {
    baseMocks();
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    vi.spyOn(api, "transcribeAudio").mockResolvedValue("go home");
    const sendTurnSpy = vi.spyOn(api, "sendTurn");

    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByLabelText(/open command palette/i));
    await user.click(screen.getByText(/open memory centre/i));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /command palette/i })).not.toBeInTheDocument());

    await pressAndReleaseSpace();

    // "go home" is a real command, executed deterministically — never sent
    // as a conversation turn.
    await waitFor(() => expect(screen.queryByText("BODY")).toBeInTheDocument());
    expect(sendTurnSpy).not.toHaveBeenCalled();
  });

  it("routes an ordinary spoken question from a Centre page to General Conversation instead of refusing it", async () => {
    baseMocks();
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    vi.spyOn(api, "createGeneralConversation").mockResolvedValue(AMBIENT_CONVERSATION);
    vi.spyOn(api, "transcribeAudio").mockResolvedValue("How is my knee doing lately?");
    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockResolvedValue({
      run_id: "run-2",
      status: "succeeded",
      user_message: { id: "m3", conversation_id: "ambient-1", role: "user", content: "How is my knee doing lately?", created_at: "", model_used: null },
      assistant_message: { id: "m4", conversation_id: "ambient-1", role: "assistant", content: "Looking steady.", created_at: "", model_used: "openai-codex/gpt-5.6-terra" },
      provider: "hermes",
      model: "openai-codex/gpt-5.6-terra",
      latency_ms: 400,
      usage: null,
      context_snapshot_id: null,
      error: null,
    } satisfies TurnResult);
    vi.spyOn(api, "synthesizeSpeech").mockResolvedValue(new Blob(["fake-mp3"], { type: "audio/mpeg" }));

    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByLabelText(/open command palette/i));
    await user.click(screen.getByText(/open memory centre/i));

    await pressAndReleaseSpace();

    // Never "not recognized as a command" — it's sent to Jarvis as an
    // ordinary question, exactly as it would be from Home or a domain.
    await waitFor(() => expect(sendTurnSpy).toHaveBeenCalledTimes(1));
    expect(sendTurnSpy).toHaveBeenCalledWith("ambient-1", "How is my knee doing lately?", expect.any(String), []);
  });
});

describe("Command safety — safe / confirm-required / proposal-lifecycle tiers (acceptance #5, #6, #7)", () => {
  it("executes a safe read-only command directly with no confirmation step", async () => {
    baseMocks();
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    vi.spyOn(api, "transcribeAudio").mockResolvedValue("sync calendar");
    const syncSpy = vi.spyOn(api, "syncGoogleCalendar").mockResolvedValue({
      provider: "google_calendar",
      status: "connected",
      scopes: [],
      external_account_label: null,
      connected_at: null,
      last_sync_at: null,
      last_sync_status: "ok",
      last_error: null,
    } satisfies IntegrationConnection);

    render(<App />);
    await screen.findByText("BODY");

    await pressAndReleaseSpace();

    await waitFor(() => expect(syncSpy).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/synced google calendar/i)).toBeInTheDocument();
  });

  it("never executes a confirmation-required command before a person accepts the dialog", async () => {
    baseMocks();
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    vi.spyOn(api, "transcribeAudio").mockResolvedValue("export data");
    const exportSpy = vi.spyOn(api, "createExport");

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("BODY");

    await pressAndReleaseSpace();

    const dialog = await screen.findByRole("alertdialog");
    expect(exportSpy).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(exportSpy).toHaveBeenCalledTimes(1));
  });

  it("cancelling the confirm dialog never executes the action", async () => {
    baseMocks();
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    vi.spyOn(api, "transcribeAudio").mockResolvedValue("disconnect google health");
    const disconnectSpy = vi.spyOn(api, "disconnectIntegration");

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("BODY");

    await pressAndReleaseSpace();

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    expect(disconnectSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("a proposal-lifecycle phrase (Calendar create) is never executed directly — it is sent as an ordinary question", async () => {
    baseMocks();
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    vi.spyOn(api, "createGeneralConversation").mockResolvedValue(AMBIENT_CONVERSATION);
    vi.spyOn(api, "transcribeAudio").mockResolvedValue("create a calendar event for tomorrow at 3pm");
    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockResolvedValue({
      run_id: "run-3",
      status: "succeeded",
      user_message: { id: "m5", conversation_id: "ambient-1", role: "user", content: "create a calendar event for tomorrow at 3pm", created_at: "", model_used: null },
      assistant_message: { id: "m6", conversation_id: "ambient-1", role: "assistant", content: "I can propose that for you.", created_at: "", model_used: "openai-codex/gpt-5.6-terra" },
      provider: "hermes",
      model: "openai-codex/gpt-5.6-terra",
      latency_ms: 400,
      usage: null,
      context_snapshot_id: null,
      error: null,
    } satisfies TurnResult);
    vi.spyOn(api, "synthesizeSpeech").mockResolvedValue(new Blob(["fake-mp3"], { type: "audio/mpeg" }));

    render(<App />);
    await screen.findByText("BODY");

    await pressAndReleaseSpace();

    await waitFor(() => expect(sendTurnSpy).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});

describe("Global voice does not double-capture when a domain conversation owns its own instance (acceptance #10)", () => {
  it("starts exactly one microphone capture when Space is pressed inside an open domain", async () => {
    baseMocks();
    vi.spyOn(api, "fetchConversations").mockResolvedValue([
      { id: "conv-1", domain_id: "1", title: "Knee check-in", created_at: "", updated_at: "", archived_at: null },
    ]);
    vi.spyOn(api, "fetchMessages").mockResolvedValue([]);
    vi.spyOn(api, "getDomainSummary").mockResolvedValue({ domain_id: "1", current_content: null, current_version_id: null, updated_at: null });
    vi.spyOn(api, "listMemories").mockResolvedValue([]);
    vi.spyOn(api, "listStructuredRecords").mockResolvedValue([]);
    vi.spyOn(api, "transcribeAudio").mockResolvedValue("   ");

    const user = userEvent.setup();
    render(<App />);
    const bodyButton = await screen.findByRole("button", { name: /open body/i });
    await user.click(bodyButton);
    const conversationButton = await screen.findByRole("button", { name: /knee check-in/i });
    await user.click(conversationButton);
    await screen.findByRole("button", { name: /hold to talk/i });

    await pressAndReleaseSpace();

    expect(FakeMediaRecorder.instances).toHaveLength(1);
  });
});
