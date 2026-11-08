//! Backend process ownership and health-gated startup (Stage 1 native
//! packaging — project rules §4/§9's "no fake activity" and "truthful diagnostic
//! state" requirements applied to the native shell itself).
//!
//! Exactly one of two things happens at startup, never a silent third:
//!   1. A real Jarvis backend is already healthy on 127.0.0.1:$PORT (started
//!      by `scripts/jarvisctl.sh`, or a prior launch of this app) — it is
//!      reused, and this process never touches its lifecycle.
//!   2. Nothing is answering there — this app spawns and owns the
//!      `jarvis-backend` sidecar, and only ever stops that exact
//!      self-spawned child on Quit.
//! A response on the port that isn't genuinely Jarvis (wrong body) is
//! reported as a real port conflict, never silently adopted or overwritten.

use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const BACKEND_DIR: &str = env!("JARVIS_BACKEND_DIR");
const HEALTH_POLL_ATTEMPTS: u32 = 30;
const HEALTH_POLL_INTERVAL: Duration = Duration::from_secs(1);
// After the fast bounded window above gives up and shows the offline
// diagnostic, this keeps checking indefinitely in the background — a slow
// backend that eventually comes up must still auto-recover into the real
// window without requiring a relaunch. Never used to decide "has it
// failed" (the offline diagnostic already reported that truthfully); only
// ever used to notice a late recovery.
const RECOVERY_POLL_INTERVAL: Duration = Duration::from_secs(3);

/// Resolves the backend port from JARVIS_BACKEND_PORT, defaulting to 8000.
pub fn backend_port() -> u16 {
    std::env::var("JARVIS_BACKEND_PORT")
        .ok()
        .and_then(|p| p.parse::<u16>().ok())
        .unwrap_or(8000)
}

/// Builds a 127.0.0.1 URL for the configured backend port.
pub fn backend_url(path: &str) -> String {
    let clean = if path.starts_with('/') { path } else { &format!("/{path}") };
    format!("http://127.0.0.1:{}{}", backend_port(), clean)
}

/// Verifiable identity of a worker process to prevent signalling recycled PIDs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerIdentity {
    pub pid: i32,
    pub start_time: String,
    pub comm: String,
}

pub struct SidecarState {
    /// Only Some(..) when THIS process spawned the child itself — never set
    /// for a reused pre-existing backend, so Quit can never kill a process
    /// this app didn't start. Tracks the PyInstaller bootloader process.
    pub owned_child: Mutex<Option<CommandChild>>,
    /// Tracks the verified worker process spawned by the bootloader (if any),
    /// captured while the bootloader was alive and parentage was unambiguous.
    pub worker_identity: Mutex<Option<WorkerIdentity>>,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            owned_child: Mutex::new(None),
            worker_identity: Mutex::new(None),
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
    let url = backend_url("/api/health");
    match ureq::get(&url).timeout(Duration::from_secs(2)).call() {
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
                let port = backend_port();
                emit_status(
                    &app,
                    "error",
                    format!("Port {port} is already in use by something other than Jarvis. Stop that process, then relaunch."),
                );
                show_offline_window(&app);
                return;
            }
            HealthProbe::Unreachable => {
                // Nothing is listening — proceed to spawn our own.
            }
        }

        let state = app.state::<SidecarState>();
        let port_str = backend_port().to_string();
        let sidecar_cmd = match app.shell().sidecar("jarvis-backend") {
            Ok(cmd) => cmd.current_dir(BACKEND_DIR).args(["--port", &port_str]),
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
        let bootloader_pid = child.pid() as i32;
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
                    // Capture the worker process identity while bootloader is alive and parentage is unambiguous
                    if let Some(identity) = discover_worker_identity(bootloader_pid, backend_port()) {
                        *state.worker_identity.lock().unwrap() = Some(identity);
                    }
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
                // Stay quiet on repeated background checks
            }
        }
    }
}

