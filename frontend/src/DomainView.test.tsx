import { render, screen } from "@testing-library/react";
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

beforeEach(() => {
  vi.restoreAllMocks();
  // Phase 12C: Mission Focus's own fetch, not what any of these tests are
  // about — default it to a harmless empty state.
  vi.spyOn(api, "fetchMissionFocus").mockResolvedValue({ active_pins: [], max_active_pins: 5, default_visible: 3 });
});

afterEach(() => {
  vi.restoreAllMocks();
});

const MIND_DOMAIN: Domain = {
  id: "2",
  slug: "mind",
  name: "MIND",
  description: "Mood and habits.",
  created_at: "",
  updated_at: "",
};

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

async function openConversation(user: ReturnType<typeof userEvent.setup>) {
  render(<DomainView slug="body" onBack={() => {}} />);
  const conversationButton = await screen.findByRole("button", { name: /knee check-in/i });
  await user.click(conversationButton);
  return screen.findByPlaceholderText(/write a note, or send it to jarvis/i);
}

describe("DomainView — Jarvis turns", () => {
  it("shows the real assistant response on a successful send", async () => {
    baseMocks();
    const user = userEvent.setup();

    const result: TurnResult = {
      run_id: "run-1",
      status: "succeeded",
      user_message: {
        id: "m1",
        conversation_id: "conv-1",
        role: "user",
        content: "How's my knee?",
        created_at: "",
        model_used: null,
      },
      assistant_message: {
        id: "m2",
        conversation_id: "conv-1",
        role: "assistant",
        content: "It sounds like it's recovering well.",
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

    const textarea = await openConversation(user);
    await user.type(textarea, "How's my knee?");
    await user.click(screen.getByRole("button", { name: /send to jarvis/i }));

    expect(await screen.findByText("It sounds like it's recovering well.")).toBeInTheDocument();
    expect(screen.getAllByText(/openai-codex\/gpt-5\.6-terra/).length).toBeGreaterThan(0);
  });

  it("shows a processing state while waiting for Jarvis", async () => {
    baseMocks();
    const user = userEvent.setup();

    let resolveTurn: (value: TurnResult) => void;
    const pending = new Promise<TurnResult>((resolve) => {
      resolveTurn = resolve;
    });
    vi.spyOn(api, "sendTurn").mockReturnValue(pending);

    const textarea = await openConversation(user);
    await user.type(textarea, "Hi");
    await user.click(screen.getByRole("button", { name: /send to jarvis/i }));

    expect(await screen.findByText(/thinking/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sending/i })).toBeDisabled();

    resolveTurn!({
      run_id: "run-2",
      status: "succeeded",
      user_message: {
        id: "m3",
        conversation_id: "conv-1",
        role: "user",
        content: "Hi",
        created_at: "",
        model_used: null,
      },
      assistant_message: {
        id: "m4",
        conversation_id: "conv-1",
        role: "assistant",
        content: "Hello.",
        created_at: "",
        model_used: "openai-codex/gpt-5.6-terra",
      },
      provider: "hermes",
      model: "openai-codex/gpt-5.6-terra",
      latency_ms: 100,
      usage: null,
      context_snapshot_id: null,
      error: null,
    });

    expect(await screen.findByText("Hello.")).toBeInTheDocument();
  });

  it("prevents duplicate submission while a send is in flight", async () => {
    baseMocks();
    const user = userEvent.setup();

    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockImplementation(
      () =>
        new Promise(() => {
          /* never resolves within this test */
        }),
    );

    const textarea = await openConversation(user);
    await user.type(textarea, "Hi");
    const sendButton = screen.getByRole("button", { name: /send to jarvis/i });
    await user.click(sendButton);
    await user.click(sendButton);
    await user.click(sendButton);

    expect(sendTurnSpy).toHaveBeenCalledTimes(1);
  });

  it("shows a local error and preserves typed content when Jarvis is unreachable", async () => {
    baseMocks();
    const user = userEvent.setup();
    vi.spyOn(api, "sendTurn").mockRejectedValue(new Error("network error"));

    const textarea = await openConversation(user);
    await user.type(textarea, "Hi there");
    await user.click(screen.getByRole("button", { name: /send to jarvis/i }));

    expect(await screen.findByText(/could not reach jarvis/i)).toBeInTheDocument();
    expect(textarea).toHaveValue("Hi there");
  });

  it("distinguishes saving a note from sending to Jarvis", async () => {
    baseMocks();
    const user = userEvent.setup();

    const createMessageSpy = vi.spyOn(api, "createMessage").mockResolvedValue({
      id: "note-1",
      conversation_id: "conv-1",
      role: "user",
      content: "just a note",
      created_at: "",
      model_used: null,
    });
    const sendTurnSpy = vi.spyOn(api, "sendTurn");

    const textarea = await openConversation(user);
    await user.type(textarea, "just a note");
    await user.click(screen.getByRole("button", { name: /^save as note$/i }));

    expect(await screen.findByText("just a note")).toBeInTheDocument();
    expect(createMessageSpy).toHaveBeenCalledTimes(1);
    expect(sendTurnSpy).not.toHaveBeenCalled();
  });
});

describe("DomainView — Phase 4 memory features", () => {
  it("saves a domain memory via the Remember flow", async () => {
    baseMocks();
    vi.spyOn(api, "fetchMessages").mockResolvedValue([
      { id: "m1", conversation_id: "conv-1", role: "user", content: "Knee felt sore today.", created_at: "", model_used: null },
    ]);
    const createMemorySpy = vi.spyOn(api, "createMemory").mockResolvedValue({
      id: "mem-1", scope: "domain", domain_id: "1", kind: "health_context", title: "Knee soreness",
      status: "active", importance: 3, confidence: 1, sensitivity: "normal", event_date: null,
      created_at: "", updated_at: "", current_version_id: "v1", supersedes_id: null, superseded_by_id: null,
    });
    const user = userEvent.setup();

    render(<DomainView slug="body" onBack={() => {}} />);
    const conversationButton = await screen.findByRole("button", { name: /knee check-in/i });
    await user.click(conversationButton);

    await screen.findByText("Knee felt sore today.");
    await user.click(screen.getByRole("button", { name: /^remember$/i }));

    await user.type(screen.getByPlaceholderText("Memory title"), "Knee soreness");
    await user.click(screen.getByRole("button", { name: /confirm remember/i }));

    expect(createMemorySpy).toHaveBeenCalledWith(
      expect.objectContaining({
        scope: "domain",
        domain_id: "1",
        title: "Knee soreness",
        content: "Knee felt sore today.",
        source_message_id: "m1",
      }),
    );
  });

  it("shows Context Used details for an assistant response", async () => {
    baseMocks();
    const user = userEvent.setup();

    const result: TurnResult = {
      run_id: "run-9",
      status: "succeeded",
      user_message: { id: "m1", conversation_id: "conv-1", role: "user", content: "hi", created_at: "", model_used: null },
      assistant_message: { id: "m2", conversation_id: "conv-1", role: "assistant", content: "hello", created_at: "", model_used: "fake-model" },
      provider: "hermes", model: "fake-model", latency_ms: 10,
      usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 },
      context_snapshot_id: "snap-1", error: null,
    };
    vi.spyOn(api, "sendTurn").mockResolvedValue(result);
    vi.spyOn(api, "getContextSnapshot").mockResolvedValue({
      id: "snap-1", agent_run_id: "run-9", active_domain_id: "1", additional_domain_ids: [],
      global_memory_version_ids: ["gv1"], domain_memory_version_ids: ["dv1", "dv2"],
      domain_summary_version_ids: ["sv1"], structured_record_ids: [], recent_message_ids: ["m1"],
      retrieval_query: "hi", retrieval_reasons: [{ memory_item_id: "dv1", reason: "lexical match" }],
      estimated_context_chars: 1234, created_at: "",
    });

    const textarea = await openConversation(user);
    await user.type(textarea, "hi");
    await user.click(screen.getByRole("button", { name: /send to jarvis/i }));
    await screen.findByText("hello");

    await user.click(screen.getByRole("button", { name: /context used/i }));

    expect(await screen.findByText(/estimated context size: 1234 chars/i)).toBeInTheDocument();
    expect(screen.getByText(/domain memory versions used: 2/i)).toBeInTheDocument();
  });

  it("requires acknowledging the sensitive-domain warning before sending with a sensitive additional domain", async () => {
    baseMocks([DOMAIN, MIND_DOMAIN]);
    const sendTurnSpy = vi.spyOn(api, "sendTurn");
    const user = userEvent.setup();

    const textarea = await openConversation(user);
    await user.type(textarea, "hi");

    await user.click(screen.getByRole("checkbox", { name: /mind/i }));
    expect(screen.getByText(/sensitive domain/i)).toBeInTheDocument();

    const sendButton = screen.getByRole("button", { name: /send to jarvis/i });
    expect(sendButton).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /i understand, include it anyway/i }));
    expect(sendButton).toBeEnabled();

    sendTurnSpy.mockResolvedValue({
      run_id: "r1", status: "succeeded",
      user_message: { id: "m1", conversation_id: "conv-1", role: "user", content: "hi", created_at: "", model_used: null },
      assistant_message: null, provider: "hermes", model: "m", latency_ms: 1, usage: null,
      context_snapshot_id: null, error: null,
    });
    await user.click(sendButton);

    expect(sendTurnSpy).toHaveBeenCalledWith("conv-1", "hi", expect.any(String), ["2"]);
  });
});

