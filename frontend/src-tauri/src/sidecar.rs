//! Backend process ownership and health-gated startup (Stage 1 native
//! packaging — CLAUDE.md §4/§9's "no fake activity" and "truthful diagnostic
//! state" requirements applied to the native shell itself).
//!
//! Exactly one of two things happens at startup, never a silent third:
//!   1. A real Jarvis backend is already healthy on 127.0.0.1:8000 (started
//!      by `scripts/jarvisctl.sh`, or a prior launch of this app) — it is
//!      reused, and this process never touches its lifecycle.
//!   2. Nothing is answering there — this app spawns and owns the
//!      `jarvis-backend` sidecar, and only ever stops that exact
//!      self-spawned child on Quit.
//! A response on the port that isn't genuinely Jarvis (wrong body) is
//! reported as a real port conflict, never silently adopted or overwritten.

use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const BACKEND_DIR: &str = env!("JARVIS_BACKEND_DIR");
const HEALTH_URL: &str = "http://127.0.0.1:8000/api/health";
const APP_URL: &str = "http://127.0.0.1:8000/";
const HEALTH_POLL_ATTEMPTS: u32 = 30;
const HEALTH_POLL_INTERVAL: Duration = Duration::from_secs(1);
// After the fast bounded window above gives up and shows the offline
// diagnostic, this keeps checking indefinitely in the background — a slow
// backend that eventually comes up must still auto-recover into the real
// window without requiring a relaunch. Never used to decide "has it
// failed" (the offline diagnostic already reported that truthfully); only
// ever used to notice a late recovery.
const RECOVERY_POLL_INTERVAL: Duration = Duration::from_secs(3);

pub struct SidecarState {
    /// Only Some(..) when THIS process spawned the child itself — never set
    /// for a reused pre-existing backend, so Quit can never kill a process
    /// this app didn't start.
    pub owned_child: Mutex<Option<CommandChild>>,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            owned_child: Mutex::new(None),
        }
    }
}

#[derive(Clone, serde::Serialize)]
struct SidecarStatusEvent<'a> {
    state: &'a str,
    message: String,
}

fn emit_status(app: &AppHandle, state: &str, message: impl Into<String>) {
    let message = message.into();
    log::info!("[sidecar] {}: {}", state, message);
    let payload = SidecarStatusEvent { state, message };
    let _ = app.emit("jarvis://sidecar-status", payload);
}

/// GET /api/health with a short timeout. Returns true only when the body
/// genuinely looks like Jarvis's own health response — a bare 200 from an
/// unrelated process squatting on the port must never be treated as "ours."
fn probe_health() -> HealthProbe {
    match ureq::get(HEALTH_URL).timeout(Duration::from_secs(2)).call() {
        Ok(response) => {
            let body = response.into_string().unwrap_or_default();
            if body.contains("\"status\"") && body.contains("\"ok\"") {
                HealthProbe::Healthy
            } else {
                HealthProbe::PortConflict
            }
        }
        Err(ureq::Error::Status(_, _)) => HealthProbe::PortConflict,
        Err(_) => HealthProbe::Unreachable,
    }
}

enum HealthProbe {
    Healthy,
    PortConflict,
    Unreachable,
}

