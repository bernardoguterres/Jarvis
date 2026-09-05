import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Home from "./views/Home";
import * as api from "./api";
import type { Domain, HomeBriefing } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness and health.", created_at: "", updated_at: "" },
  { id: "2", slug: "mind", name: "MIND", description: "Mood and habits.", created_at: "", updated_at: "" },
  { id: "3", slug: "people", name: "PEOPLE", description: "Relationships.", created_at: "", updated_at: "" },
  { id: "4", slug: "path", name: "PATH", description: "Career and education.", created_at: "", updated_at: "" },
  { id: "5", slug: "build", name: "BUILD", description: "Projects and code.", created_at: "", updated_at: "" },
  { id: "6", slug: "life", name: "LIFE", description: "Calendar and finances.", created_at: "", updated_at: "" },
];

const EMPTY_BRIEFING: HomeBriefing = {
  generated_at: "2026-08-29T09:00:00Z",
  items: [],
  sources: [],
  include_body: true,
  include_mind: false,
  include_people: false,
  acknowledged_and_snoozed: [],
  mission_focus: [],
};

const POPULATED_BRIEFING: HomeBriefing = {
  generated_at: "2026-08-29T09:00:00Z",
  items: [
    {
      id: "life_task:abc123",
      category: "now",
      tone: "attention",
      title: "Renew passport",
      subtitle: "Due 2026-08-20",
      domain_slug: "life",
      source_type: "life_task",
      source_ids: ["abc123"],
      reason: "overdue since 2026-08-20",
      source_timestamp: "2026-08-15T09:00:00Z",
      freshness: "current",
      classification: "factual",
      link_target: "domain:life",
      fingerprint: "fp-passport-1",
      change_state: "new",
      pinned: false,
      pin_rank: null,
    },
    {
      id: "action_proposal:pending",
      category: "watch",
      tone: "attention",
      title: "2 action proposals awaiting your review",
      subtitle: null,
      domain_slug: null,
      source_type: "action_proposal",
      source_ids: ["a1", "a2"],
      reason: "Proposed but not yet approved/executed",
      source_timestamp: null,
      freshness: "current",
      classification: "factual",
      link_target: "actions_centre",
      fingerprint: "fp-actions-1",
      change_state: "ongoing",
      pinned: false,
      pin_rank: null,
    },
  ],
  sources: [{ source_type: "calendar", status: "unavailable", detail: "rate_limited", last_updated: null }],
  include_body: true,
  include_mind: false,
  include_people: false,
  acknowledged_and_snoozed: [],
  mission_focus: [],
};

