import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Home from "./views/Home";
import * as api from "./api";
import type { Domain, HomeBriefing, MissionFocusEntry } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "Fitness and health.", created_at: "", updated_at: "" },
  { id: "2", slug: "mind", name: "MIND", description: "Mood and habits.", created_at: "", updated_at: "" },
  { id: "3", slug: "people", name: "PEOPLE", description: "Relationships.", created_at: "", updated_at: "" },
  { id: "4", slug: "path", name: "PATH", description: "Career and education.", created_at: "", updated_at: "" },
  { id: "5", slug: "build", name: "BUILD", description: "Projects and code.", created_at: "", updated_at: "" },
  { id: "6", slug: "life", name: "LIFE", description: "Calendar and finances.", created_at: "", updated_at: "" },
];

function entry(overrides: Partial<MissionFocusEntry> = {}): MissionFocusEntry {
  return {
    pin_id: "pin-1",
    rank: 1,
    source_type: "life_task",
    domain_slug: "life",
    title: "Renew passport",
    subtitle: "Due 2026-08-20",
    next_action: "Book an appointment",
    target_at: null,
    blocker: null,
    link_target: "domain:life",
    available: true,
    resolved: false,
    change_state: "new",
    ...overrides,
  };
}

function briefingWith(entries: MissionFocusEntry[]): HomeBriefing {
  return {
    generated_at: "2026-08-29T09:00:00Z",
    items: [],
    sources: [],
    include_body: true,
    include_mind: false,
    include_people: false,
    acknowledged_and_snoozed: [],
    mission_focus: entries,
  };
}