/// Runs on a background thread from `setup()` so it never blocks Tauri's
/// event loop. Decides reuse-vs-spawn, polls health, then reveals the real
/// window (or a truthful failure state) — never both a hidden window and
/// silence.
pub fn start(app: AppHandle) {
    std::thread::spawn(move || {
        emit_status(&app, "starting", "Checking for a running Jarvis backend…");

        match probe_health() {
            HealthProbe::Healthy => {
                log::info!("[sidecar] reusing an already-running, already-healthy backend");
                reveal_app(&app);
                return;
            }
            HealthProbe::PortConflict => {
                emit_status(
                    &app,
                    "error",
                    "Port 8000 is already in use by something other than Jarvis. Stop that process, then relaunch.",
                );
                show_offline_window(&app);
                return;
            }
            HealthProbe::Unreachable => {
                // Nothing is listening — proceed to spawn our own.
            }
        }

        let state = app.state::<SidecarState>();
        let sidecar_cmd = match app.shell().sidecar("jarvis-backend") {
            Ok(cmd) => cmd.current_dir(BACKEND_DIR),
            Err(err) => {
                emit_status(&app, "error", format!("Could not locate the backend sidecar: {err}"));
                show_offline_window(&app);
                return;
            }
        };
        let (mut rx, child) = match sidecar_cmd.spawn() {
            Ok(pair) => pair,
            Err(err) => {
                emit_status(&app, "error", format!("Could not start the backend: {err}"));
                show_offline_window(&app);
                return;
            }
        };
        *state.owned_child.lock().unwrap() = Some(child);

        // The stdout/stderr pipe MUST be drained continuously for the life
        // of the child — Alembic's migration log alone is tens of KB, and
        // an undrained OS pipe fills its kernel buffer and makes the
        // child's own write() block forever, hanging startup with no
        // visible error (the defect this comment replaces). Forwarding
        // into `log` also gives real diagnostic output instead of silence.
        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(line) => {
                        log::info!("[backend] {}", String::from_utf8_lossy(&line).trim_end());
                    }
                    CommandEvent::Stderr(line) => {
                        log::info!("[backend] {}", String::from_utf8_lossy(&line).trim_end());
                    }
                    CommandEvent::Error(err) => {
                        log::warn!("[backend] process error: {err}");
                    }
                    CommandEvent::Terminated(payload) => {
                        log::info!("[backend] process terminated: {:?}", payload);
                    }
                    _ => {}
                }
            }
        });

        emit_status(&app, "starting", "Starting local services…");

        for attempt in 1..=HEALTH_POLL_ATTEMPTS {
            std::thread::sleep(HEALTH_POLL_INTERVAL);
            match probe_health() {
                HealthProbe::Healthy => {
                    reveal_app(&app);
                    return;
                }
                HealthProbe::PortConflict => {
                    emit_status(&app, "error", "The backend bound to an unexpected state. Relaunch Jarvis.");
                    show_offline_window(&app);
                    return;
                }
                HealthProbe::Unreachable => {
                    emit_status(
                        &app,
                        "starting",
                        format!("Starting local services… ({attempt}/{HEALTH_POLL_ATTEMPTS})"),
                    );
                }
            }
        }

        emit_status(
            &app,
            "error",
            "The Jarvis backend did not become healthy in time. Still checking in the background — it will open automatically if it recovers, or use Retry Connection.",
        );
        show_offline_window(&app);
        run_recovery_loop(&app);
    });
}

/// Runs after the bounded fast-retry window above gives up. Keeps checking
/// health forever at a slower interval — this is what makes "recovers
/// without requiring a relaunch" genuinely true rather than aspirational:
/// a real slow first-run (large model-file load, a delayed Keychain
/// approval, etc.) that eventually succeeds must still reach the real
/// window on its own. Stops the moment health is reached; runs for the
/// life of the process otherwise (harmless — one lightweight HTTP probe
/// every few seconds).
fn run_recovery_loop(app: &AppHandle) {
    loop {
        std::thread::sleep(RECOVERY_POLL_INTERVAL);
        match probe_health() {
            HealthProbe::Healthy => {
                log::info!("[sidecar] backend recovered after the initial timeout — opening automatically");
                reveal_app(app);
                return;
            }
            HealthProbe::PortConflict | HealthProbe::Unreachable => {
                // Stay quiet on the repeated background checks — the
                // offline screen already shows the real failure state;
                // re-emitting the identical message every 3s would just be
                // noise, not new information.
            }
        }
    }
}

/// Invoked by the offline diagnostic's "Retry Connection" button — runs
/// one immediate check outside the slower background cadence above, so a
/// user-initiated retry gets an instant answer instead of waiting for the
/// next scheduled tick.
#[tauri::command]
fn retry_connection(app: AppHandle) {
    match probe_health() {
        HealthProbe::Healthy => reveal_app(&app),
        HealthProbe::PortConflict => {
            emit_status(&app, "error", "Port 8000 is still in use by something other than Jarvis.");
        }
        HealthProbe::Unreachable => {
            emit_status(&app, "error", "Still not reachable — still checking automatically in the background.");
        }
    }
}

/// Invoked by the offline diagnostic's "Show Logs" button — resolves
/// entirely from Tauri's own path resolver (never depends on the backend
/// being reachable, which is the whole point when this is shown), then
/// reveals it in Finder. Logs a real, timestamped record of the launch
/// (lifecycle events plus every drained backend stdout/stderr line — see
/// the log plugin setup in lib.rs) for diagnosing a failed startup.
#[tauri::command]
fn reveal_log_folder(app: AppHandle) -> Result<(), String> {
    log::info!("[commands] reveal_log_folder invoked");
    let dir = app.path().app_log_dir().map_err(|e| e.to_string())?;
    let result = std::process::Command::new("open").arg(&dir).spawn();
    match &result {
        Ok(child) => log::info!("[commands] reveal_log_folder: spawned open, pid {}", child.id()),
        Err(e) => log::warn!("[commands] reveal_log_folder: spawn failed: {e}"),
    }
    result.map(|_| ()).map_err(|e| e.to_string())
}

