import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __resetTransitionInFlightForTests,
  DOMAIN_TRANSITION_NAME,
  runDomainViewTransition,
} from "./domainViewTransition";

/** jsdom has no real View Transitions implementation, so these tests stub
 * `document.startViewTransition` themselves to exercise both the
 * supported and unsupported code paths deterministically. */
function stubViewTransitions(): {
  startViewTransition: ReturnType<typeof vi.fn>;
  resolveFinished: () => void;
} {
  let resolveFinished: () => void = () => {};
  const finished = new Promise<void>((resolve) => {
    resolveFinished = resolve;
  });
  const startViewTransition = vi.fn((callback: () => void) => {
    callback();
    return { finished, ready: Promise.resolve(), updateCallbackDone: Promise.resolve(), skipTransition: vi.fn() };
  });
  // @ts-expect-error -- test-only stub, jsdom has no real implementation
  document.startViewTransition = startViewTransition;
  return { startViewTransition, resolveFinished };
}

function clearViewTransitionStub() {
  delete (document as { startViewTransition?: unknown }).startViewTransition;
}

describe("runDomainViewTransition", () => {
  afterEach(() => {
    clearViewTransitionStub();
    __resetTransitionInFlightForTests();
    document.documentElement.removeAttribute("style");
    document.body.innerHTML = "";
  });

  it("falls back to an immediate commit when document.startViewTransition is unavailable", () => {
    clearViewTransitionStub();
    const commit = vi.fn();
    runDomainViewTransition("body", commit);
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("falls back to an immediate commit under prefers-reduced-motion, even when View Transitions are supported", () => {
    stubViewTransitions();
    const matchMediaSpy = vi.spyOn(window, "matchMedia").mockReturnValue({
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList);

    const commit = vi.fn();
    runDomainViewTransition("body", commit);

    expect(commit).toHaveBeenCalledTimes(1);
    expect(document.startViewTransition).not.toHaveBeenCalled();
    matchMediaSpy.mockRestore();
  });

  it("tags the matching source node before starting the transition, and clears it once finished", async () => {
    const { resolveFinished } = stubViewTransitions();
    const node = document.createElement("button");
    node.setAttribute("data-domain-transition-slug", "body");
    document.body.appendChild(node);

    let nameDuringCommit: string | undefined;
    runDomainViewTransition("body", () => {
      nameDuringCommit = node.style.viewTransitionName;
    });

    expect(nameDuringCommit).toBe(DOMAIN_TRANSITION_NAME);
    expect(node.style.viewTransitionName).toBe(DOMAIN_TRANSITION_NAME);

    resolveFinished();
    await Promise.resolve();
    await Promise.resolve();

    expect(node.style.viewTransitionName).toBe("");
  });

  it("runs a plain crossfade (no assigned name) when no matching node exists — e.g. a command fired from a Centre page", () => {
    const { startViewTransition } = stubViewTransitions();
    const commit = vi.fn();

    runDomainViewTransition("build", commit);

    expect(startViewTransition).toHaveBeenCalledTimes(1);
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it("ignores a second call while a transition is already in flight (double-activation protection)", () => {
    stubViewTransitions();
    const first = vi.fn();
    const second = vi.fn();

    runDomainViewTransition("body", first);
    runDomainViewTransition("mind", second);

    expect(first).toHaveBeenCalledTimes(1);
    expect(second).not.toHaveBeenCalled();
  });

  it("never produces an unhandled rejection when the browser rejects `ready` (e.g. the document was hidden mid-click) — `updateCallbackDone`/`finished` still resolve and commit still runs", async () => {
    const unhandledRejections: unknown[] = [];
    const onUnhandled = (event: PromiseRejectionEvent) => unhandledRejections.push(event.reason);
    window.addEventListener("unhandledrejection", onUnhandled);

    let resolveFinished: () => void = () => {};
    const finished = new Promise<void>((resolve) => {
      resolveFinished = resolve;
    });
    const startViewTransition = vi.fn((callback: () => void) => {
      callback();
      return {
        ready: Promise.reject(new DOMException("Transition was aborted because of invalid state", "InvalidStateError")),
        updateCallbackDone: Promise.resolve(),
        finished,
        skipTransition: vi.fn(),
      };
    });
    // @ts-expect-error -- test-only stub
    document.startViewTransition = startViewTransition;

    const commit = vi.fn();
    runDomainViewTransition("body", commit);
    expect(commit).toHaveBeenCalledTimes(1);

    resolveFinished();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    window.removeEventListener("unhandledrejection", onUnhandled);
    expect(unhandledRejections).toHaveLength(0);
  });

  it("accepts a new activation once the previous transition has finished", async () => {
    const { resolveFinished } = stubViewTransitions();
    const first = vi.fn();
    runDomainViewTransition("body", first);
    resolveFinished();
    await Promise.resolve();
    await Promise.resolve();

    const second = vi.fn();
    runDomainViewTransition("mind", second);
    expect(second).toHaveBeenCalledTimes(1);
  });
});
