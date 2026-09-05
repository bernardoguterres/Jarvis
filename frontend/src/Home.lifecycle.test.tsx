import { act, render } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Home from "./views/Home";
import * as api from "./api";
import type { Domain, HomeBriefing, MissionCandidates } from "./api";

/** A promise this test controls directly, so a request can be left
 * deliberately unresolved while Home unmounts, then resolved/rejected
 * afterward — reproducing the exact race a normal mocked-resolved-value
 * fetch can't: real network timing where the response arrives after the
 * viewer has already navigated away. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const DOMAINS: Domain[] = [];
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
const NO_CANDIDATES: MissionCandidates = { recommended: null, alternatives: [], watch: [], generated_at: "2026-08-29T09:00:00Z" };

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Home — async lifecycle safety", () => {
  it("clears its poll interval and never throws when requests resolve after unmount, under Strict Mode", async () => {
    const domainsDeferred = deferred<Domain[]>();
    const briefingDeferred = deferred<HomeBriefing>();
    const missionDeferred = deferred<{ session: null }>();
    const candidatesDeferred = deferred<MissionCandidates>();

    vi.spyOn(api, "fetchDomains").mockReturnValue(domainsDeferred.promise);
    vi.spyOn(api, "fetchHomeBriefing").mockReturnValue(briefingDeferred.promise);
    vi.spyOn(api, "fetchCurrentMission").mockReturnValue(missionDeferred.promise);
    vi.spyOn(api, "fetchMissionCandidates").mockReturnValue(candidatesDeferred.promise);

    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    // Strict Mode: mounts, runs every effect's cleanup, then re-runs setup
    // once more before the component's "real" lifetime begins — the exact
    // condition that exposed mountedRef never being reset back to true.
    const { unmount } = render(
      <StrictMode>
        <Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />
      </StrictMode>,
    );

    // Leave every request unresolved, then unmount — mirrors selecting a
    // domain (or any navigation away from Home) before these ever settle.
    unmount();

    // Now resolve/reject them, only after Home is gone.
    //
    // Note on what this can and can't prove: the original failure
    // (`ReferenceError: window is not defined`, surfaced intermittently
    // across full test-suite runs) required vitest's jsdom environment
    // for an *entire test file* to be torn down while one of these
    // promises was still pending from an earlier file — React's
    // dispatchSetState reads `window.event` for priority inference on any
    // update triggered outside a synthetic event (exactly what a `.then()`
    // continuation is), which only throws if `window` itself is gone, not
    // merely because the component unmounted. A real browser tab's
    // `window` never disappears while the page is open, so that crash is
    // a test-environment artifact, not a producible bug — and it can't be
    // deterministically re-triggered inside one still-alive test file
    // without unsafely deleting global `window` mid-test. Verified this
    // directly: with every mountedRef guard temporarily stripped, this
    // exact test still passed, proving it does not by itself distinguish
    // guarded from unguarded for that specific crash.
    //
    // What this test *does* prove directly, regardless of that: the
    // interval is actually cleared on unmount, and resolving/rejecting
    // every in-flight request post-unmount throws nothing synchronously
    // and logs no console error.
    await act(async () => {
      domainsDeferred.resolve(DOMAINS);
      briefingDeferred.resolve(EMPTY_BRIEFING);
      missionDeferred.resolve({ session: null });
      candidatesDeferred.reject(new Error("network error arriving after navigation"));
      // Let every microtask spawned by the above actually run before the
      // test (and its automatic unhandled-rejection detection) finishes.
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(consoleErrorSpy).not.toHaveBeenCalled();
    // The 30s Mission Control poll interval must be cleared on unmount —
    // proven directly, not inferred from the absence of a crash.
    expect(clearIntervalSpy).toHaveBeenCalled();
  });

  it("still applies real updates normally while mounted (the guard must not suppress legitimate state changes)", async () => {
    const briefingDeferred = deferred<HomeBriefing>();
    vi.spyOn(api, "fetchDomains").mockResolvedValue(DOMAINS);
    vi.spyOn(api, "fetchHomeBriefing").mockReturnValue(briefingDeferred.promise);
    vi.spyOn(api, "fetchCurrentMission").mockResolvedValue({ session: null });
    vi.spyOn(api, "fetchMissionCandidates").mockResolvedValue(NO_CANDIDATES);

    const { findByText } = render(
      <StrictMode>
        <Home onSelectDomain={() => {}} onOpenGeneral={() => {}} onNavigate={() => {}} health="ok" />
      </StrictMode>,
    );

    // Resolve while Home is still mounted — this must reach the screen.
    // If mountedRef were stuck false after Strict Mode's double-invoke
    // (the exact regression this file guards against), this update would
    // be silently dropped and the briefing would stay in "loading"
    // forever even though nothing is actually still fetching.
    await act(async () => {
      briefingDeferred.resolve({
        ...EMPTY_BRIEFING,
        items: [
          {
            id: "item-1",
            category: "watch",
            tone: "neutral",
            title: "Renew passport",
            subtitle: null,
            domain_slug: "life",
            source_type: "life_task",
            source_ids: ["xyz"],
            reason: "Due in 3 days",
            source_timestamp: null,
            freshness: "current",
            classification: "factual",
            link_target: "domain:life",
            fingerprint: "fp-1",
            change_state: "new",
            pinned: false,
            pin_rank: null,
          },
        ],
      });
    });

    expect(await findByText("Renew passport")).toBeInTheDocument();
  });
});
