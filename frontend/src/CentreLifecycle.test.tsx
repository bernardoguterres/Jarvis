import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import IntegrationsCentre from "./views/IntegrationsCentre";
import RoutineCentre from "./views/RoutineCentre";
import SkillsCentre from "./views/SkillsCentre";
import * as api from "./api";
import type { Domain, IntegrationConnection, IntegrationSchedule, RoutineSchedule, Skill } from "./api";

/** Same technique as Home.lifecycle.test.tsx: a promise this test controls
 * directly, left unresolved across an unmount so the continuation fires
 * only afterward. Reported as observations (not confirmed defects) in the
 * V1 audit, since — unlike Home.tsx — none of these three components poll
 * on an interval, and no failure had actually been reproduced for them.
 * This file is what actually checks that, instead of leaving it asserted. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const DOMAINS: Domain[] = [{ id: "1", slug: "body", name: "BODY", description: "", created_at: "", updated_at: "" }];

const DISCONNECTED: IntegrationConnection[] = [
  { provider: "google_calendar", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
  { provider: "google_health", status: "disconnected", scopes: [], external_account_label: null, connected_at: null, last_sync_at: null, last_sync_status: null, last_error: null },
];

function integrationSchedule(provider: "google_calendar" | "google_health"): IntegrationSchedule {
  return {
    provider,
    enabled: false,
    interval_minutes: provider === "google_calendar" ? 30 : 360,
    next_due_at: null,
    last_attempt_at: null,
    last_success_at: null,
    last_status: null,
    last_error: null,
    consecutive_failure_count: 0,
  };
}

function routineSchedule(routineType: string): RoutineSchedule {
  return {
    routine_type: routineType as RoutineSchedule["routine_type"],
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
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Centre components — async lifecycle safety (V1 audit observations, verified)", () => {
  it("IntegrationsCentre: resolving listIntegrations after unmount throws nothing and logs no error", async () => {
    const connectionsDeferred = deferred<IntegrationConnection[]>();
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchMissionFocus").mockResolvedValue({ active_pins: [], max_active_pins: 5, default_visible: 3 });
    vi.spyOn(api, "listIntegrations").mockReturnValue(connectionsDeferred.promise);
    vi.spyOn(api, "listCalendars").mockResolvedValue([]);
    vi.spyOn(api, "listCalendarEvents").mockResolvedValue([]);
    vi.spyOn(api, "listGoogleHealthSummaries").mockResolvedValue([]);
    vi.spyOn(api, "listGoogleHealthSessions").mockResolvedValue([]);
    vi.spyOn(api, "fetchGoogleHealthMetricGroups").mockResolvedValue([]);
    vi.spyOn(api, "fetchGoogleHealthUnsupportedMetrics").mockResolvedValue([]);
    vi.spyOn(api, "listDocuments").mockResolvedValue([]);
    vi.spyOn(api, "getIntegrationSchedule").mockImplementation(async (provider) => integrationSchedule(provider));

    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<IntegrationsCentre onBack={() => {}} />);

    unmount();
    await act(async () => {
      connectionsDeferred.resolve(DISCONNECTED);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it("RoutineCentre: resolving getRoutineSchedule after unmount throws nothing and logs no error", async () => {
    const scheduleDeferred = deferred<RoutineSchedule>();
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "getRoutineSchedule").mockImplementation((routineType) =>
      routineType === "morning_briefing" ? scheduleDeferred.promise : Promise.resolve(routineSchedule(routineType)),
    );
    vi.spyOn(api, "listRoutineHistory").mockResolvedValue([]);

    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<RoutineCentre onBack={() => {}} />);

    unmount();
    await act(async () => {
      scheduleDeferred.resolve(routineSchedule("morning_briefing"));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it("SkillsCentre: resolving listSkills after unmount throws nothing and logs no error", async () => {
    const skillsDeferred = deferred<Skill[]>();
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "listSkills").mockReturnValue(skillsDeferred.promise);

    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<SkillsCentre onBack={() => {}} />);

    unmount();
    await act(async () => {
      skillsDeferred.resolve([]);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });
});
