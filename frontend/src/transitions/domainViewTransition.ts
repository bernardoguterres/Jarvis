import { flushSync } from "react-dom";

/** The one shared `view-transition-name` used for the Home↔domain morph.
 * Only ever assigned to a single DOM node at a time (imperatively, right
 * before/after the transition), never applied via a static CSS rule to
 * all six domain nodes at once — the View Transitions API requires a
 * given name to be unique across the document at snapshot time. */
const DOMAIN_TRANSITION_NAME = "jarvis-domain-shared";

function domainTransitionNode(slug: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-domain-transition-slug="${slug}"]`);
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function supportsViewTransitions(): boolean {
  return typeof document !== "undefined" && typeof document.startViewTransition === "function";
}

// `document.startViewTransition`'s callback runs in a microtask, not
// synchronously — so a rapid double-click/double-Enter can otherwise reach
// this function a second time before the first transition's DOM swap has
// actually happened, starting a second, conflicting transition. This
// module-level latch (there is only ever one Home↔domain transition
// in flight at a time, regardless of which slug) makes a second call a
// no-op until the first one's `commit` has genuinely run — without making
// the first activation itself feel delayed.
let transitionInFlight = false;

/** Exposed for tests only, to reset the module-level in-flight latch
 * between cases. */
export function __resetTransitionInFlightForTests(): void {
  transitionInFlight = false;
}

/** Runs `commit` (a React state update that swaps Home for a domain view,
 * or a domain view back for Home) as one continuous browser View
 * Transition, so the click/keyboard/shortcut/command path that selected
 * `slug` all read identically — never a manual growth animation followed
 * by an artificial wait before the destination screen replaces Home.
 *
 * Whichever single DOM node currently carries
 * `data-domain-transition-slug="<slug>"` (Home's own node on the way in,
 * or the domain view's header emblem on the way back out) is tagged with
 * the one shared `view-transition-name` immediately before the browser
 * captures the "old" snapshot; after `commit` re-renders, whichever node
 * now carries that same data attribute gets the same name for the "new"
 * snapshot, so the browser morphs one directly into the other. When no
 * matching node exists on either side (e.g. a command fired from a Centre
 * page, where Home was never mounted), no name is assigned at all — the
 * browser's own default root crossfade covers that case, exactly the
 * "clean short page crossfade" this is supposed to fall back to.
 *
 * Falls back to an immediate, undelayed `commit()` — never an artificial
 * wait either way — when View Transitions aren't supported or the user
 * prefers reduced motion, matching this project's existing global
 * reduced-motion discipline. */
export function runDomainViewTransition(slug: string, commit: () => void): void {
  if (transitionInFlight) return;

  if (!supportsViewTransitions() || prefersReducedMotion()) {
    // No async gap here — `commit` runs synchronously, so there is no
    // window for a second activation to race this one; no latch needed.
    commit();
    return;
  }

  transitionInFlight = true;
  const sourceEl = domainTransitionNode(slug);
  if (sourceEl) sourceEl.style.viewTransitionName = DOMAIN_TRANSITION_NAME;

  let transition: ViewTransition;
  try {
    transition = document.startViewTransition(() => {
      flushSync(commit);
      const targetEl = domainTransitionNode(slug);
      if (targetEl) targetEl.style.viewTransitionName = DOMAIN_TRANSITION_NAME;
    });
  } catch {
    // A genuinely unsupported/broken environment (e.g. a test DOM with a
    // partial polyfill) — never leave navigation stuck behind a failed
    // animation call.
    if (sourceEl) sourceEl.style.viewTransitionName = "";
    transitionInFlight = false;
    commit();
    return;
  }

  // `ready` rejects whenever the browser decides it cannot (or should
  // not) run the custom animation at all — most commonly the document
  // being hidden/backgrounded at the exact moment of the call, which is
  // a normal, recoverable condition (e.g. the user switched tabs mid
  // click) rather than a bug in `commit` itself. `updateCallbackDone`/
  // `finished` still resolve normally in that case — the DOM swap always
  // completes — so this exists purely to avoid an unhandled promise
  // rejection console error, never to change navigation behavior.
  transition.ready.catch(() => {});

  transition.finished.finally(() => {
    if (sourceEl) sourceEl.style.viewTransitionName = "";
    const targetEl = domainTransitionNode(slug);
    if (targetEl) targetEl.style.viewTransitionName = "";
    transitionInFlight = false;
  });
}

export { DOMAIN_TRANSITION_NAME };
