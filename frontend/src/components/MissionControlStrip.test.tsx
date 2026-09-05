import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MissionControlStrip from "./MissionControlStrip";
import type { FocusSession, MissionCandidate, MissionCandidates } from "../api";

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

function candidates(overrides: Partial<MissionCandidates> = {}): MissionCandidates {
  return {
    recommended: candidate(),
    alternatives: [],
    watch: [],
    generated_at: "2026-08-29T09:00:00Z",
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

const noop = () => {};

function baseProps() {
  return {
    candidates: null,
    candidatesLoading: false,
    candidatesError: null,
    currentMission: null,
    currentMissionLoading: false,
    currentMissionError: null,
    onStartFromCandidate: noop,
    onStartManual: noop,
    onPause: noop,
    onResume: noop,
    onComplete: noop,
    onAbandon: noop,
    busy: false,
    actionError: null,
  };
}

describe("MissionControlStrip — no active mission", () => {
  it("shows a truthful empty state when there are no candidates", () => {
    render(<MissionControlStrip {...baseProps()} />);
    expect(screen.getByText(/no suggested focus candidates/i)).toBeInTheDocument();
  });

  it("shows a truthful loading state", () => {
    render(<MissionControlStrip {...baseProps()} candidatesLoading currentMissionLoading />);
    expect(screen.getByText(/loading current mission/i)).toBeInTheDocument();
  });

  it("shows a truthful error state for the candidates fetch", () => {
    render(<MissionControlStrip {...baseProps()} candidatesError="Could not load focus suggestions." />);
    expect(screen.getByRole("alert")).toHaveTextContent(/could not load focus suggestions/i);
  });

  it("shows a truthful error state for the current-mission fetch", () => {
    render(<MissionControlStrip {...baseProps()} currentMissionError="Could not load the current focus session." />);
    expect(screen.getByRole("alert")).toHaveTextContent(/could not load the current focus session/i);
  });

  it("phrases the recommended candidate as a suggestion, never a claim of certainty", () => {
    render(<MissionControlStrip {...baseProps()} candidates={candidates()} />);
    expect(screen.getByText(/suggested from current information/i)).toBeInTheDocument();
    expect(screen.getByText("Renew passport")).toBeInTheDocument();
    expect(screen.getByText("Due in 3 days")).toBeInTheDocument();
  });

  it("shows up to two alternatives alongside the recommended candidate", () => {
    render(
      <MissionControlStrip
        {...baseProps()}
        candidates={candidates({
          alternatives: [candidate({ stable_key: "b", title: "Second thing" }), candidate({ stable_key: "c", title: "Third thing" })],
        })}
      />,
    );
    expect(screen.getByText("Renew passport")).toBeInTheDocument();
    expect(screen.getByText("Second thing")).toBeInTheDocument();
    expect(screen.getByText("Third thing")).toBeInTheDocument();
  });

  it("shows WATCH items separately, behind a disclosure, never mixed into the candidate list", () => {
    render(
      <MissionControlStrip
        {...baseProps()}
        candidates={candidates({ watch: [candidate({ stable_key: "w", title: "Watch item" })] })}
      />,
    );
    expect(screen.getByText(/1 item to watch/i)).toBeInTheDocument();
    expect(screen.getByText("Watch item")).toBeInTheDocument();
  });

  it("marks the source as unavailable/stale truthfully rather than hiding it", () => {
    render(<MissionControlStrip {...baseProps()} candidates={candidates({ recommended: candidate({ freshness: "unavailable" }) })} />);
    expect(screen.getByText("unavailable")).toBeInTheDocument();
  });

  it("starting from a candidate opens a duration picker, then calls onStartFromCandidate with the chosen duration", async () => {
    const user = userEvent.setup();
    const onStartFromCandidate = vi.fn();
    render(<MissionControlStrip {...baseProps()} candidates={candidates()} onStartFromCandidate={onStartFromCandidate} />);

    await user.click(screen.getByRole("button", { name: /renew passport/i }));
    const confirm = screen.getByRole("group", { name: /start focus on renew passport/i });
    await user.click(within(confirm).getByRole("button", { name: "45 min" }));
    await user.click(within(confirm).getByRole("button", { name: /start \(45 min\)/i }));

    expect(onStartFromCandidate).toHaveBeenCalledWith(expect.objectContaining({ title: "Renew passport" }), 45);
  });

  it("can back out of a pending candidate via 'Choose another'", async () => {
    const user = userEvent.setup();
    const onStartFromCandidate = vi.fn();
    render(<MissionControlStrip {...baseProps()} candidates={candidates()} onStartFromCandidate={onStartFromCandidate} />);
    await user.click(screen.getByRole("button", { name: /renew passport/i }));
    await user.click(screen.getByRole("button", { name: /choose another/i }));
    expect(screen.queryByRole("group", { name: /start focus on renew passport/i })).not.toBeInTheDocument();
    expect(onStartFromCandidate).not.toHaveBeenCalled();
  });

  it("a manual/custom focus session requires a title and calls onStartManual with the domain and duration", async () => {
    const user = userEvent.setup();
    const onStartManual = vi.fn();
    render(<MissionControlStrip {...baseProps()} onStartManual={onStartManual} />);

    await user.click(screen.getByRole("button", { name: /start a custom focus session/i }));
    const submit = screen.getByRole("button", { name: /start focus session/i });
    await user.click(submit);
    expect(onStartManual).not.toHaveBeenCalled(); // empty title never submits

    await user.type(screen.getByLabelText(/what are you focusing on/i), "Write project notes");
    await user.click(within(screen.getByRole("radiogroup", { name: "Domain" })).getByRole("radio", { name: /build/i }));
    await user.click(screen.getByRole("button", { name: "60 min" }));
    await user.click(submit);

    expect(onStartManual).toHaveBeenCalledWith("Write project notes", "build", 60);
  });
});

describe("MissionControlStrip — active mission", () => {
  it("renders title, domain, status, and target duration", () => {
    render(<MissionControlStrip {...baseProps()} currentMission={session()} />);
    expect(screen.getByText("Renew passport")).toBeInTheDocument();
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
    expect(screen.getByText(/25 min target/i)).toBeInTheDocument();
    expect(screen.getByText(/source: renew passport/i)).toBeInTheDocument();
  });

  it("moves keyboard/screen-reader focus onto its own heading when a new session mounts — regression for the real-Mac acceptance defect where starting a mission silently dropped focus back to <body>", () => {
    render(<MissionControlStrip {...baseProps()} currentMission={session()} />);
    expect(screen.getByText("Renew passport")).toHaveFocus();
  });

  it("does not steal focus away on an ordinary re-render of the same session (e.g. the live timer tick)", () => {
    const { rerender } = render(<MissionControlStrip {...baseProps()} currentMission={session({ elapsed_seconds: 0 })} />);
    const heading = screen.getByText("Renew passport");
    expect(heading).toHaveFocus();
    (document.activeElement as HTMLElement)?.blur();
    rerender(<MissionControlStrip {...baseProps()} currentMission={session({ elapsed_seconds: 5 })} />);
    expect(heading).not.toHaveFocus();
  });

  it("shows Pause (not Resume) while active, and never conveys status by color alone", () => {
    render(<MissionControlStrip {...baseProps()} currentMission={session({ status: "active" })} />);
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
    // The status is a real text label ("ACTIVE"), not merely a color swatch.
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
  });

  it("shows Resume (not Pause) while paused", () => {
    render(<MissionControlStrip {...baseProps()} currentMission={session({ status: "paused", paused_at: "2026-08-29T09:10:00Z" })} />);
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(screen.getByText("PAUSED")).toBeInTheDocument();
  });

  it("Pause/Resume/Abandon call their handlers directly", async () => {
    const user = userEvent.setup();
    const onPause = vi.fn();
    render(<MissionControlStrip {...baseProps()} currentMission={session({ status: "active" })} onPause={onPause} />);
    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(onPause).toHaveBeenCalledTimes(1);
  });

  it("Abandon calls onAbandon directly, with no separate confirmation form", async () => {
    const user = userEvent.setup();
    const onAbandon = vi.fn();
    render(<MissionControlStrip {...baseProps()} currentMission={session()} onAbandon={onAbandon} />);
    await user.click(screen.getByRole("button", { name: "Abandon" }));
    expect(onAbandon).toHaveBeenCalledTimes(1);
  });

  it("Complete opens an optional note form and submits trimmed notes (or null) via onComplete", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    render(<MissionControlStrip {...baseProps()} currentMission={session()} onComplete={onComplete} />);

    await user.click(screen.getByRole("button", { name: "Complete" }));
    await user.click(screen.getByRole("button", { name: /mark complete/i }));
    expect(onComplete).toHaveBeenCalledWith(null, null);

    onComplete.mockClear();
    await user.click(screen.getByRole("button", { name: "Complete" }));
    await user.type(screen.getByLabelText(/completion note/i), "  Filed the form  ");
    await user.type(screen.getByLabelText(/what changed/i), "Application submitted");
    await user.click(screen.getByRole("button", { name: /mark complete/i }));
    expect(onComplete).toHaveBeenCalledWith("Filed the form", "Application submitted");
  });

  it("disables lifecycle controls while an action is busy, so a double-click can't double-submit", () => {
    render(<MissionControlStrip {...baseProps()} currentMission={session()} busy />);
    expect(screen.getByRole("button", { name: "Pause" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Complete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Abandon" })).toBeDisabled();
  });

  it("shows an action error truthfully without discarding the active session view", () => {
    render(<MissionControlStrip {...baseProps()} currentMission={session()} actionError="Could not pause this focus session." />);
    expect(screen.getByRole("alert")).toHaveTextContent(/could not pause this focus session/i);
    expect(screen.getByText("Renew passport")).toBeInTheDocument();
  });

  it("carries a coarse, non-spammy screen-reader announcement separate from the live-updating visual timer", () => {
    // started_at 125 real seconds ago — the component re-derives elapsed
    // time from persisted timestamps against the wall clock, never from a
    // static elapsed_seconds field, so the fixture must reflect that.
    const startedAt = new Date(Date.now() - 125_000).toISOString();
    const { container } = render(<MissionControlStrip {...baseProps()} currentMission={session({ started_at: startedAt })} />);
    const live = container.querySelector('[aria-live="polite"]');
    expect(live).not.toBeNull();
    expect(live).toHaveTextContent(/2 minutes elapsed, active/i);
    // The fast-ticking numeric display is explicitly NOT the aria-live region.
    const timer = container.querySelector(".mc-active-timer");
    expect(timer?.getAttribute("aria-live")).toBe("off");
  });
});