function baseMocks() {
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Home — situational briefing (Phase 12A)", () => {
  it("shows a truthful empty state rather than manufacturing advice", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(EMPTY_BRIEFING);

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);

    expect(await screen.findByText("No immediate items.")).toBeInTheDocument();
  });

  it("shows a truthful stale/unavailable message when the briefing fetch itself fails", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockRejectedValue(new Error("network error"));

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);

    expect(await screen.findByText(/could not load the situational briefing/i)).toBeInTheDocument();
  });

  it("renders real items with category badges, source-unavailable note, and navigates on click", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(POPULATED_BRIEFING);
    const onNavigate = vi.fn();

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={onNavigate} health="ok" />);

    expect(await screen.findByText("Renew passport")).toBeInTheDocument();
    expect(screen.getByText("2 action proposals awaiting your review")).toBeInTheDocument();
    expect(screen.getByText("NOW")).toBeInTheDocument();
    expect(screen.getByText("WATCH")).toBeInTheDocument();
    expect(screen.getByText(/some sources are unavailable/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /renew passport/i }));
    expect(onNavigate).toHaveBeenCalledWith("domain:life");

    await user.click(screen.getByRole("button", { name: /2 action proposals/i }));
    expect(onNavigate).toHaveBeenCalledWith("actions_centre");
  });

  it("never navigates for an item with no link_target", async () => {
    baseMocks();
    const briefingNoLink: HomeBriefing = {
      ...POPULATED_BRIEFING,
      items: [{ ...POPULATED_BRIEFING.items[0], link_target: null }],
    };
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingNoLink);
    const onNavigate = vi.fn();

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={onNavigate} health="ok" />);

    const button = await screen.findByRole("button", { name: /renew passport/i });
    expect(button).toBeDisabled();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("refresh re-fetches the briefing deterministically (no model call involved)", async () => {
    const user = userEvent.setup();
    baseMocks();
    const fetchSpy = vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(EMPTY_BRIEFING);

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("No immediate items.");
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /^refresh$/i }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
  });

  it("Discuss with Jarvis sends the briefing into a real general conversation turn, labeled as a model response", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(POPULATED_BRIEFING);
    vi.spyOn(api, "createGeneralConversation").mockResolvedValue({
      id: "conv-1",
      domain_id: null,
      title: "Situational briefing discussion",
      created_at: "",
      updated_at: "",
      archived_at: null,
    });
    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockResolvedValue({
      run_id: "run-1",
      status: "succeeded",
      user_message: { id: "u1", conversation_id: "conv-1", role: "user", content: "x", created_at: "", model_used: null },
      assistant_message: {
        id: "a1",
        conversation_id: "conv-1",
        role: "assistant",
        content: "Let's tackle the passport renewal first.",
        created_at: "",
        model_used: "fake-model",
      },
      provider: "hermes",
      model: "fake-model",
      latency_ms: 10,
      usage: null,
      context_snapshot_id: null,
      error: null,
    });

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");

    await user.click(screen.getByRole("button", { name: /discuss with jarvis/i }));

    expect(await screen.findByText(/let's tackle the passport renewal first/i)).toBeInTheDocument();
    expect(screen.getByText(/jarvis \(model response\)/i)).toBeInTheDocument();
    expect(sendTurnSpy).toHaveBeenCalledWith("conv-1", expect.stringContaining("Renew passport"), expect.any(String), []);
  });

  it("Discuss with Jarvis is disabled when there is nothing to discuss", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(EMPTY_BRIEFING);

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("No immediate items.");

    expect(screen.getByRole("button", { name: /discuss with jarvis/i })).toBeDisabled();
  });
});

