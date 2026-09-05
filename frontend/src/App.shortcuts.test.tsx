import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import * as api from "./api";
import type { Domain } from "./api";

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
});

afterEach(() => {
  vi.restoreAllMocks();
});

function baseMocks() {
  vi.spyOn(api, "fetchHealth").mockResolvedValue({ status: "ok" });
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
  vi.spyOn(api, "fetchAgentStatus").mockResolvedValue({
    hermes_available: false,
    model_configured: false,
    model: null,
    provider: "hermes",
  });
  vi.spyOn(api, "fetchConversations").mockResolvedValue([]);
  vi.spyOn(api, "listExports").mockResolvedValue([]);
  vi.spyOn(api, "fetchLatestBackup").mockResolvedValue({
    latest: null,
    by_category: { daily: null, weekly: null, monthly: null },
  });
  vi.spyOn(api, "listMemories").mockResolvedValue([]);
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
}

describe("App — global keyboard shortcuts", () => {
  it("digit keys 1-6 open the corresponding domain when no input is focused", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    await screen.findByText("BODY");
    await user.keyboard("2");

    expect(await screen.findByRole("heading", { name: "BUILD" })).toBeInTheDocument();
  });

  it("digit 0 returns to the Jarvis home view from a domain", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    await screen.findByText("BODY");
    await user.keyboard("2");
    expect(await screen.findByRole("heading", { name: "BUILD" })).toBeInTheDocument();

    await user.keyboard("0");
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "BUILD" })).not.toBeInTheDocument();
    });
    expect(await screen.findByText("BODY")).toBeInTheDocument();
  });

  it("does not trigger the digit shortcut while typing in a text field", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    await screen.findByText("BODY");
    await user.click(screen.getByRole("button", { name: /open body/i }));
    const titleInput = await screen.findByPlaceholderText(/new conversation title/i);

    await user.click(titleInput);
    await user.keyboard("2");

    // Still on BODY, not navigated to BUILD via the digit shortcut.
    expect(screen.getByRole("heading", { name: "BODY" })).toBeInTheDocument();
    expect(titleInput).toHaveValue("2");
  });

  it("Cmd+K opens the command palette, and selecting an action navigates", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    await screen.findByText("BODY");
    await user.keyboard("{Meta>}k{/Meta}");

    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/type a command/i), "PATH");
    await user.click(screen.getByRole("button", { name: "Go to PATH" }));

    expect(await screen.findByRole("heading", { name: "PATH" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /command palette/i })).not.toBeInTheDocument();
  });

  it("Escape closes the command palette without navigating", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    await screen.findByText("BODY");
    await user.keyboard("{Meta>}k{/Meta}");
    expect(await screen.findByRole("dialog", { name: /command palette/i })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: /command palette/i })).not.toBeInTheDocument();
    expect(screen.getByText("BODY")).toBeInTheDocument();
  });

  it("Cmd+Shift+E opens Data Management (the export workflow)", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    await screen.findByText("BODY");
    await user.keyboard("{Meta>}{Shift>}E{/Shift}{/Meta}");

    expect(await screen.findByText(/JARVIS_DATA_DIR/i)).toBeInTheDocument();
  });

  it("Cmd+Shift+F opens Recall — shift-modified so it never collides with the browser's own Cmd+F", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "searchRecall").mockResolvedValue({
      query: "",
      results: [],
      total_considered: 0,
      limit: 20,
      offset: 0,
      has_more: false,
      partial_failures: [],
    });
    render(<App />);

    await screen.findByText("BODY");
    await user.keyboard("{Meta>}{Shift>}F{/Shift}{/Meta}");

    expect(await screen.findByRole("heading", { name: "Recall" })).toBeInTheDocument();
  });
});
