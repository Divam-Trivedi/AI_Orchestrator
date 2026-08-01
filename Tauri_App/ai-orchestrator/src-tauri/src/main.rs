// Prevents additional console window on Windows in the background
#![cfg_attr(windows_env_options, windows_subsystem = "windows")]

use tauri::Manager;
use std::process::{Command, Child};
use std::sync::Mutex;
use std::sync::Arc;

// Global state to keep track of the backend and ollama processes
struct AppState {
    backend_process: Mutex<Option<Child>>,
    ollama_process: Mutex<Option<Child>>,
}

fn main() {
    // Setup state
    let state = Arc::new(AppState {
        backend_process: Mutex::new(None),
        ollama_process: Mutex::new(None),
    });

    tauri::Builder::default()
        .manage(state.clone())
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            let state = app.state::<Arc<AppState>>();

            // 1. Try to launch Ollama if installed
            let ollama_handle = Command::new("ollama")
                .arg("serve")
                .spawn();

            match ollama_handle {
                Ok(child) => {
                    println!("Ollama started successfully");
                    *state.ollama_process.lock().unwrap() = Some(child);
                }
                Err(_) => println!("Ollama not found or already running, skipping..."),
            }

            // 2. Launch the Python Backend Sidecar
            // Tauri looks for the binary in the binaries folder automatically
            let backend_handle = Command::new_sidecar("main")
                .arg("--db-path")
                .arg(format!("{}/ai_orchestrator.db", app.path_resolver().app_data_dir().unwrap_or_else(|| std::path::PathBuf::from(".")).to_str().unwrap()))
                .spawn();

            match backend_handle {
                Ok(child) => {
                    println!("Backend server started successfully");
                    *state.backend_process.lock().unwrap() = Some(child);
                }
                Err(e) => {
                    eprintln!("Failed to start backend server: {}", e);
                }
            }

            Ok(())
        })
        .on_window_event(move |event| {
            // 3. Cleanup: Kill processes when window closes
            if let tauri::WindowEvent::CloseRequested = event.event() {
                let state = event.window().state::<Arc<AppState>>();
                
                if let Some(child) = state.backend_process.lock().unwrap().take() {
                    let _ = child.kill();
                    println!("Backend process terminated.");
                }
                if let Some(child) = state.ollama_process.lock().unwrap().take() {
                    let _ = child.kill();
                    println!("Ollama process terminated.");
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

// Helper extension to make launching sidecars easier
trait CommandExt {
    fn new_sidecar(&self, name: &str) -> std::process::Command;
}

impl CommandExt for std::process::Command {
    fn new_sidecar(&self, name: &str) -> std::process::Command {
        // This is a simplified version for demonstration
        // In real Tauri, sidecars are managed via tauri::api::process::Command
        // But for a simple wrapper, we call the binary by its target name
        let binary_path = format!("./binaries/{}-aarch64-apple-darwin", name);
        std::process::Command::new(binary_path)
    }
}