describe("Home — briefing continuity (Phase 12B)", () => {
  it("shows a distinct change-state badge alongside the category badge, never color alone", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(POPULATED_BRIEFING);

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");

    expect(screen.getByText("NEW")).toBeInTheDocument();
    expect(screen.getByText("ONGOING")).toBeInTheDocument();
  });

  it("Refresh button explicitly requests the home_refresh trigger", async () => {
    const user = userEvent.setup();
    baseMocks();
    const fetchSpy = vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(EMPTY_BRIEFING);

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("No immediate items.");
    expect(fetchSpy).toHaveBeenCalledWith("home_view");

    await user.click(screen.getByRole("button", { name: /^refresh$/i }));
    await waitFor(() => expect(fetchSpy).toHaveBeenLastCalledWith("home_refresh"));
  });

  it("Acknowledge hides the item — a local presentation change, not a source mutation", async () => {
    const user = userEvent.setup();
    baseMocks();
    const fetchSpy = vi
      .spyOn(api, "fetchHomeBriefing")
      .mockResolvedValueOnce(POPULATED_BRIEFING)
      .mockResolvedValueOnce(EMPTY_BRIEFING);
    const ackSpy = vi
      .spyOn(api, "acknowledgeBriefingItem")
      .mockResolvedValue({ stable_key: "life_task:abc123", suppressed: "acknowledged", message: "Hidden." });

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");

    await user.click(screen.getAllByRole("button", { name: /^acknowledge$/i })[0]);

    expect(ackSpy).toHaveBeenCalledWith("life_task:abc123");
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText("Renew passport")).not.toBeInTheDocument());
  });

  it("Snooze duration menu is a real accessible disclosure and calls the API with the chosen duration", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(POPULATED_BRIEFING);
    const snoozeSpy = vi
      .spyOn(api, "snoozeBriefingItem")
      .mockResolvedValue({ stable_key: "life_task:abc123", suppressed: "snoozed", message: "Hidden for 1 hour." });

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");

    // The snooze duration list is a native <details> disclosure — matching
    // the project's existing .builder-surface pattern (docs/DECISIONS.md
    // D80), jsdom's queries reach its content directly regardless of the
    // native `open` toggle, which jsdom itself doesn't simulate on click.
    expect(screen.getAllByText("Snooze")[0].closest("details")).not.toBeNull();
    await user.click(screen.getAllByRole("button", { name: /^1 hour$/i })[0]);

    expect(snoozeSpy).toHaveBeenCalledWith("life_task:abc123", "1h");
  });

  it("resolved items never show Acknowledge/Snooze controls", async () => {
    baseMocks();
    const resolvedBriefing: HomeBriefing = {
      ...POPULATED_BRIEFING,
      items: [{ ...POPULATED_BRIEFING.items[0], change_state: "resolved" }],
    };
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(resolvedBriefing);

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");

    expect(screen.getByText("RESOLVED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^acknowledge$/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Snooze")).not.toBeInTheDocument();
  });

  it("shows an unobtrusive Acknowledged & snoozed history with a working Restore", async () => {
    const user = userEvent.setup();
    baseMocks();
    const briefingWithHistory: HomeBriefing = {
      ...EMPTY_BRIEFING,
      acknowledged_and_snoozed: [
        {
          stable_key: "life_task:abc123",
          kind: "acknowledged",
          title: "Renew passport",
          subtitle: "Due 2026-08-20",
          domain_slug: "life",
          link_target: "domain:life",
          since: "2026-08-29T08:00:00Z",
          until: null,
          duration_key: null,
        },
      ],
    };
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValueOnce(briefingWithHistory).mockResolvedValueOnce(EMPTY_BRIEFING);
    const restoreSpy = vi
      .spyOn(api, "restoreBriefingItem")
      .mockResolvedValue({ stable_key: "life_task:abc123", suppressed: null, message: "Restored." });

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText(/acknowledged & snoozed/i);

    await user.click(screen.getByText(/acknowledged & snoozed/i));
    expect(screen.getByText(/only changes what this briefing shows/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^restore$/i }));
    expect(restoreSpy).toHaveBeenCalledWith("life_task:abc123");
  });

  it("never shows the acknowledged/snoozed history section when nothing is hidden", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(POPULATED_BRIEFING);
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");
    expect(screen.queryByText(/acknowledged & snoozed/i)).not.toBeInTheDocument();
  });

  it("Discuss with Jarvis includes each item's change-state label", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(POPULATED_BRIEFING);
    vi.spyOn(api, "createGeneralConversation").mockResolvedValue({
      id: "conv-1", domain_id: null, title: "Situational briefing discussion", created_at: "", updated_at: "",
      archived_at: null,
    });
    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockResolvedValue({
      run_id: "run-1", status: "succeeded",
      user_message: { id: "u1", conversation_id: "conv-1", role: "user", content: "x", created_at: "", model_used: null },
      assistant_message: {
        id: "a1", conversation_id: "conv-1", role: "assistant", content: "Noted.", created_at: "", model_used: "fake",
      },
      provider: "hermes", model: "fake", latency_ms: 5, usage: null, context_snapshot_id: null, error: null,
    });

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");
    await user.click(screen.getByRole("button", { name: /discuss with jarvis/i }));

    await waitFor(() => expect(sendTurnSpy).toHaveBeenCalled());
    const sentText = sendTurnSpy.mock.calls[0][1];
    expect(sentText).toContain("NOW/NEW");
    expect(sentText).toContain("WATCH/ONGOING");
  });
});