/// Invoked by the offline diagnostic's "Retry Connection" button — runs
/// one immediate check outside the slower background cadence above.
#[tauri::command]
fn retry_connection(app: AppHandle) {
    match probe_health() {
        HealthProbe::Healthy => reveal_app(&app),
        HealthProbe::PortConflict => {
            let port = backend_port();
            emit_status(&app, "error", format!("Port {port} is still in use by something other than Jarvis."));
        }
        HealthProbe::Unreachable => {
            emit_status(&app, "error", "Still not reachable — still checking automatically in the background.");
        }
    }
}

/// Invoked by the offline diagnostic's "Show Logs" button — reveals log dir.
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

pub fn invoke_handler() -> impl Fn(tauri::ipc::Invoke) -> bool {
    tauri::generate_handler![retry_connection, reveal_log_folder]
}

fn reveal_app(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let app_url = backend_url("/");
        if let Ok(url) = app_url.parse() {
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

pub fn process_alive(pid: i32) -> bool {
    unsafe {
        if libc::kill(pid, 0) == 0 {
            true
        } else {
            let err = std::io::Error::last_os_error().raw_os_error();
            err == Some(libc::EPERM)
        }
    }
}

/// Retrieves the parent PID (PPID) of a process via `ps -o ppid= -p <pid>`.
pub fn get_parent_pid(pid: i32) -> Option<i32> {
    let output = std::process::Command::new("ps")
        .args(["-o", "ppid=", "-p", &pid.to_string()])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    String::from_utf8_lossy(&output.stdout)
        .trim()
        .parse::<i32>()
        .ok()
}

/// Retrieves all immediate child PIDs of `parent_pid` via `pgrep -P <parent_pid>`.
pub fn get_child_pids(parent_pid: i32) -> Vec<i32> {
    let Ok(output) = std::process::Command::new("pgrep")
        .args(["-P", &parent_pid.to_string()])
        .output()
    else {
        return Vec::new();
    };
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|l| l.trim().parse::<i32>().ok())
        .collect()
}

/// Retrieves all listening PIDs on the specified TCP port via `lsof`.
pub fn get_port_listeners(port: u16) -> Vec<i32> {
    let Ok(output) = std::process::Command::new("lsof")
        .args([&format!("-tiTCP:{port}"), "-sTCP:LISTEN", "-n", "-P"])
        .output()
    else {
        return Vec::new();
    };
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|l| l.trim().parse::<i32>().ok())
        .collect()
}

/// Reads the verified running PID recorded by `scripts/jarvisctl.sh` in $PID_FILE,
/// if alive. Returns None if the file is absent or the process is not alive.
pub fn get_controller_pid() -> Option<i32> {
    let runtime_dir = std::env::var("JARVIS_RUNTIME_DIR")
        .ok()
        .map(PathBuf::from)
        .or_else(|| {
            let home = std::env::var("JARVIS_HOME").ok().or_else(|| std::env::var("HOME").ok())?;
            Some(PathBuf::from(home).join("Library/Application Support/Jarvis"))
        })?;
    let pid_file = runtime_dir.join("run/backend.pid");
    let content = std::fs::read_to_string(pid_file).ok()?;
    let pid = content.trim().parse::<i32>().ok()?;
    if process_alive(pid) {
        Some(pid)
    } else {
        None
    }
}

/// Queries the live OS process table for the process start time and executable name.
/// Returns None if the process does not exist, has exited, or cannot be queried.
pub fn get_process_identity(pid: i32) -> Option<WorkerIdentity> {
    if !process_alive(pid) {
        return None;
    }
    let lstart_out = std::process::Command::new("ps")
        .args(["-o", "lstart=", "-p", &pid.to_string()])
        .output()
        .ok()?;
    if !lstart_out.status.success() {
        return None;
    }
    let start_time = String::from_utf8_lossy(&lstart_out.stdout).trim().to_string();
    if start_time.is_empty() {
        return None;
    }

    let comm_out = std::process::Command::new("ps")
        .args(["-o", "comm=", "-p", &pid.to_string()])
        .output()
        .ok()?;
    if !comm_out.status.success() {
        return None;
    }
    let comm = String::from_utf8_lossy(&comm_out.stdout).trim().to_string();
    if comm.is_empty() {
        return None;
    }

    Some(WorkerIdentity {
        pid,
        start_time,
        comm,
    })
}

