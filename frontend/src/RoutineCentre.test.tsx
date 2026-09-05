import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RoutineCentre from "./views/RoutineCentre";
import * as api from "./api";
import type { Domain, RoutineRunInfo, RoutineSchedule } from "./api";

const DOMAINS: Domain[] = [
  { id: "1", slug: "body", name: "BODY", description: "", created_at: "", updated_at: "" },
  { id: "6", slug: "life", name: "LIFE", description: "", created_at: "", updated_at: "" },
];

function schedule(overrides: Partial<RoutineSchedule> = {}): RoutineSchedule {
  return {
    routine_type: "morning_briefing",
    enabled: false,
    local_time: "08:00",
    weekday: null,
    timezone: "UTC",
    selected_domains: [],
    next_due_at: null,
    last_run_at: null,
    last_status: null,
    last_error: null,
    consecutive_failure_count: 0,
    ...overrides,
  };
}

function baseMocks(overrides: Partial<Record<string, unknown>> = {}) {
  vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
  vi.spyOn(api, "getRoutineSchedule").mockImplementation(async (routineType) =>
    schedule({
      routine_type: routineType,
      local_time: routineType === "evening_checkin" ? "20:00" : routineType === "weekly_review" ? "09:00" : "08:00",
      weekday: routineType === "weekly_review" ? 6 : null,
      ...(overrides.schedules as Record<string, Partial<RoutineSchedule>> | undefined)?.[routineType],
    }),
  );
  const historyForType = overrides.history as RoutineRunInfo[] | undefined;
  vi.spyOn(api, "listRoutineHistory").mockImplementation(async (routineType) => {
    if (!historyForType) return [];
    return historyForType.filter((run) => run.routine_type === routineType);
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RoutineCentre", () => {
  it("shows all three routines disabled by default", async () => {
    baseMocks();
    render(<RoutineCentre onBack={() => {}} />);

    expect(await screen.findByText("Morning Briefing")).toBeInTheDocument();
    expect(screen.getByText("Evening Check-in")).toBeInTheDocument();
    expect(screen.getByText("Weekly Review")).toBeInTheDocument();

    const toggles = await screen.findAllByRole("checkbox", { name: /^enabled$/i });
    expect(toggles).toHaveLength(3);
    toggles.forEach((toggle) => expect(toggle).not.toBeChecked());
  });

  it("enabling a routine calls updateRoutineSchedule with its current fields", async () => {
    const user = userEvent.setup();
    baseMocks();
    const updateSpy = vi.spyOn(api, "updateRoutineSchedule").mockResolvedValue(
      schedule({ routine_type: "morning_briefing", enabled: true, next_due_at: "2026-08-27T08:00:00Z" }),
    );

    render(<RoutineCentre onBack={() => {}} />);
    const toggles = await screen.findAllByRole("checkbox", { name: /^enabled$/i });
    await user.click(toggles[0]);

    await waitFor(() =>
      expect(updateSpy).toHaveBeenCalledWith(
        "morning_briefing",
        expect.objectContaining({ enabled: true, local_time: "08:00", timezone: "UTC", selected_domains: [] }),
      ),
    );
  });

  it("morning briefing only offers BODY/MIND/PEOPLE as sensitive opt-ins, never PATH/BUILD/LIFE", async () => {
    baseMocks();
    render(<RoutineCentre onBack={() => {}} />);

    const morningSection = (await screen.findByLabelText("Morning Briefing")) as HTMLElement;
    expect(morningSection).toBeInTheDocument();
    expect(within(morningSection).getByText("BODY")).toBeInTheDocument();
    expect(within(morningSection).getByText("MIND")).toBeInTheDocument();
    expect(within(morningSection).getByText("PEOPLE")).toBeInTheDocument();
    expect(within(morningSection).queryByText("PATH")).not.toBeInTheDocument();
  });

  it("toggling a sensitive domain checkbox calls updateRoutineSchedule with the domain added", async () => {
    const user = userEvent.setup();
    baseMocks();
    const updateSpy = vi.spyOn(api, "updateRoutineSchedule").mockResolvedValue(
      schedule({ routine_type: "morning_briefing", selected_domains: ["body"] }),
    );

    render(<RoutineCentre onBack={() => {}} />);
    const bodyCheckbox = (await screen.findAllByRole("checkbox", { name: "BODY" }))[0];
    await user.click(bodyCheckbox);

    await waitFor(() =>
      expect(updateSpy).toHaveBeenCalledWith("morning_briefing", expect.objectContaining({ selected_domains: ["body"] })),
    );
  });

  it("Run now calls runRoutineNow for that routine type", async () => {
    const user = userEvent.setup();
    baseMocks();
    const runSpy = vi.spyOn(api, "runRoutineNow").mockResolvedValue({
      id: "run-1",
      routine_type: "morning_briefing",
      trigger: "manual",
      started_at: "t",
      completed_at: "t",
      outcome: "succeeded",
      reason: null,
      sections: [],
      responses: {},
      selected_domains: [],
    });

    render(<RoutineCentre onBack={() => {}} />);
    const runButtons = await screen.findAllByRole("button", { name: /run now/i });
    await user.click(runButtons[0]);

    await waitFor(() => expect(runSpy).toHaveBeenCalledWith("morning_briefing"));
  });

  it("renders the latest output as a clearly-labeled local summary with source references, not a model response", async () => {
    baseMocks({
      history: [
        {
          id: "run-1",
          routine_type: "morning_briefing",
          trigger: "manual",
          started_at: "t",
          completed_at: "t",
          outcome: "succeeded",
          reason: null,
          sections: [{ title: "Today's Calendar events", lines: [{ text: "Dentist at 10am", source_ref: "calendar_event:abc12345" }] }],
          responses: {},
          selected_domains: [],
        } as RoutineRunInfo,
      ],
    });

    render(<RoutineCentre onBack={() => {}} />);

    expect(await screen.findByText(/generated locally — not a model response/i)).toBeInTheDocument();
    expect(screen.getByText(/Dentist at 10am/)).toBeInTheDocument();
    expect(screen.getByText(/calendar_event:abc12345/)).toBeInTheDocument();
  });

  it("evening check-in responses save locally via recordCheckinResponses, without creating any memory", async () => {
    const user = userEvent.setup();
    baseMocks({
      history: undefined,
    });
    vi.spyOn(api, "listRoutineHistory").mockImplementation(async (routineType) => {
      if (routineType !== "evening_checkin") return [];
      return [
        {
          id: "run-2",
          routine_type: "evening_checkin",
          trigger: "scheduled",
          started_at: "t",
          completed_at: "t",
          outcome: "succeeded",
          reason: null,
          sections: [{ title: "Evening check-in", lines: [{ text: "What did you complete today?", source_ref: null }] }],
          responses: {},
          selected_domains: [],
        },
      ];
    });
    const saveSpy = vi.spyOn(api, "recordCheckinResponses").mockResolvedValue({
      id: "run-2",
      routine_type: "evening_checkin",
      trigger: "scheduled",
      started_at: "t",
      completed_at: "t",
      outcome: "succeeded",
      reason: null,
      sections: [],
      responses: { "What did you complete today?": "Shipped the routines feature." },
      selected_domains: [],
    });

    render(<RoutineCentre onBack={() => {}} />);
    const input = await screen.findByLabelText(/what did you complete today/i);
    await user.type(input, "Shipped the routines feature.");
    await user.click(screen.getByRole("button", { name: /save responses/i }));

    await waitFor(() =>
      expect(saveSpy).toHaveBeenCalledWith("run-2", { "What did you complete today?": "Shipped the routines feature." }),
    );
    // The local-only guarantee is stated in the UI itself.
    expect(screen.getByRole("button", { name: /never auto-added to memory/i })).toBeInTheDocument();
  });

  it("Discuss with Jarvis creates a LIFE conversation, sends the routine text, and labels the reply as a model response distinct from the local summary", async () => {
    const user = userEvent.setup();
    baseMocks({
      history: [
        {
          id: "run-3",
          routine_type: "morning_briefing",
          trigger: "manual",
          started_at: "t",
          completed_at: "t",
          outcome: "succeeded",
          reason: null,
          sections: [{ title: "Today's Calendar events", lines: [{ text: "Dentist at 10am", source_ref: "calendar_event:abc12345" }] }],
          responses: {},
          selected_domains: [],
        } as RoutineRunInfo,
      ],
    });
    const createConvSpy = vi.spyOn(api, "createConversation").mockResolvedValue({
      id: "conv-1", domain_id: "6", title: "Morning Briefing discussion", created_at: "t", updated_at: "t", archived_at: null,
    });
    const sendTurnSpy = vi.spyOn(api, "sendTurn").mockResolvedValue({
      run_id: "r1",
      status: "succeeded",
      user_message: { id: "m1", conversation_id: "conv-1", role: "user", content: "x", created_at: "t", model_used: null },
      assistant_message: { id: "m2", conversation_id: "conv-1", role: "assistant", content: "Looks like a light morning.", created_at: "t", model_used: "gpt-5.6-terra" },
      provider: "hermes",
      model: "gpt-5.6-terra",
      latency_ms: 10,
      usage: null,
      context_snapshot_id: null,
      error: null,
    });

    render(<RoutineCentre onBack={() => {}} />);
    const discussButton = await screen.findByRole("button", { name: /discuss with jarvis/i });
    await user.click(discussButton);

    await waitFor(() => expect(createConvSpy).toHaveBeenCalledWith("life", expect.stringContaining("Morning Briefing")));
    await waitFor(() => expect(sendTurnSpy).toHaveBeenCalled());
    expect(sendTurnSpy.mock.calls[0][0]).toBe("conv-1");
    expect(sendTurnSpy.mock.calls[0][1]).toContain("Dentist at 10am");

    expect(await screen.findByText(/Jarvis \(model response\):/i)).toBeInTheDocument();
    expect(screen.getByText(/Looks like a light morning\./)).toBeInTheDocument();
  });
});
