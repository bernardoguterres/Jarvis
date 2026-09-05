// A tiny, generic "find this control once it exists, then briefly
// highlight it" mechanism used by sensitive focus-control commands (see
// registry.ts). It never clicks anything — it only scrolls the control
// into view, focuses it, and adds a temporary CSS class so the user can
// see exactly what a spoken/typed command was pointing at before deciding
// to act on it themselves.

let pendingId: string | null = null;
let pollHandle: ReturnType<typeof setInterval> | null = null;

const HIGHLIGHT_CLASS = "command-highlight";
const HIGHLIGHT_DURATION_MS = 1800;
const POLL_INTERVAL_MS = 100;
const POLL_TIMEOUT_MS = 4000;

export function requestHighlight(controlId: string): void {
  pendingId = controlId;
  let elapsed = 0;
  if (pollHandle) clearInterval(pollHandle);
  pollHandle = setInterval(() => {
    elapsed += POLL_INTERVAL_MS;
    const el = document.querySelector<HTMLElement>(`[data-command-target="${controlId}"]`);
    if (el && pendingId === controlId) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.focus?.({ preventScroll: true });
      el.classList.add(HIGHLIGHT_CLASS);
      setTimeout(() => el.classList.remove(HIGHLIGHT_CLASS), HIGHLIGHT_DURATION_MS);
      pendingId = null;
      if (pollHandle) clearInterval(pollHandle);
      pollHandle = null;
    } else if (elapsed >= POLL_TIMEOUT_MS) {
      pendingId = null;
      if (pollHandle) clearInterval(pollHandle);
      pollHandle = null;
    }
  }, POLL_INTERVAL_MS);
}