/// Actively revalidates a remembered worker identity against the live OS process table
/// immediately before signalling.
///
/// Prevents signalling a recycled PID if the original worker died and the OS
/// assigned its PID to an unrelated process.
///
/// Must satisfy all of the following:
///   1. The process must be alive right now.
///   2. The process start time (ps -o lstart=) must exactly match the recorded start time.
///   3. The executable name (ps -o comm=) must match the recorded executable.
///   4. If the bootloader is still alive, the process PPID must match bootloader_pid.
///      If the bootloader has already exited, orphaned child must have been reparented to launchd (PID 1).
///   5. Must not match controller_pid.
pub fn revalidate_worker_identity(worker: &WorkerIdentity, bootloader_pid: i32) -> bool {
    let current = match get_process_identity(worker.pid) {
        Some(curr) => curr,
        None => return false,
    };

    // Revalidation 1: Process start time must match exactly (PID recycling guard)
    if current.start_time != worker.start_time {
        log::warn!(
            "[sidecar] remembered worker PID {} start time mismatch ('{}' != '{}'); PID was recycled, failing closed",
            worker.pid,
            current.start_time,
            worker.start_time
        );
        return false;
    }

    // Revalidation 2: Executable command/name must match
    if current.comm != worker.comm {
        log::warn!(
            "[sidecar] remembered worker PID {} comm mismatch ('{}' != '{}'); failing closed",
            worker.pid,
            current.comm,
            worker.comm
        );
        return false;
    }

    // Revalidation 3: If the bootloader is still alive, the worker's parent PID must be bootloader_pid.
    // If the bootloader has already exited, macOS reparents orphaned processes to launchd (PID 1).
    if let Some(ppid) = get_parent_pid(worker.pid) {
        if process_alive(bootloader_pid) {
            if ppid != bootloader_pid {
                log::warn!(
                    "[sidecar] remembered worker PID {} parent mismatch: expected bootloader {bootloader_pid}, found {ppid}",
                    worker.pid
                );
                return false;
            }
        } else if ppid != 1 {
            log::warn!(
                "[sidecar] bootloader {bootloader_pid} is dead, but worker PID {} was not reparented to launchd (ppid {ppid})",
                worker.pid
            );
            return false;
        }
    } else {
        return false;
    }

    // Revalidation 4: Controller PID check (never signal controller)
    if let Some(c_pid) = get_controller_pid() {
        if worker.pid == c_pid {
            return false;
        }
    }

    true
}

/// Returns true only when `candidate_pid` is proven to belong to the
/// owned sidecar process tree spawned by this Tauri instance:
///   1. Exactly equal to `bootloader_pid` (the direct spawned child).
///   2. A remembered worker identity that passes live OS revalidation (start_time, comm, PPID).
///   3. A direct child of `bootloader_pid` according to the OS (`ps -o ppid=`).
///   4. Listed in `pgrep -P bootloader_pid`.
///
/// Fails closed (returns false) if:
///   - The PID matches `controller_pid` (owned by scripts/jarvisctl.sh).
///   - The PID is an unverified, separate process, even if its executable
///     happens to be named "jarvis-backend".
///   - The cached worker identity fails revalidation (e.g. recycled PID).
///   - Ownership is ambiguous or cannot be verified.
pub fn is_owned_process(
    candidate_pid: i32,
    bootloader_pid: i32,
    known_worker: Option<&WorkerIdentity>,
    controller_pid: Option<i32>,
) -> bool {
    // If the process is known to be owned by jarvisctl.sh, fail closed: never touch it.
    if let Some(c_pid) = controller_pid {
        if candidate_pid == c_pid {
            return false;
        }
    }

    if candidate_pid == bootloader_pid {
        return true;
    }

    // A candidate PID matching a cached worker is NEVER trusted on bare PID alone:
    // It must pass live revalidation against the OS process table right now.
    if let Some(worker) = known_worker {
        if candidate_pid == worker.pid {
            return revalidate_worker_identity(worker, bootloader_pid);
        }
    }

    if let Some(ppid) = get_parent_pid(candidate_pid) {
        if ppid == bootloader_pid {
            return true;
        }
    }

    let children = get_child_pids(bootloader_pid);
    if children.contains(&candidate_pid) {
        return true;
    }

    false
}

