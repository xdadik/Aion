// Aion Hand — Tauri lib (app core).

use log::info;
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{Manager, State};

// ── App state ───────────────────────────────────────────────────────────────

struct AppState {
    api_base_url: Mutex<String>,
    api_token: Mutex<Option<String>>,
}

#[derive(Default)]
struct Stats {
    messages_sent: Mutex<u32>,
    tokens_used: Mutex<u64>,
}

// ── Commands callable from the frontend ─────────────────────────────────────

#[derive(Serialize, Deserialize)]
struct ChatResponse {
    content: String,
    tools_used: Vec<serde_json::Value>,
    tokens: u64,
    elapsed_ms: u64,
}

/// Send a chat message to the Aion backend.
#[tauri::command]
async fn send_chat(
    state: State<'_, AppState>,
    stats: State<'_, Stats>,
    message: String,
    persona: Option<String>,
) -> Result<ChatResponse, String> {
    let start = std::time::Instant::now();
    let base_url = state.api_base_url.lock().unwrap().clone();
    let token = state.api_token.lock().unwrap().clone();

    let client = reqwest::Client::new();
    let mut req = client
        .post(format!("{}/api/chat", base_url))
        .json(&serde_json::json!({
            "message": message,
        }));
    if let Some(t) = token {
        req = req.header("Authorization", format!("Bearer {}", t));
    }
    if let Some(p) = persona {
        // Apply the persona first (best-effort — ignore errors)
        let _ = client
            .post(format!("{}/api/personas/apply", base_url))
            .json(&serde_json::json!({"name": p}))
            .send()
            .await;
    }

    let resp = req
        .send()
        .await
        .map_err(|e| format!("HTTP request failed: {}", e))?;
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))?;

    let content = body
        .get("content")
        .and_then(|v| v.as_str())
        .unwrap_or("(no response)")
        .to_string();
    let tools_used = body
        .get("tools_used")
        .cloned()
        .unwrap_or_else(|| serde_json::Value::Array(vec![]));
    let tokens = body
        .pointer("/metadata/total_tokens")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);

    let elapsed_ms = start.elapsed().as_millis() as u64;

    // Update stats
    *stats.messages_sent.lock().unwrap() += 1;
    *stats.tokens_used.lock().unwrap() += tokens;

    Ok(ChatResponse {
        content,
        tools_used: tools_used.as_array().cloned().unwrap_or_default(),
        tokens,
        elapsed_ms,
    })
}

/// List available personas from the backend.
#[tauri::command]
async fn list_personas(state: State<'_, AppState>) -> Result<Vec<String>, String> {
    let base_url = state.api_base_url.lock().unwrap().clone();
    let client = reqwest::Client::new();
    let resp = client
        .get(format!("{}/api/personas", base_url))
        .send()
        .await
        .map_err(|e| format!("HTTP request failed: {}", e))?;
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse response: {}", e))?;
    let personas = body
        .get("personas")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|v| v.as_str().map(String::from)).collect())
        .unwrap_or_default();
    Ok(personas)
}

/// Check the backend health.
#[tauri::command]
async fn check_health(state: State<'_, AppState>) -> Result<bool, String> {
    let base_url = state.api_base_url.lock().unwrap().clone();
    let client = reqwest::Client::new();
    match client
        .get(format!("{}/health/live", base_url))
        .timeout(std::time::Duration::from_secs(3))
        .send()
        .await
    {
        Ok(resp) => Ok(resp.status().is_success()),
        Err(_) => Ok(false),
    }
}

/// Get app stats.
#[tauri::command]
fn get_stats(stats: State<'_, Stats>) -> serde_json::Value {
    serde_json::json!({
        "messages_sent": *stats.messages_sent.lock().unwrap(),
        "tokens_used": *stats.tokens_used.lock().unwrap(),
    })
}

/// Configure the backend URL.
#[tauri::command]
fn set_api_url(state: State<'_, AppState>, url: String) -> Result<(), String> {
    *state.api_base_url.lock().unwrap() = url;
    Ok(())
}

/// Configure the API token.
#[tauri::command]
fn set_api_token(state: State<'_, AppState>, token: Option<String>) -> Result<(), String> {
    *state.api_token.lock().unwrap() = token;
    Ok(())
}

// ── Run ─────────────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_secs()
        .init();

    info!("Aion Hand desktop starting up…");

    let state = AppState {
        api_base_url: Mutex::new("http://localhost:8000".to_string()),
        api_token: Mutex::new(None),
    };
    let stats = Stats::default();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .manage(state)
        .manage(stats)
        .invoke_handler(tauri::generate_handler![
            send_chat,
            list_personas,
            check_health,
            get_stats,
            set_api_url,
            set_api_token,
        ])
        .setup(|_app| {
            #[cfg(debug_assertions)]
            {
                if let Some(window) = _app.get_webview_window("main") {
                    window.open_devtools();
                }
            }
            info!("Aion Hand desktop ready");
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                info!("Window '{}' closing", window.title().unwrap_or_default());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
