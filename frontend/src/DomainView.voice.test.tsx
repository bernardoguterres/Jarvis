import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DomainView from "./views/DomainView";
import * as api from "./api";
import type { Conversation, Domain, TurnResult } from "./api";

const DOMAIN: Domain = {
  id: "1",
  slug: "body",
  name: "BODY",
  description: "Fitness and health.",
  created_at: "",
  updated_at: "",
};

const CONVERSATION: Conversation = {
  id: "conv-1",
  domain_id: "1",
  title: "Knee check-in",
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

function baseMocks(domains: Domain[] = [DOMAIN]) {
  vi.spyOn(api, "fetchDomains").mockResolvedValue(domains);
  vi.spyOn(api, "fetchConversations").mockResolvedValue([CONVERSATION]);
  vi.spyOn(api, "fetchMessages").mockResolvedValue([]);
  vi.spyOn(api, "getDomainSummary").mockResolvedValue({
    domain_id: "1",
    current_content: null,
    current_version_id: null,
    updated_at: null,
  });
  vi.spyOn(api, "listMemories").mockResolvedValue([]);
  vi.spyOn(api, "listStructuredRecords").mockResolvedValue([]);
}

beforeEach(() => {
  vi.restoreAllMocks();
  // Phase 12C: Mission Focus's own fetch, not what any of these tests are
  // about — default it to a harmless empty state.
  vi.spyOn(api, "fetchMissionFocus").mockResolvedValue({ active_pins: [], max_active_pins: 5, default_visible: 3 });
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

async function openConversation(user: ReturnType<typeof userEvent.setup>) {
  render(<DomainView slug="body" onBack={() => {}} />);
  const conversationButton = await screen.findByRole("button", { name: /knee check-in/i });
  await user.click(conversationButton);
  return screen.findByRole("button", { name: /hold to talk/i });
}

describe("DomainView — push-to-talk voice", () => {
  it("completes a full round trip: record, transcribe, send, and speak", async () => {
    baseMocks();
    const user = userEvent.setup();

    vi.spyOn(api, "transcribeAudio").mockResolvedValue("What do you remember about my knee?");

    const result: TurnResult = {
      run_id: "run-1",
      status: "succeeded",
      user_message: {
        id: "m1",
        conversation_id: "conv-1",
        role: "user",
        content: "What do you remember about my knee?",
        created_at: "",
        model_used: null,
      },
      assistant_message: {
        id: "m2",
        conversation_id: "conv-1",
        role: "assistant",
        content: "It's healing well.",
        created_at: "",
        model_used: "openai-codex/gpt-5.6-terra",
      },
      provider: "hermes",
      model: "openai-codex/gpt-5.6-terra",
      latency_ms: 500,
      usage: { input_tokens: 10, output_tokens: 8, total_tokens: 18 },
      context_snapshot_id: null,
      error: null,
    };
    vi.spyOn(api, "sendTurn").mockResolvedValue(result);
    vi.spyOn(api, "synthesizeSpeech").mockResolvedValue(new Blob(["fake-mp3"], { type: "audio/mpeg" }));

    const button = await openConversation(user);

    await user.pointer({ keys: "[MouseLeft>]", target: button });
    expect(FakeMediaRecorder.instances).toHaveLength(1);
    await user.pointer({ keys: "[/MouseLeft]", target: button });

    expect(await screen.findByText("It's healing well.")).toBeInTheDocument();
    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalled());
    expect(api.transcribeAudio).toHaveBeenCalledTimes(1);
    expect(api.synthesizeSpeech).toHaveBeenCalledWith("It's healing well.");
  });

  it("shows an error and does not submit a turn when transcription is empty", async () => {
    baseMocks();
    const user = userEvent.setup();

    vi.spyOn(api, "transcribeAudio").mockResolvedValue("   ");
    const sendTurnSpy = vi.spyOn(api, "sendTurn");

    const button = await openConversation(user);
    await user.pointer({ keys: "[MouseLeft>]", target: button });
    await user.pointer({ keys: "[/MouseLeft]", target: button });

    // Two places now truthfully show this: the page's own error banner and
    // the voice capture overlay's concise error reason.
    expect((await screen.findAllByText(/could not hear anything/i)).length).toBeGreaterThan(0);
    expect(sendTurnSpy).not.toHaveBeenCalled();
  });

  it("returns to idle when Escape cancels while the microphone permission prompt is still pending", async () => {
    baseMocks();
    const user = userEvent.setup();

    // getUserMedia deliberately never resolves within this test, simulating
    // a still-open browser permission prompt.
    let resolveGetUserMedia: (stream: MediaStream) => void = () => {};
    const pendingPermission = new Promise<MediaStream>((resolve) => {
      resolveGetUserMedia = resolve;
    });
    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockReturnValue(pendingPermission) },
    });

    const button = await openConversation(user);
    await user.pointer({ keys: "[MouseLeft>]", target: button });

    expect(await screen.findByText("listening")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    // Cancelling while permission is still pending must bring the UI back
    // to idle immediately, not leave it stuck on "listening" forever.
    await waitFor(() => expect(screen.queryByText("listening")).not.toBeInTheDocument());
    expect(FakeMediaRecorder.instances).toHaveLength(0);

    // Permission finally resolves after the cancel — recording must not
    // start retroactively.
    const fakeTrack = { stop: vi.fn() };
    resolveGetUserMedia({ getTracks: () => [fakeTrack] } as unknown as MediaStream);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(FakeMediaRecorder.instances).toHaveLength(0);
    expect(fakeTrack.stop).toHaveBeenCalled();
  });

  it("keeps the push-to-talk button enabled while listening, so a mouse release can reach it", async () => {
    baseMocks();
    const user = userEvent.setup();

    let resolveGetUserMedia: (stream: MediaStream) => void = () => {};
    const pendingPermission = new Promise<MediaStream>((resolve) => {
      resolveGetUserMedia = resolve;
    });
    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockReturnValue(pendingPermission) },
    });

    const button = await openConversation(user);
    await user.pointer({ keys: "[MouseLeft>]", target: button });

    expect(await screen.findByText("listening")).toBeInTheDocument();
    // A disabled button never receives mouseup/mouseleave at all — if this
    // button were disabled here, releasing the mouse could never stop the
    // recording, stranding the user in "listening" with no mouse-driven way
    // out (only Escape would still work, via the window-level listener).
    expect(button).toBeEnabled();

    await user.pointer({ keys: "[/MouseLeft]", target: button });
    await waitFor(() => expect(screen.queryByText("listening")).not.toBeInTheDocument());

    resolveGetUserMedia({ getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream);
  });
});