describe("DomainView — header identity (Phase 6, D91/D91)", () => {
  it("shows the domain glyph and its canonical number, and never shows the live-activity dot while idle", async () => {
    baseMocks();
    render(<DomainView slug="body" onBack={vi.fn()} onSystemCommand={vi.fn()} />);
    await screen.findByRole("heading", { name: "BODY" });

    const emblem = document.querySelector(".domain-emblem");
    expect(emblem).not.toBeNull();
    expect(emblem!.querySelector("svg.domain-glyph")).not.toBeNull();
    expect(document.querySelector(".domain-emblem-kbd")!.textContent).toBe("1");

    // The violet arc-and-dot only conveys real state (Jarvis genuinely
    // processing/listening) — with nothing happening, it must not be
    // rendered at all, so it never competes with the domain glyph.
    expect(document.querySelector(".mini-core")).toBeNull();
  });

  it("shows the live-activity indicator only while genuinely sending to Jarvis", async () => {
    baseMocks();
    const user = userEvent.setup();
    let resolveTurn: (value: TurnResult) => void;
    const pending = new Promise<TurnResult>((resolve) => {
      resolveTurn = resolve;
    });
    vi.spyOn(api, "sendTurn").mockReturnValue(pending);

    const textarea = await openConversation(user);
    await user.type(textarea, "Hi");
    await user.click(screen.getByRole("button", { name: /send to jarvis/i }));

    expect(await screen.findByText(/thinking/i)).toBeInTheDocument();
    expect(document.querySelector(".mini-core")).not.toBeNull();
    expect(document.querySelector(".mini-core-sm")).not.toBeNull();

    resolveTurn!({
      run_id: "run-3",
      status: "succeeded",
      user_message: { id: "m5", conversation_id: "conv-1", role: "user", content: "Hi", created_at: "", model_used: null },
      assistant_message: {
        id: "m6",
        conversation_id: "conv-1",
        role: "assistant",
        content: "Hello.",
        created_at: "",
        model_used: "openai-codex/gpt-5.6-terra",
      },
      provider: "hermes",
      model: "openai-codex/gpt-5.6-terra",
      latency_ms: 100,
      usage: null,
      context_snapshot_id: null,
      error: null,
    });
    await screen.findByText("Hello.");
    expect(document.querySelector(".mini-core")).toBeNull();
  });
});
