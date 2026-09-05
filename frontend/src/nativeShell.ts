/** True when this page is running inside the packaged Tauri app's own
 * window, false for the `jarvisctl.sh`/browser dev-mode workflow.
 *
 * Note: this reflects whether the surrounding shell is Tauri, not whether
 * `window.__TAURI__`'s JS/IPC bridge is actually usable from this exact
 * page — Tauri only injects that bridge into content loaded from its own
 * trusted origin, and this app's real content loads from the same plain
 * `http://127.0.0.1` origin the backend serves everything else from, so
 * the bridge is never actually present here even though this returns
 * true. (Confirmed the hard way: an earlier "open the OAuth URL via
 * Tauri's IPC bridge" attempt from this same context silently invoked
 * nothing — see the backend's own `POST
 * /api/integrations/{provider}/connect`, which now opens the system
 * browser server-side instead, sidestepping this entirely.) Only used
 * today to vary *displayed text* (e.g. ControllerOfflineDiagnostic's
 * launch instructions) — never to decide whether an IPC call will work. */
export function isRunningInNativeApp(): boolean {
  return Boolean((window as unknown as { __TAURI__?: unknown }).__TAURI__);
}
