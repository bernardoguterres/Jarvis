use std::path::PathBuf;

fn main() {
    // Native packaging targets exactly this one real Mac and this one real
    // repo checkout — there is no distributed installer. The sidecar still
    // needs to read backend/.env (Hermes bearer token, non-secret config)
    // via its cwd, and that source-tree location isn't inside the .app
    // bundle, so it's baked in at build time from CARGO_MANIFEST_DIR.
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let backend_dir = manifest_dir
        .parent() // frontend/
        .expect("src-tauri has a parent directory")
        .parent() // repo root
        .expect("frontend has a parent directory")
        .join("backend");
    println!(
        "cargo:rustc-env=JARVIS_BACKEND_DIR={}",
        backend_dir.display()
    );

    // Registers a real permission ("allow-retry-connection") for the one
    // custom app command (src/lib.rs's `retry_connection`) so the offline
    // diagnostic's Retry button can invoke it — app-defined commands need
    // an explicit ACL entry the same way plugin commands do.
    let attributes = tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["retry_connection", "reveal_log_folder"]),
    );
    tauri_build::try_build(attributes).expect("tauri_build::try_build failed");
}
