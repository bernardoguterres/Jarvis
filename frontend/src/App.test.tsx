import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import * as api from "./api";
import type { Conversation, Domain, Message } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness and health.", created_at: "", updated_at: "" },
  { id: "2", slug: "mind", name: "MIND", description: "Mood and habits.", created_at: "", updated_at: "" },
  { id: "3", slug: "people", name: "PEOPLE", description: "Relationships.", created_at: "", updated_at: "" },
  { id: "4", slug: "path", name: "PATH", description: "Career and education.", created_at: "", updated_at: "" },
  { id: "5", slug: "build", name: "BUILD", description: "Projects and code.", created_at: "", updated_at: "" },
  { id: "6", slug: "life", name: "LIFE", description: "Calendar and finances.", created_at: "", updated_at: "" },
];

beforeEach(() => {
  vi.restoreAllMocks();
  // Phase 12A: Home's on-demand situational briefing fetch — not what any
  // of these tests are about, so default it to a harmless empty briefing
  // rather than letting an unmocked network call resolve unpredictably.
  vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue({
    generated_at: "2026-08-29T09:00:00Z",
    items: [],
    sources: [],
    include_body: true,
    include_mind: false,
    include_people: false,
    acknowledged_and_snoozed: [],
    mission_focus: [],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function mockAgentStatusUnavailable() {
  vi.spyOn(api, "fetchAgentStatus").mockResolvedValue({
    hermes_available: false,
    model_configured: false,
    model: null,
    provider: "hermes",
  });
}

describe("Home view", () => {
  it("renders all six domains once loaded", async () => {
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    mockAgentStatusUnavailable();

    render(<App />);

    for (const domain of DOMAINS) {
      expect(await screen.findByText(domain.name)).toBeInTheDocument();
    }
  });

  it("shows a backend-unavailable indicator when health check fails", async () => {
    vi.spyOn(api, "fetchHealth").mockRejectedValue(new Error("network error"));
    vi.spyOn(api, "fetchDomains").mockRejectedValue(new Error("network error"));
    mockAgentStatusUnavailable();

    render(<App />);

    expect(await screen.findByText(/backend unavailable/i)).toBeInTheDocument();
  });

  it("shows the top-bar Jarvis-unavailable indicator as degraded (amber), never critical (red), while the backend controller stays up — matching ModelLinkBanner's amber degraded treatment", async () => {
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    mockAgentStatusUnavailable();

    render(<App />);

    const dot = await screen.findByRole("status", { name: /jarvis: unavailable/i });
    expect(dot).toHaveClass("degraded");
    expect(dot).not.toHaveClass("error");
  });

  it("shows the top-bar indicator as degraded (amber), not critical (red), when Hermes is up but no model is configured", async () => {
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchAgentStatus").mockResolvedValue({
      hermes_available: true,
      model_configured: false,
      model: null,
      provider: "hermes",
    });

    render(<App />);

    const dot = await screen.findByRole("status", { name: /jarvis: model not configured/i });
    expect(dot).toHaveClass("degraded");
    expect(dot).not.toHaveClass("error");
  });
});

describe("General Jarvis conversation (Phase 6 — the core as an entry point)", () => {
  it("opens the general conversation when the core is clicked, and returns home from it", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    mockAgentStatusUnavailable();

    render(<App />);

    const coreButton = await screen.findByRole("button", { name: /talk to jarvis/i });
    await user.click(coreButton);

    expect(await screen.findByRole("heading", { name: /ask jarvis anything/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /back to jarvis/i }));

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: /ask jarvis anything/i })).not.toBeInTheDocument();
    });
    expect(await screen.findByText("BODY")).toBeInTheDocument();
  });

  it("opens the general conversation via keyboard (Enter) on the focused core", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    mockAgentStatusUnavailable();

    render(<App />);

    const coreButton = await screen.findByRole("button", { name: /talk to jarvis/i });
    coreButton.focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { name: /ask jarvis anything/i })).toBeInTheDocument();
  });

  it("does not create a seventh domain — exactly six still show on Home afterwards", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchGeneralConversations").mockResolvedValue([]);
    mockAgentStatusUnavailable();

    render(<App />);

    const coreButton = await screen.findByRole("button", { name: /talk to jarvis/i });
    await user.click(coreButton);
    await screen.findByRole("heading", { name: /ask jarvis anything/i });
    await user.click(screen.getByRole("button", { name: /back to jarvis/i }));

    for (const domain of DOMAINS) {
      expect(await screen.findByText(domain.name)).toBeInTheDocument();
    }
    expect(screen.queryAllByRole("button", { name: /^open (body|mind|people|path|build|life):/i })).toHaveLength(6);
  });
});

describe("Domain navigation and conversations", () => {
  it("opens a domain, creates a conversation, sends a message, and returns home", async () => {
    const user = userEvent.setup();

    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchConversations").mockResolvedValue([]);
    mockAgentStatusUnavailable();

    const newConversation: Conversation = {
      id: "conv-1",
      domain_id: "1",
      title: "Knee check-in",
      created_at: "",
      updated_at: "",
      archived_at: null,
    };
    vi.spyOn(api, "createConversation").mockResolvedValue(newConversation);
    vi.spyOn(api, "fetchMessages").mockResolvedValue([]);

    const savedMessage: Message = {
      id: "msg-1",
      conversation_id: "conv-1",
      role: "user",
      content: "Felt fine on today's run.",
      created_at: "",
      model_used: null,
    };
    vi.spyOn(api, "createMessage").mockResolvedValue(savedMessage);

    render(<App />);

    const bodyButton = await screen.findByRole("button", { name: /open body/i });
    await user.click(bodyButton);

    expect(await screen.findByRole("heading", { name: "BODY" })).toBeInTheDocument();
    expect(screen.getByText(/only that action generates one/i)).toBeInTheDocument();

    const titleInput = screen.getByPlaceholderText(/new conversation title/i);
    await user.type(titleInput, "Knee check-in");
    await user.click(screen.getByRole("button", { name: /^new$/i }));

    const textarea = await screen.findByPlaceholderText(/write a note, or send it to jarvis/i);
    await user.type(textarea, "Felt fine on today's run.");
    await user.click(screen.getByRole("button", { name: /^save as note$/i }));

    expect(await screen.findByText("Felt fine on today's run.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /back to jarvis/i }));

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "BODY" })).not.toBeInTheDocument();
    });
    expect(await screen.findByText("BODY")).toBeInTheDocument();
  });

  it("lists an existing conversation and opens it on click", async () => {
    const user = userEvent.setup();

    vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    mockAgentStatusUnavailable();

    const existing: Conversation = {
      id: "conv-2",
      domain_id: "5",
      title: "Alpha checkpoint",
      created_at: "",
      updated_at: "",
      archived_at: null,
    };
    vi.spyOn(api, "fetchConversations").mockResolvedValue([existing]);
    vi.spyOn(api, "fetchMessages").mockResolvedValue([
      {
        id: "msg-2",
        conversation_id: "conv-2",
        role: "user",
        content: "Shipped the tokenizer fix.",
        created_at: "",
        model_used: null,
      },
    ]);

    render(<App />);

    const buildButton = await screen.findByRole("button", { name: /open build/i });
    await user.click(buildButton);

    const conversationButton = await screen.findByRole("button", { name: /alpha checkpoint/i });
    await user.click(conversationButton);

    const detail = await screen.findByRole("region", { name: /messages/i });
    expect(within(detail).getByText("Shipped the tokenizer fix.")).toBeInTheDocument();
  });
});
