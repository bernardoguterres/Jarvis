import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Home from "./views/Home";
import * as api from "./api";
import type { Domain, FocusSession, HomeBriefing, MissionCandidate, MissionCandidates } from "./api";

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

function candidate(overrides: Partial<MissionCandidate> = {}): MissionCandidate {
  return {
    stable_key: "life_task:abc",
    domain_slug: "life",
    title: "Renew passport",
    subtitle: null,
    reason: "Due in 3 days",
    source_type: "life_task",
    source_ids: ["abc"],
    freshness: "current",
    link_target: "domain:life",
    ...overrides,
  };
}

function session(overrides: Partial<FocusSession> = {}): FocusSession {
  return {
    id: "session-1",
    title: "Renew passport",
    domain_slug: "life",
    source_type: "life_task",
    source_id: "abc",
    source_title_snapshot: "Renew passport",
    status: "active",
    target_duration_minutes: 25,
    started_at: "2026-08-29T09:00:00Z",
    paused_at: null,
    accumulated_paused_seconds: 0,
    completed_at: null,
    completion_note: null,
    what_changed_note: null,
    abandoned_reason: null,
    elapsed_seconds: 0,
    remaining_seconds: 1500,
    created_at: "2026-08-29T09:00:00Z",
    updated_at: "2026-08-29T09:00:00Z",
    ...overrides,
  };
}

const NO_CANDIDATES: MissionCandidates = { recommended: null, alternatives: [], watch: [], generated_at: "2026-08-29T09:00:00Z" };

function baseMocks() {
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
  vi.spyOn(api, "fetchHomeBriefing").mockResolvedValue(EMPTY_BRIEFING);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Home — Mission Control integration", () => {
  it("shows the recommended candidate when there is no active mission", async () => {
    baseMocks();
    vi.spyOn(api, "fetchCurrentMission").mockResolvedValue({ session: null });
    vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue({
      recommended: candidate(),
      alternatives: [],
      watch: [],
      generated_at: "2026-08-29T09:00:00Z",
    });
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    expect(await screen.findByText("Mission Control")).toBeInTheDocument();
    expect(await screen.findByText("Renew passport")).toBeInTheDocument();
    expect(screen.getByText(/suggested from current information/i)).toBeInTheDocument();
  });

  it("shows a truthful empty state when there is no active mission and no candidates", async () => {
    baseMocks();
    vi.spyOn(api, "fetchCurrentMission").mockResolvedValue({ session: null });
    vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue(NO_CANDIDATES);
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    expect(await screen.findByText(/no suggested focus candidates/i)).toBeInTheDocument();
  });

  it("renders the active mission and never re-fetches candidates while one is active", async () => {
    baseMocks();
    vi.spyOn(api, "fetchCurrentMission").mockResolvedValue({ session: session() });
    const candidatesSpy = vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue(NO_CANDIDATES);
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    expect(await screen.findByText("ACTIVE")).toBeInTheDocument();
    expect(candidatesSpy).not.toHaveBeenCalled();
  });

  it("starting a mission from a candidate calls startMission with the source reference and default duration", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchCurrentMission").mockResolvedValue({ session: null });
    vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue({
      recommended: candidate(),
      alternatives: [],
      watch: [],
      generated_at: "2026-08-29T09:00:00Z",
    });
    const startSpy = vi.spyOn(api, "startMission").mockResolvedValue(session());
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);

    await user.click(await screen.findByRole("button", { name: /renew passport/i }));
    await user.click(screen.getByRole("button", { name: /start \(25 min\)/i }));

    await waitFor(() =>
      expect(startSpy).toHaveBeenCalledWith({
        source_type: "life_task",
        source_id: "abc",
        target_duration_minutes: 25,
      }),
    );
    expect(await screen.findByText("ACTIVE")).toBeInTheDocument();
  });

  it("pausing the active mission calls pauseMission with its id and reflects the new status", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchCurrentMission").mockResolvedValue({ session: session() });
    vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue(NO_CANDIDATES);
    const pauseSpy = vi.spyOn(api, "pauseMission").mockResolvedValue(session({ status: "paused", paused_at: "2026-08-29T09:10:00Z" }));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);

    await user.click(await screen.findByRole("button", { name: "Pause" }));
    expect(pauseSpy).toHaveBeenCalledWith("session-1");
    expect(await screen.findByText("PAUSED")).toBeInTheDocument();
  });

  it("completing the active mission calls completeMission and returns to the candidate view", async () => {
    const user = userEvent.setup();
    baseMocks();
    vi.spyOn(api, "fetchCurrentMission").mockResolvedValue({ session: session() });
    vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue(NO_CANDIDATES);
    const completeSpy = vi.spyOn(api, "completeMission").mockResolvedValue(session({ status: "completed" }));
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);

    await user.click(await screen.findByRole("button", { name: "Complete" }));
    await user.click(screen.getByRole("button", { name: /mark complete/i }));

    expect(completeSpy).toHaveBeenCalledWith("session-1", { completion_note: null, what_changed_note: null });
    expect(await screen.findByText(/no suggested focus candidates/i)).toBeInTheDocument();
  });

  it("refetches the current mission immediately on MISSION_CONTROL_REFRESH_EVENT, not just on the poll interval — regression for the real-Mac acceptance defect where a command-palette/voice focus_start left Home showing its stale prior state", async () => {
    baseMocks();
    const currentSpy = vi
      .spyOn(api, "fetchCurrentMission")
      .mockResolvedValueOnce({ session: null })
      .mockResolvedValueOnce({ session: session() });
    vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue(NO_CANDIDATES);
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);

    expect(await screen.findByText(/no suggested focus candidates/i)).toBeInTheDocument();
    expect(currentSpy).toHaveBeenCalledTimes(1);

    window.dispatchEvent(new Event(api.MISSION_CONTROL_REFRESH_EVENT));

    await waitFor(() => expect(currentSpy).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("ACTIVE")).toBeInTheDocument();
  });

  it("does not obstruct the six-domain orbit — all six domains still render alongside Mission Control", async () => {
    baseMocks();
    vi.spyOn(api, "fetchCurrentMission").mockResolvedValue({ session: session() });
    vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue(NO_CANDIDATES);
    render(<Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />);
    await screen.findByText("ACTIVE");
    for (const domain of DOMAINS) {
      expect(screen.getByRole("button", { name: new RegExp(domain.name, "i") })).toBeInTheDocument();
    }
  });
});