/// Attempts to discover and fingerprint the listening worker process spawned by `bootloader_pid`.
pub fn discover_worker_identity(bootloader_pid: i32, port: u16) -> Option<WorkerIdentity> {
    let controller_pid = get_controller_pid();
    for l_pid in get_port_listeners(port) {
        if is_owned_process(l_pid, bootloader_pid, None, controller_pid) {
            return get_process_identity(l_pid);
        }
    }
    // Also check direct children via pgrep
    for c_pid in get_child_pids(bootloader_pid) {
        if is_owned_process(c_pid, bootloader_pid, None, controller_pid) {
            return get_process_identity(c_pid);
        }
    }
    None
}

/// Stops only a sidecar this app itself spawned. Never touches a reused,
/// pre-existing backend — matching the project rules' "never kill a process the
/// app did not start."
///
/// Handles the real macOS / PyInstaller onefile shape:
///   - Tauri spawns the PyInstaller bootloader (`bootloader_pid`).
///   - The bootloader extracts to a temp directory and forks a child worker process.
///   - Sending SIGTERM/SIGKILL blindly to bootloader alone can orphan the worker
///     (reparenting it to launchd / PID 1) while still bound to the backend port.
///   - Lineage is verified BEFORE terminating the bootloader, ensuring both
///     bootloader and worker are tracked.
///   - Fails closed on any ambiguous PID or foreign process with the same name.
pub fn shutdown_owned_backend(app: &AppHandle) {
    let taken = {
        let state = app.state::<SidecarState>();
        let child = state.owned_child.lock().unwrap().take();
        child
    };
    let Some(child) = taken else { return };

    let bootloader_pid = child.pid() as i32;
    let worker_identity = {
        let state = app.state::<SidecarState>();
        let w = state.worker_identity.lock().unwrap().take();
        w
    };
    let port = backend_port();

    shutdown_process_tree(child, bootloader_pid, worker_identity, port);
}

