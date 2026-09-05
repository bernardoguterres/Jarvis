import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GeneralConversation from "./views/GeneralConversation";
import * as api from "./api";
import type { Conversation, Domain, TurnResult } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness and health.", created_at: "", updated_at: "" },
  { id: "2", slug: "mind", name: "MIND", description: "Mood and habits.", created_at: "", updated_at: "" },
  { id: "3", slug: "people", name: "PEOPLE", description: "Relationships.", created_at: "", updated_at: "" },
  { id: "4", slug: "path", name: "PATH", description: "Career and education.", created_at: "", updated_at: "" },
  { id: "5", slug: "build", name: "BUILD", description: "Projects and code.", created_at: "", updated_at: "" },
  { id: "6", slug: "life", name: "LIFE", description: "Calendar and finances.", created_at: "", updated_at: "" },
];

const CONVERSATION: Conversation = {
  id: "gen-1",
  domain_id: null,
  title: "General chat",
  created_at: "",
  updated_at: "",
  archived_at: null,
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function baseMocks() {
  vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([CONVERSATION]);
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
  vi.spyOn(api, "fetchMessages").mockResolvedValue([]);
}

async function openConversation(user: ReturnType<typeof userEvent.setup>) {
  render(<GeneralConversation onBack={() => {}} />);
  const conversationButton = await screen.findByRole("button", { name: /general chat/i });
  await user.click(conversationButton);
  return screen.findByPlaceholderText(/write a note, or send it to jarvis/i);
}

describe("GeneralConversation", () => {
  it("shows exactly six domain context chips, none pre-selected", async () => {
    baseMocks();
    render(<GeneralConversation onBack={() => {}} />);

    for (const domain of DOMAINS) {
      const checkbox = await screen.findByRole("checkbox", { name: domain.name });
      expect(checkbox).not.toBeChecked();
    }
  });

  it("has no domain-scoped heading — this is not a seventh domain", async () => {
    baseMocks();
    render(<GeneralConversation onBack={() => {}} />);
    expect(await screen.findByRole("heading", { name: /ask jarvis anything/i })).toBeInTheDocument();
  });

  it("sends a turn with no additional domains by default", async () => {
    baseMocks();
    const user = userEvent.setup();
    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockResolvedValue({
      run_id: "r1",
      status: "succeeded",
      user_message: { id: "m1", conversation_id: "gen-1", role: "user", content: "hi", created_at: "", model_used: null },
      assistant_message: null,
      provider: "hermes",
      model: "m",
      latency_ms: 1,
      usage: null,
      context_snapshot_id: null,
      error: null,
    } satisfies TurnResult);

    const textarea = await openConversation(user);
    await user.type(textarea, "hi");
    await user.click(screen.getByRole("button", { name: /send to jarvis/i }));

    expect(sendTurnSpy).toHaveBeenCalledWith("gen-1", "hi", expect.any(String), []);
  });

  it("requires acknowledging the sensitive-domain warning before including MIND for a turn", async () => {
    baseMocks();
    const user = userEvent.setup();
    const sendTurnSpy = vi.spyOn(api, "sendTurn");

    const textarea = await openConversation(user);
    await user.type(textarea, "hi");

    await user.click(screen.getByRole("checkbox", { name: /mind/i }));
    expect(screen.getByText(/sensitive domain/i)).toBeInTheDocument();

    const sendButton = screen.getByRole("button", { name: /send to jarvis/i });
    expect(sendButton).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /i understand, include it anyway/i }));
    expect(sendButton).toBeEnabled();

    sendTurnSpy.mockResolvedValue({
      run_id: "r1",
      status: "succeeded",
      user_message: { id: "m1", conversation_id: "gen-1", role: "user", content: "hi", created_at: "", model_used: null },
      assistant_message: null,
      provider: "hermes",
      model: "m",
      latency_ms: 1,
      usage: null,
      context_snapshot_id: null,
      error: null,
    });
    await user.click(sendButton);

    expect(sendTurnSpy).toHaveBeenCalledWith("gen-1", "hi", expect.any(String), ["2"]);
  });

  it("saves a Remember action as a global memory, not a domain-assigned one", async () => {
    baseMocks();
    vi.spyOn(api, "fetchMessages").mockResolvedValue([
      { id: "m1", conversation_id: "gen-1", role: "user", content: "I prefer mornings.", created_at: "", model_used: null },
    ]);
    const createMemorySpy = vi.spyOn(api, "createMemory").mockResolvedValue({
      id: "mem-1",
      scope: "global",
      domain_id: null,
      kind: "fact",
      title: "Morning preference",
      status: "active",
      importance: 3,
      confidence: 1,
      sensitivity: "normal",
      event_date: null,
      created_at: "",
      updated_at: "",
      current_version_id: "v1",
      supersedes_id: null,
      superseded_by_id: null,
    });
    const user = userEvent.setup();

    render(<GeneralConversation onBack={() => {}} />);
    const conversationButton = await screen.findByRole("button", { name: /general chat/i });
    await user.click(conversationButton);

    await screen.findByText("I prefer mornings.");
    await user.click(screen.getByRole("button", { name: /^remember$/i }));
    await user.type(screen.getByPlaceholderText("Memory title"), "Morning preference");
    await user.click(screen.getByRole("button", { name: /confirm remember/i }));

    expect(createMemorySpy).toHaveBeenCalledWith(
      expect.objectContaining({
        scope: "global",
        title: "Morning preference",
        content: "I prefer mornings.",
      }),
    );
    expect(createMemorySpy.mock.calls[0][0]).not.toHaveProperty("domain_id");
  });
});