describe("DomainView — audio-reactive voice capture overlay (Phase 6)", () => {
  it("reuses the exact MediaStream already acquired — never a second getUserMedia call", async () => {
    baseMocks();
    const user = userEvent.setup();
    const getUserMediaSpy = navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>;

    const button = await openConversation(user);
    await user.pointer({ keys: "[MouseLeft>]", target: button });
    expect(await screen.findByText("MIC ACTIVE")).toBeInTheDocument();
    await user.pointer({ keys: "[/MouseLeft]", target: button });

    expect(getUserMediaSpy).toHaveBeenCalledTimes(1);
  });

  it("shows MIC ACTIVE, LISTENING, the real scope, and an elapsed timer only while genuinely listening", async () => {
    baseMocks();
    const user = userEvent.setup();

    const button = await openConversation(user);
    await user.pointer({ keys: "[MouseLeft>]", target: button });

    expect(await screen.findByText("MIC ACTIVE")).toBeInTheDocument();
    expect(screen.getByText("LISTENING")).toBeInTheDocument();
    expect(document.querySelector(".voice-capture-scope")).toHaveTextContent("BODY");
    expect(screen.getByText(/^\d:\d\d$/)).toBeInTheDocument();
    expect(screen.getByText(/release to send/i)).toBeInTheDocument();

    await user.pointer({ keys: "[/MouseLeft]", target: button });
    await waitFor(() => expect(screen.queryByText("MIC ACTIVE")).not.toBeInTheDocument());
  });

  it("never fabricates transcript text while listening — nothing claims to be a transcript before one genuinely exists", async () => {
    baseMocks();
    const user = userEvent.setup();
    let resolveTranscribe: (v: string) => void = () => {};
    vi.spyOn(api, "transcribeAudio").mockReturnValue(new Promise((r) => (resolveTranscribe = r)));

    const button = await openConversation(user);
    await user.pointer({ keys: "[MouseLeft>]", target: button });
    await screen.findByText("MIC ACTIVE");
    await user.pointer({ keys: "[/MouseLeft]", target: button });

    expect(await screen.findByText("TRANSCRIBING LOCALLY")).toBeInTheDocument();
    // No transcript content anywhere yet — only the truthful local-processing
    // label, never placeholder or guessed text standing in for real speech.
    expect(screen.queryByText(/what do you remember/i)).not.toBeInTheDocument();

    resolveTranscribe("real transcript now");
  });

  it("remains accessible under prefers-reduced-motion — state still visible as text, not motion-only", async () => {
    window.matchMedia = (query: string) =>
      ({
        matches: query.includes("reduce"),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList;

    baseMocks();
    const user = userEvent.setup();
    const button = await openConversation(user);
    await user.pointer({ keys: "[MouseLeft>]", target: button });

    expect(await screen.findByText("LISTENING")).toBeInTheDocument();
    expect(screen.getByText("MIC ACTIVE")).toBeInTheDocument();

    await user.pointer({ keys: "[/MouseLeft]", target: button });
  });
});