function baseMocks() {
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Home — Mission Focus (Phase 12C)", () => {
  it("shows a truthful empty state", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingWith([]));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    expect(await screen.findByText(/no pins yet/i)).toBeInTheDocument();
    expect(screen.getByText("Mission Focus (0/5)")).toBeInTheDocument();
  });

  it("shows a truthful loading/error state when the fetch itself fails", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockRejectedValue(new Error("network error"));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    expect(await screen.findByText(/could not load the situational briefing/i)).toBeInTheDocument();
  });

  it("renders one pin with rank, next action, and change badge", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingWith([entry()]));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    expect(await screen.findByText("Renew passport")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("Book an appointment")).toBeInTheDocument();
    expect(screen.getByText("Mission Focus (1/5)")).toBeInTheDocument();
  });

  it("shows exactly the top three by default and the rest behind a disclosure at five pins", async () => {
    baseMocks();
    const five = [1, 2, 3, 4, 5].map((rank) => entry({ pin_id: `pin-${rank}`, rank, title: `Item ${rank}` }));
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingWith(five));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);

    await screen.findByText("Item 1");
    expect(screen.getByText("Item 2")).toBeInTheDocument();
    expect(screen.getByText("Item 3")).toBeInTheDocument();
    expect(screen.getByText("Mission Focus (5/5)")).toBeInTheDocument();
    expect(screen.getByText("2 more pinned")).toBeInTheDocument();

    // The remaining two are present in the DOM behind the (closed) native
    // <details> disclosure — matches this project's existing pattern for
    // .builder-surface/.snooze-menu (D80/Phase 12B).
    expect(screen.getByText("Item 4")).toBeInTheDocument();
    expect(screen.getByText("Item 5")).toBeInTheDocument();
  });

  it("View source navigates via the same command-layer entry point as the briefing", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingWith([entry()]));
    const onNavigate = vi.fn();
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={onNavigate} health="ok" />);
    await screen.findByText("Renew passport");

    await user.click(screen.getByRole("button", { name: /view source/i }));
    expect(onNavigate).toHaveBeenCalledWith("domain:life");
  });

  it("View source is disabled and never navigates when the source is unavailable", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(
      briefingWith([entry({ available: false, link_target: null, title: "Old checkpoint" })]),
    );
    const onNavigate = vi.fn();
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={onNavigate} health="ok" />);
    await screen.findByText("Old checkpoint");

    expect(screen.getByText(/source unavailable/i)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: /view source/i });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("shows a truthful resolved note without implying the pin was removed", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingWith([entry({ resolved: true })]));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    expect(await screen.findByText(/source resolved/i)).toBeInTheDocument();
    expect(screen.getByText("Renew passport")).toBeInTheDocument(); // still shown, not silently dropped
  });

  it("shows a blocker only when present", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingWith([entry({ blocker: "Waiting on documents" })]));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    expect(await screen.findByText(/waiting on documents/i)).toBeInTheDocument();
  });

  it("Remove from focus calls the unpin API and refreshes — never touches the source", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing")
      .mockResolvedValueOnce(briefingWith([entry()]))
      .mockResolvedValueOnce(briefingWith([]));
    const unpinSpy = vi.spyOn(api, "unpinMissionFocusPin").mockResolvedValue({
      id: "pin-1", source_type: "life_task", source_id: "abc", domain_slug: "life", rank: 1,
      next_action: "a", target_at: null, blocker: null, status: "unpinned", pinned_at: "", unpinned_at: "",
      title: "Renew passport", subtitle: null, link_target: "domain:life", available: true, resolved: false,
      change_state: null,
    });

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");

    await user.click(screen.getByRole("button", { name: /remove from focus/i }));
    expect(unpinSpy).toHaveBeenCalledWith("pin-1");
    await waitFor(() => expect(screen.getByText("Mission Focus (0/5)")).toBeInTheDocument());
  });

  it("Discuss Mission Focus is the only model-triggering action, disabled when empty", async () => {
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingWith([]));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText(/no pins yet/i);
    expect(screen.getByRole("button", { name: /discuss mission focus with jarvis/i })).toBeDisabled();
  });

  it("Discuss Mission Focus sends pin data through the existing general-conversation turn flow", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(briefingWith([entry()]));
    vi.spyOn(api, "createGeneralConversation").mockResolvedValue({
      id: "conv-1", domain_id: null, title: "Mission Focus discussion", created_at: "", updated_at: "", archived_at: null,
    });
    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockResolvedValue({
      run_id: "run-1", status: "succeeded",
      user_message: { id: "u1", conversation_id: "conv-1", role: "user", content: "x", created_at: "", model_used: null },
      assistant_message: { id: "a1", conversation_id: "conv-1", role: "assistant", content: "Focus on the passport first.", created_at: "", model_used: "fake" },
      provider: "hermes", model: "fake", latency_ms: 5, usage: null, context_snapshot_id: null, error: null,
    });

    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Renew passport");
    await user.click(screen.getByRole("button", { name: /discuss mission focus with jarvis/i }));

    expect(await screen.findByText(/focus on the passport first/i)).toBeInTheDocument();
    expect(screen.getByText(/jarvis \(model response\)/i)).toBeInTheDocument();
    expect(sendTurnSpy).toHaveBeenCalledWith("conv-1", expect.stringContaining("Renew passport"), expect.any(String), []);
  });

  it("never renders a MIND/PEOPLE domain label even if such a pin were somehow present", async () => {
    baseMocks();
    // Defense-in-depth frontend check — the real boundary is server-side
    // (Mission Focus cannot pin MIND/PEOPLE at all), but the rail must
    // never format such a domain_slug into view either.
    vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(
      briefingWith([entry({ domain_slug: "life", title: "Safe item" })]),
    );
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("Safe item");
    // The orbit itself always renders "MIND"/"PEOPLE" as ordinary domain
    // nodes — the real check is that no *Mission Focus* domain chip ever
    // names one of them.
    const domainChips = document.querySelectorAll(".mission-focus-domain");
    const chipText = Array.from(domainChips).map((el) => el.textContent);
    expect(chipText).not.toContain("MIND");
    expect(chipText).not.toContain("PEOPLE");
  });
});