// No Rust command opens OAuth URLs: Tauri's JS/IPC bridge is never present
// on this app's real content (it loads from a plain http://127.0.0.1
// origin, not Tauri's trusted origin), so the frontend can't reach one
// anyway. The backend opens the browser itself, server-side, in
// `POST /api/integrations/{provider}/connect`.

pub fn invoke_handler() -> impl Fn(tauri::ipc::Invoke) -> bool {
    tauri::generate_handler![retry_connection, reveal_log_folder]
}

fn reveal_app(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if let Ok(url) = APP_URL.parse() {
            let _ = window.navigate(url);
        }
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn show_offline_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    } else {
        let _ = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("offline.html".into()))
            .title("Jarvis")
            .build();
    }
}

fn process_alive(pid: i32) -> bool {
    // kill(pid, 0) sends no signal — it only checks whether the pid still
    // exists and is ours to signal.
    unsafe { libc::kill(pid, 0) == 0 }
}

/// Stops only a sidecar this app itself spawned. Never touches a reused,
/// pre-existing backend — matching CLAUDE.md's "never kill a process the
/// app did not start."
///
/// `CommandChild::kill()` alone is not enough: it sends SIGKILL straight to
/// the pid tauri-plugin-shell tracks, which for the PyInstaller onefile
/// sidecar is the bootloader stub, not the real Python/uvicorn process it
/// unpacks and supervises. SIGKILL gives the bootloader no chance to relay
/// anything, so the real process was found orphaned (reparented to
/// launchd) and still bound to port 8000 after Quit — breaking every
/// later launch's reuse-vs-spawn health probe. SIGTERM first gives the
/// bootloader the chance to forward it (its documented behavior) and lets
/// uvicorn shut down gracefully; the port-8000 owner is then independently
/// re-checked and killed by exact executable path, so cleanup is verified
/// rather than assumed regardless of the bootloader's own relaying.
pub fn shutdown_owned_backend(app: &AppHandle) {
    let taken = {
        let state = app.state::<SidecarState>();
        let child = state.owned_child.lock().unwrap().take();
        child
    };
    let Some(child) = taken else { return };

    let pid = child.pid() as i32;
    log::info!("[sidecar] stopping app-owned backend (pid {pid}) on Quit");
    unsafe {
        libc::kill(pid, libc::SIGTERM);
    }
    for _ in 0..20 {
        if !process_alive(pid) {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    if process_alive(pid) {
        log::warn!("[sidecar] pid {pid} did not exit after SIGTERM; sending SIGKILL");
        let _ = child.kill();
    }

    kill_any_surviving_port_owner();
}

/// Defensive verification pass: whatever is still listening on 127.0.0.1:8000
/// after the steps above, kill it too — but ONLY if its own executable is
/// genuinely our bundled sidecar binary (exact path match), mirroring
/// scripts/jarvisctl.sh's own "verified_running_pid" pattern. This is what
/// makes cleanup verified rather than assumed if the bootloader's signal
/// relay ever doesn't happen.
fn kill_any_surviving_port_owner() {
    let Ok(lsof_out) = std::process::Command::new("lsof")
        .args(["-tiTCP:8000", "-sTCP:LISTEN", "-n", "-P"])
        .output()
    else {
        return;
    };
    let our_binary = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.join("jarvis-backend")));
    for line in String::from_utf8_lossy(&lsof_out.stdout).lines() {
        let Ok(pid) = line.trim().parse::<i32>() else {
            continue;
        };
        let Ok(comm_out) = std::process::Command::new("ps")
            .args(["-o", "comm=", "-p", &pid.to_string()])
            .output()
        else {
            continue;
        };
        let comm = String::from_utf8_lossy(&comm_out.stdout).trim().to_string();
        let matches_ours = our_binary
            .as_ref()
            .is_some_and(|ours| comm == ours.to_string_lossy());
        if matches_ours {
            log::warn!("[sidecar] port 8000 still held by our own pid {pid} after shutdown; killing it directly");
            unsafe {
                libc::kill(pid, libc::SIGKILL);
            }
        }
    }
}
