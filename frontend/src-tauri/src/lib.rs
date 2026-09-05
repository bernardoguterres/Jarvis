mod sidecar;

use tauri::menu::{CheckMenuItemBuilder, MenuBuilder, MenuItemBuilder};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, WindowEvent};
use tauri_plugin_autostart::ManagerExt as AutostartManagerExt;

const INTEGRATIONS_SYNC_CALENDAR: &str = "http://127.0.0.1:8000/api/integrations/google_calendar/sync";
const INTEGRATIONS_SYNC_HEALTH: &str = "http://127.0.0.1:8000/api/integrations/google_health/sync";
const EXPORT_URL: &str = "http://127.0.0.1:8000/api/export";
const DATA_DIR_URL: &str = "http://127.0.0.1:8000/api/data-dir";

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Single-instance MUST be registered before any other plugin
        // (Tauri's own documented requirement) — a second launch focuses
        // the existing window and exits, so exactly one backend is ever
        // owned by this app.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .invoke_handler(sidecar::invoke_handler())
        .manage(sidecar::SidecarState::new())
        .setup(|app| {
            // Always installed, not just in debug builds — a release
            // build has no other way to leave a real, timestamped record
            // of a launch (lifecycle events plus every drained backend
            // stdout/stderr line, see sidecar.rs) for diagnosing a failed
            // startup after the fact. Written under the app's own log
            // directory (macOS: ~/Library/Logs/Jarvis) as well as stdout,
            // so a Terminal-launched run still shows it live too.
            app.handle().plugin(
                tauri_plugin_log::Builder::default()
                    .level(log::LevelFilter::Info)
                    .targets([
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                        tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
                            file_name: Some("jarvis".into()),
                        }),
                    ])
                    .build(),
            )?;

            // Launch at Login starts disabled until Bernardo enables it
            // from the installed app (CLAUDE.md §Stage-1 requirement) —
            // the autostart plugin defaults to disabled and nothing here
            // enables it.
            let autostart_enabled = app.autolaunch().is_enabled().unwrap_or(false);

            let open_item = MenuItemBuilder::with_id("open", "Open Jarvis").build(app)?;
            let hide_item = MenuItemBuilder::with_id("hide", "Hide Jarvis").build(app)?;
            let status_item = MenuItemBuilder::with_id("status", "System Status").build(app)?;
            let sync_item = MenuItemBuilder::with_id("sync", "Sync Integrations").build(app)?;
            let export_item =
                MenuItemBuilder::with_id("export_backup", "Export Portable Jarvis Backup").build(app)?;
            let restore_item =
                MenuItemBuilder::with_id("restore_backup", "Restore from Jarvis Export…").build(app)?;
            let reveal_item =
                MenuItemBuilder::with_id("reveal_data_folder", "Reveal Jarvis Data Folder").build(app)?;
            let launch_at_login_item = CheckMenuItemBuilder::with_id("launch_at_login", "Launch Jarvis at Login")
                .checked(autostart_enabled)
                .build(app)?;
            let quit_item = MenuItemBuilder::with_id("quit", "Quit Jarvis").build(app)?;

            let tray_menu = MenuBuilder::new(app)
                .item(&open_item)
                .item(&hide_item)
                .separator()
                .item(&status_item)
                .item(&sync_item)
                .separator()
                .item(&export_item)
                .item(&restore_item)
                .item(&reveal_item)
                .separator()
                .item(&launch_at_login_item)
                .separator()
                .item(&quit_item)
                .build()?;

            // A real macOS menu-bar template image (black-on-transparent,
            // 18x18 + @2x 36x36) rather than the full-color app icon at
            // tray size — this is what makes it clearly visible and
            // correctly auto-tinted for light/dark menu bars and
            // hover/click states, matching every other native macOS menu
            // bar icon's convention.
            let tray_icon = tauri::image::Image::from_bytes(include_bytes!(
                "../icons/tray/tray-icon@2x.png"
            ))?;

            TrayIconBuilder::new()
                .icon(tray_icon)
                .menu(&tray_menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                    "hide" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.hide();
                        }
                    }
                    "status" => {
                        // Single-URL SPA (no client-side routing) — Home
                        // itself already surfaces the real NOW/NEXT/WATCH
                        // integration/routine health briefing, so this is
                        // truthfully equivalent to "Open Jarvis" for now
                        // rather than inventing a deep-link route.
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                    "sync" => {
                        let app_handle = app.clone();
                        std::thread::spawn(move || {
                            for url in [INTEGRATIONS_SYNC_CALENDAR, INTEGRATIONS_SYNC_HEALTH] {
                                match ureq::post(url).call() {
                                    Ok(_) => log::info!("[tray] triggered sync: {url}"),
                                    Err(err) => log::warn!("[tray] sync failed for {url}: {err}"),
                                }
                            }
                            let _ = app_handle;
                        });
                    }
                    "export_backup" => {
                        // Safe, non-destructive, idempotent — a direct
                        // one-click action, unlike restore below.
                        std::thread::spawn(|| match ureq::post(EXPORT_URL).call() {
                            Ok(_) => log::info!("[tray] export created"),
                            Err(err) => log::warn!("[tray] export failed: {err}"),
                        });
                    }
                    "restore_backup" => {
                        // Restoring replaces this Mac's live database — the
                        // guarded confirmation flow lives entirely in the
                        // Data Management screen (see
                        // frontend/src/views/DataManagement.tsx); this menu
                        // item only ever brings Jarvis to the front, the
                        // same as "Open Jarvis", never performs the
                        // restore itself.
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.unminimize();
                            let _ = window.set_focus();
                        }
                    }
                    "reveal_data_folder" => {
                        std::thread::spawn(|| {
                            let path = match ureq::get(DATA_DIR_URL).call() {
                                Ok(response) => response
                                    .into_string()
                                    .ok()
                                    .and_then(|body| serde_json::from_str::<serde_json::Value>(&body).ok())
                                    .and_then(|v| v.get("path").and_then(|p| p.as_str()).map(str::to_owned)),
                                Err(err) => {
                                    log::warn!("[tray] could not resolve data dir: {err}");
                                    None
                                }
                            };
                            if let Some(path) = path {
                                if let Err(err) = std::process::Command::new("open").arg(&path).spawn() {
                                    log::warn!("[tray] could not reveal {path} in Finder: {err}");
                                }
                            }
                        });
                    }
                    "launch_at_login" => {
                        let autolaunch = app.autolaunch();
                        let currently_enabled = autolaunch.is_enabled().unwrap_or(false);
                        let result = if currently_enabled {
                            autolaunch.disable()
                        } else {
                            autolaunch.enable()
                        };
                        if let Err(err) = result {
                            log::warn!("[tray] could not change Launch at Login: {err}");
                        }
                    }
                    "quit" => {
                        sidecar::shutdown_owned_backend(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            sidecar::start(app.handle().clone());

            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window hides the app instead of terminating it —
            // scheduled integration syncs and routines keep running in the
            // backend regardless (CLAUDE.md's "remain active from the menu
            // bar when its window is hidden"). Only an actual Quit (tray
            // menu, Cmd+Q, or Dock ▸ Quit — handled below) stops anything.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| match event {
            // Covers every real exit path, not just the tray's own Quit
            // item — Cmd+Q and Dock ▸ Quit route through ExitRequested too,
            // and an owned sidecar must be stopped on all of them alike.
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                sidecar::shutdown_owned_backend(app_handle);
            }
            // Fires when the Dock icon of an already-running app with no
            // visible window is clicked — the standard way a macOS user
            // reopens a hidden app. Without this, hiding the window (see
            // the CloseRequested handler above) leaves no way back in
            // except the tray menu or a second `open` launch.
            tauri::RunEvent::Reopen { .. } => {
                if let Some(window) = app_handle.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            }
            _ => {}
        });
}
