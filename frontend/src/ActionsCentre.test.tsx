import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ActionsCentre from "./views/ActionsCentre";
import * as api from "./api";
import type { ActionProposal } from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
  // Phase 12C: Mission Focus's own fetch, not what any of these tests are
  // about — default it to a harmless empty state rather than letting an
  // unmocked network call resolve unpredictably.
  vi.spyOn(api, "fetchMissionFocus").mockResolvedValue({ active_pins: [], max_active_pins: 5, default_visible: 3 });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function makeProposal(overrides: Partial<ActionProposal> = {}): ActionProposal {
  return {
    id: "prop-1",
    capability_id: "memory.create",
    domain_id: null,
    permission_level: "confirm",
    arguments: { scope: "global", kind: "fact", title: "T", content: "c" },
    reason: "test reason",
    expected_effect: "Create a global memory titled 'T'.",
    payload_digest: "abc123",
    status: "proposed",
    source: "manual_proposal",
    confirmation_token: null,
    confirmation_expires_at: null,
    result: null,
    error_summary: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function byExactText(text: string) {
  return (_: string, el: Element | null) => el?.textContent === text;
}

/** A minimal stateful fake standing in for the backend — every mock reads
 * and writes the same mutable proposal object, so this test is immune to
 * exactly how many times the component happens to call listActionProposals
 * (e.g. on mount), unlike a queued mockResolvedValueOnce chain. */
function installFakeBackend(initial: ActionProposal) {
  let current = initial;
  vi.spyOn(api, "listActionProposals").mockImplementation(async () => [current]);
  vi.spyOn(api, "approveActionProposal").mockImplementation(async () => {
    current = { ...current, status: "approved", confirmation_token: "tok-123" };
    return current;
  });
  vi.spyOn(api, "denyActionProposal").mockImplementation(async () => {
    current = { ...current, status: "denied" };
    return current;
  });
  vi.spyOn(api, "executeActionProposal").mockImplementation(async () => {
    current = { ...current, status: "succeeded", result: { memory_item_id: "m1" } };
    return current;
  });
  return () => current;
}

describe("ActionsCentre", () => {
  it("lists a pending proposal and approves then executes it", async () => {
    const user = userEvent.setup();
    installFakeBackend(makeProposal());

    render(<ActionsCentre onBack={() => {}} />);
    expect(await screen.findByText(byExactText("memory.create · proposed"))).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^approve$/i }));
    expect(await screen.findByRole("button", { name: /^execute$/i })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^execute$/i }));
    expect(await screen.findByText(byExactText("memory.create · succeeded"))).toBeInTheDocument();
  });

  it("denies a pending proposal", async () => {
    const user = userEvent.setup();
    installFakeBackend(makeProposal());

    render(<ActionsCentre onBack={() => {}} />);
    await screen.findByText(byExactText("memory.create · proposed"));

    await user.click(screen.getByRole("button", { name: /^deny$/i }));
    expect(await screen.findByText(byExactText("memory.create · denied"))).toBeInTheDocument();
  });

  it("shows audit history on request", async () => {
    const user = userEvent.setup();
    const proposal = makeProposal({ status: "succeeded" });

    vi.spyOn(api, "listActionProposals").mockResolvedValue([proposal]);
    vi.spyOn(api, "getActionProposal").mockResolvedValue({
      proposal,
      audit_events: [
        { id: "e1", action_proposal_id: "prop-1", event_type: "proposed", detail: null, created_at: "2026-09-04T12:00:00" },
        { id: "e2", action_proposal_id: "prop-1", event_type: "succeeded", detail: null, created_at: "2026-09-04T12:05:00" },
      ],
    });

    render(<ActionsCentre onBack={() => {}} />);
    await screen.findByText(byExactText("memory.create · succeeded"));

    await user.click(screen.getByRole("button", { name: /audit history/i }));
    expect(await screen.findByText(/— proposed/)).toBeInTheDocument();
    expect(await screen.findByText(/— succeeded/)).toBeInTheDocument();
  });
});
