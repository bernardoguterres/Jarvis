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

describe("App: focus after switching views", () => {
  it("moves focus to the domain heading when a domain node is activated with the keyboard", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    const node = await screen.findByRole("button", { name: /open build/i });
    node.focus();
    await user.keyboard("{Enter}");

    const heading = await screen.findByRole("heading", { level: 1, name: "BUILD" });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it("moves focus to the domain heading after a digit shortcut", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    await screen.findByRole("button", { name: /open body/i });
    await user.keyboard("1");

    const heading = await screen.findByRole("heading", { level: 1, name: "BODY" });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it("returns focus to the domain's node when going back to Home", async () => {
    const user = userEvent.setup();
    baseMocks();
    render(<App />);

    await screen.findByRole("button", { name: /open build/i });
    await user.keyboard("2");
    await screen.findByRole("heading", { level: 1, name: "BUILD" });

    await user.click(screen.getByRole("button", { name: /back to jarvis/i }));

    const node = await screen.findByRole("button", { name: /open build/i });
    await waitFor(() => expect(node).toHaveFocus());
  });

  it("does not move focus on first load", async () => {
    baseMocks();
    render(<App />);

    await screen.findByRole("button", { name: /open body/i });
    expect(document.body).toHaveFocus();
  });
});
