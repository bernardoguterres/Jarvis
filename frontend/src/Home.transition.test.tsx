import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Home domain navigation — no artificial delay (jsdom has no View Transitions, so this exercises the fallback path)", () => {
  it("a click opens the destination domain in the same synchronous tick — no setTimeout advance needed", async () => {
    baseMocks();
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    render(<App />);

    const bodyButton = await screen.findByRole("button", { name: /open body/i });
    fireEvent.click(bodyButton);

    // Synchronous: no `await waitFor`/timer advance required at all.
    expect(screen.getByRole("heading", { name: "BODY" })).toBeInTheDocument();
    // Other app machinery (health polling, etc.) legitimately uses
    // setTimeout/setInterval — the regression this guards against is
    // specifically a navigation delay, so assert none of the old 220ms/
    // 260ms artificial-wait durations were used, rather than that no
    // timer anywhere in the app ever fires.
    expect(setTimeoutSpy.mock.calls.map((call) => call[1])).not.toContain(220);
    expect(setTimeoutSpy.mock.calls.map((call) => call[1])).not.toContain(260);
  });

  it("a digit shortcut opens the destination domain in the same synchronous tick", async () => {
    baseMocks();
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    render(<App />);

    await screen.findByText("BODY");
    fireEvent.keyDown(window, { key: "2" });

    expect(screen.getByRole("heading", { name: "BUILD" })).toBeInTheDocument();
    // Other app machinery (health polling, etc.) legitimately uses
    // setTimeout/setInterval — the regression this guards against is
    // specifically a navigation delay, so assert none of the old 220ms/
    // 260ms artificial-wait durations were used, rather than that no
    // timer anywhere in the app ever fires.
    expect(setTimeoutSpy.mock.calls.map((call) => call[1])).not.toContain(220);
    expect(setTimeoutSpy.mock.calls.map((call) => call[1])).not.toContain(260);
  });

  it("rapid re-activation of a domain node never crashes and never leaves two destinations rendered (double-activation protection)", async () => {
    baseMocks();
    render(<App />);

    const bodyButton = await screen.findByRole("button", { name: /open body/i });
    fireEvent.click(bodyButton);
    // By the time this second click is dispatched, Home has already
    // unmounted (the swap is synchronous on the no-View-Transitions
    // fallback path) — this asserts that's genuinely true, not just
    // hoped for, and that nothing throws in the process.
    expect(screen.queryByRole("button", { name: /open body/i })).not.toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "BODY" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { name: "BODY" })).toHaveLength(1);
  });

  it("Back to Jarvis reverses the transition and returns to Home with all six domains visible again", async () => {
    baseMocks();
    render(<App />);

    const bodyButton = await screen.findByRole("button", { name: /open body/i });
    fireEvent.click(bodyButton);
    expect(await screen.findByRole("heading", { name: "BODY" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /back to jarvis/i }));

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "BODY" })).not.toBeInTheDocument();
    });
    for (const domain of DOMAINS) {
      expect(await screen.findByText(domain.name)).toBeInTheDocument();
    }
  });
});