/// Shuts down the owned process tree with full lineage verification and fail-closed safety.
pub fn shutdown_process_tree(
    child: CommandChild,
    bootloader_pid: i32,
    worker_identity: Option<WorkerIdentity>,
    port: u16,
) {
    let controller_pid = get_controller_pid();
    log::info!("[sidecar] stopping app-owned backend (bootloader PID {bootloader_pid}, worker {worker_identity:?}) on port {port}");

    // Collect all verified owned PIDs while process hierarchy is intact
    let mut verified_pids = vec![bootloader_pid];

    // Revalidate remembered worker identity IMMEDIATELY before signalling
    if let Some(ref worker) = worker_identity {
        if is_owned_process(worker.pid, bootloader_pid, Some(worker), controller_pid) {
            if !verified_pids.contains(&worker.pid) {
                verified_pids.push(worker.pid);
            }
        } else {
            log::warn!(
                "[sidecar] remembered worker PID {} failed live revalidation; skipping signal (fail-closed)",
                worker.pid
            );
        }
    }
    for c_pid in get_child_pids(bootloader_pid) {
        if is_owned_process(c_pid, bootloader_pid, worker_identity.as_ref(), controller_pid)
            && !verified_pids.contains(&c_pid)
        {
            verified_pids.push(c_pid);
        }
    }
    for l_pid in get_port_listeners(port) {
        if is_owned_process(l_pid, bootloader_pid, worker_identity.as_ref(), controller_pid)
            && !verified_pids.contains(&l_pid)
        {
            verified_pids.push(l_pid);
        }
    }

    // 1. Send SIGTERM to all verified owned processes
    for &pid in &verified_pids {
        if process_alive(pid) {
            unsafe {
                libc::kill(pid, libc::SIGTERM);
            }
        }
    }

    // 2. Wait up to 2 seconds for verified PIDs to exit gracefully
    for _ in 0..20 {
        let any_alive = verified_pids.iter().any(|&pid| process_alive(pid));
        if !any_alive {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    // 3. SIGKILL any surviving verified owned processes
    for &pid in &verified_pids {
        if process_alive(pid) {
            log::warn!("[sidecar] verified owned pid {pid} did not exit after SIGTERM; sending SIGKILL");
            unsafe {
                libc::kill(pid, libc::SIGKILL);
            }
        }
    }
    let _ = child.kill();

    // 4. Defensive port check: verify whether any process on the port is genuinely ours
    kill_surviving_verified_port_owner(port, &verified_pids, controller_pid);
}

/// Defensive verification pass: inspect whatever is listening on the port.
/// Kill it ONLY if it is proven to be in `verified_pids`.
/// If the listener matches `controller_pid` or is unverified/ambiguous, FAIL CLOSED: do not kill.
pub fn kill_surviving_verified_port_owner(
    port: u16,
    verified_pids: &[i32],
    controller_pid: Option<i32>,
) {
    let listeners = get_port_listeners(port);
    for pid in listeners {
        if Some(pid) == controller_pid {
            log::info!("[sidecar] port {port} is held by controller-owned PID {pid}; leaving alive");
            continue;
        }
        if verified_pids.contains(&pid) {
            log::warn!("[sidecar] port {port} still held by our own verified pid {pid} after shutdown; killing it directly");
            unsafe {
                libc::kill(pid, libc::SIGKILL);
            }
        } else {
            // Ownership is ambiguous or belongs to a separate process: FAIL CLOSED
            log::warn!(
                "[sidecar] port {port} is held by unverified PID {pid}; leaving untouched (fail-closed)"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use std::process::Command;

    #[test]
    fn test_is_owned_process_logic() {
        let mut dummy = Command::new("sleep")
            .arg("10")
            .spawn()
            .expect("Failed to spawn dummy child");
        let worker_pid = dummy.id() as i32;
        let bootloader_pid = std::process::id() as i32;
        let controller_pid = 999999;

        // Bootloader itself is always owned
        assert!(is_owned_process(bootloader_pid, bootloader_pid, None, None));

        // Revalidated worker identity is owned
        let worker_identity = get_process_identity(worker_pid);
        assert!(is_owned_process(worker_pid, bootloader_pid, worker_identity.as_ref(), None));

        // Controller process is NEVER owned (fail closed)
        assert!(!is_owned_process(controller_pid, bootloader_pid, worker_identity.as_ref(), Some(controller_pid)));

        // Unrelated PID is not owned
        assert!(!is_owned_process(999998, bootloader_pid, worker_identity.as_ref(), Some(controller_pid)));

        let _ = dummy.kill();
        let _ = dummy.wait();
    }

    #[test]
    fn test_revalidate_worker_identity_guards_against_recycled_or_tampered_pid() {
        // Spawn a real child process to act as our worker
        let mut worker_child = Command::new("sleep")
            .arg("30")
            .spawn()
            .expect("Failed to spawn worker child");
        let worker_pid = worker_child.id() as i32;
        let parent_pid = std::process::id() as i32;

        let genuine_identity = get_process_identity(worker_pid)
            .expect("Must be able to query identity of live worker");

        // 1. Genuine identity with matching parent and live process passes revalidation
        assert!(revalidate_worker_identity(&genuine_identity, parent_pid));
        assert!(is_owned_process(worker_pid, parent_pid, Some(&genuine_identity), None));

        // 2. Tampered start time (simulating PID recycling by OS where new process was assigned the same PID):
        // Revalidation MUST fail closed!
        let recycled_identity = WorkerIdentity {
            pid: worker_pid,
            start_time: "Sun Jan  1 00:00:00 2000".to_string(),
            comm: genuine_identity.comm.clone(),
        };
        assert!(!revalidate_worker_identity(&recycled_identity, parent_pid));
        assert!(!is_owned_process(worker_pid, parent_pid, Some(&recycled_identity), None));

        // 3. Tampered comm (simulating unrelated process reusing PID):
        // Revalidation MUST fail closed!
        let wrong_comm_identity = WorkerIdentity {
            pid: worker_pid,
            start_time: genuine_identity.start_time.clone(),
            comm: "unrelated-app".to_string(),
        };
        assert!(!revalidate_worker_identity(&wrong_comm_identity, parent_pid));
        assert!(!is_owned_process(worker_pid, parent_pid, Some(&wrong_comm_identity), None));

        // 4. Parent mismatch while parent is alive:
        // If bootloader is alive, PPID must match bootloader_pid. An unrelated parent MUST fail closed.
        let mut unrelated_child = Command::new("sleep")
            .arg("10")
            .spawn()
            .expect("Failed to spawn unrelated child");
        let unrelated_parent = unrelated_child.id() as i32;
        assert!(!revalidate_worker_identity(&genuine_identity, unrelated_parent));
        assert!(!is_owned_process(worker_pid, unrelated_parent, Some(&genuine_identity), None));
        let _ = unrelated_child.kill();
        let _ = unrelated_child.wait();

        // 5. Terminated worker (dead PID):
        let _ = worker_child.kill();
        let _ = worker_child.wait();
        assert!(!process_alive(worker_pid));
        assert!(!revalidate_worker_identity(&genuine_identity, parent_pid));
        assert!(!is_owned_process(worker_pid, parent_pid, Some(&genuine_identity), None));
    }

    #[test]
    fn test_reproduce_owned_vs_separately_launched_process_with_same_executable_name() {
        let test_dir = std::env::temp_dir().join(format!("jarvis-test-sidecar-{}", std::process::id()));
        fs::create_dir_all(&test_dir).unwrap();

        // Create an executable script named "jarvis-backend"
        // Simulates the PyInstaller launch shape:
        // When run with `--bootloader <file>`, it spawns a child worker and writes its PID to <file>.
        let bin_path = test_dir.join("jarvis-backend");
        let worker_pid_file = test_dir.join("worker.pid");
        let script = r#"#!/bin/sh
if [ "$1" = "--bootloader" ]; then
    "$0" --worker &
    echo $! > "$2"
    trap 'exit 0' TERM INT
    while true; do
        sleep 1 &
        wait $!
    done
elif [ "$1" = "--worker" ]; then
    trap 'exit 0' TERM INT
    while true; do
        sleep 1 &
        wait $!
    done
else
    # Standalone separate process
    trap 'exit 0' TERM INT
    while true; do
        sleep 1 &
        wait $!
    done
fi
"#;
        fs::write(&bin_path, script).unwrap();
        let mut perms = fs::metadata(&bin_path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&bin_path, perms).unwrap();

        // 1. Spawn Process 1 (simulating our owned bootloader sidecar)
        let mut owned_child = Command::new(&bin_path)
            .args(["--bootloader", worker_pid_file.to_str().unwrap()])
            .spawn()
            .expect("Failed to spawn owned bootloader child");
        let owned_bootloader_pid = owned_child.id() as i32;

        // Wait for the bootloader to spawn its worker and write its PID
        let mut owned_worker_pid = 0;
        for _ in 0..20 {
            if let Ok(content) = fs::read_to_string(&worker_pid_file) {
                if let Ok(pid) = content.trim().parse::<i32>() {
                    if process_alive(pid) {
                        owned_worker_pid = pid;
                        break;
                    }
                }
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        assert!(owned_worker_pid > 0, "Bootloader failed to spawn child worker");

        // 2. Spawn Process 2: a SEPARATELY launched process with the EXACT SAME executable name "jarvis-backend"
        let mut separate_process = Command::new(&bin_path)
            .spawn()
            .expect("Failed to spawn separate process");
        let separate_pid = separate_process.id() as i32;

        // Give them a moment to settle
        std::thread::sleep(Duration::from_millis(50));

        // Assert all 3 processes are alive
        assert!(process_alive(owned_bootloader_pid));
        assert!(process_alive(owned_worker_pid));
        assert!(process_alive(separate_pid));

        // Obtain worker identity
        let owned_worker_identity = get_process_identity(owned_worker_pid);
        assert!(owned_worker_identity.is_some());

        // Lineage verification directly via macOS process table:
        // - owned_bootloader_pid is recognized as owned
        assert!(is_owned_process(owned_bootloader_pid, owned_bootloader_pid, None, None));

        // - owned_worker_pid has PPID == owned_bootloader_pid in macOS kernel:
        let os_ppid = get_parent_pid(owned_worker_pid);
        assert_eq!(os_ppid, Some(owned_bootloader_pid));
        let os_children = get_child_pids(owned_bootloader_pid);
        assert!(os_children.contains(&owned_worker_pid));

        // - owned_worker_pid is recognized as owned via OS parentage WITHOUT known_worker passed!
        assert!(is_owned_process(owned_worker_pid, owned_bootloader_pid, None, None));

        // - owned_worker_pid is also recognized via revalidated worker identity:
        assert!(is_owned_process(owned_worker_pid, owned_bootloader_pid, owned_worker_identity.as_ref(), None));

        // - separate_pid has the EXACT same executable name, but was launched separately.
        // It MUST NOT be recognized as owned!
        assert!(!is_owned_process(separate_pid, owned_bootloader_pid, owned_worker_identity.as_ref(), None));

        // Now simulate the shutdown procedure on the owned instance:
        // We track verified owned PIDs: [owned_bootloader_pid, owned_worker_pid]
        let verified_pids = vec![owned_bootloader_pid, owned_worker_pid];

        // Send SIGTERM to verified owned PIDs
        for &pid in &verified_pids {
            if process_alive(pid) {
                unsafe { libc::kill(pid, libc::SIGTERM); }
            }
        }

        // Wait up to 1 second for graceful exit, reaping child status
        for _ in 0..10 {
            let _ = owned_child.try_wait();
            if !process_alive(owned_bootloader_pid) && !process_alive(owned_worker_pid) {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }

        // Send SIGKILL to any surviving verified owned PIDs (mirroring shutdown step 3)
        for &pid in &verified_pids {
            let _ = owned_child.try_wait();
            if process_alive(pid) {
                unsafe { libc::kill(pid, libc::SIGKILL); }
            }
        }
        let _ = owned_child.kill();
        let _ = owned_child.wait();
        if process_alive(owned_worker_pid) {
            unsafe { libc::kill(owned_worker_pid, libc::SIGKILL); }
        }

        // Verify: Owned bootloader and worker are TERMINATED
        assert!(!process_alive(owned_bootloader_pid), "Owned bootloader should be terminated");
        assert!(!process_alive(owned_worker_pid), "Owned worker should be terminated");

        // Verify: SEPARATELY launched process with same executable name is STILL ALIVE!
        assert!(process_alive(separate_pid), "Separately launched jarvis-backend process must remain alive!");

        // Test defensive port check fail-closed behavior:
        // Even if separate_pid was somehow listening on a port, kill_surviving_verified_port_owner must NOT kill it
        let fake_port = 59999;
        kill_surviving_verified_port_owner(fake_port, &verified_pids, None);
        assert!(process_alive(separate_pid), "Fail-closed check must leave separate_pid alive");

        // Clean up separate process
        let _ = separate_process.kill();
        let _ = separate_process.wait();
        let _ = fs::remove_dir_all(&test_dir);
    }

    #[test]
    fn test_controller_pid_resolution_and_fail_closed() {
        let test_dir = std::env::temp_dir().join(format!("jarvis-test-controller-{}", std::process::id()));
        let run_dir = test_dir.join("run");
        fs::create_dir_all(&run_dir).unwrap();

        // Spawn a dummy process to serve as our controller-owned backend
        let mut dummy = Command::new("sleep")
            .arg("10")
            .spawn()
            .expect("Failed to spawn dummy controller backend");
        let dummy_pid = dummy.id() as i32;

        let pid_file = run_dir.join("backend.pid");
        fs::write(&pid_file, dummy_pid.to_string()).unwrap();

        // Point JARVIS_RUNTIME_DIR to our test directory
        std::env::set_var("JARVIS_RUNTIME_DIR", &test_dir);

        let resolved_controller = get_controller_pid();
        assert_eq!(resolved_controller, Some(dummy_pid));

        // Verify is_owned_process refuses to claim a controller-owned PID
        assert!(!is_owned_process(dummy_pid, 9999, None, Some(dummy_pid)));

        // Clean up
        std::env::remove_var("JARVIS_RUNTIME_DIR");
        let _ = dummy.kill();
        let _ = dummy.wait();
        let _ = fs::remove_dir_all(&test_dir);
    }
}
