# Aion Hand — Native Desktop App (Tauri)

Aion Hand ships as a native desktop app for **macOS, Windows, and Linux**, built with [Tauri 2.0](https://tauri.app). The desktop app wraps the existing Next.js web UI in a native webview and provides direct access to local system resources (filesystem, notifications, clipboard, native dialogs) via Tauri plugins.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Aion Hand Desktop App                       │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Tauri Window (1280×800, dark theme)                  │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │  Next.js Web UI (aion_web/)                      │  │  │
│  │  │  • Dashboard (/)                                 │  │  │
│  │  │  • Chat (/chat)                                  │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
│                          ↕ Tauri IPC                         │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Rust backend (src-tauri/src/lib.rs)                  │  │
│  │  • send_chat(persona?) → ChatResponse                 │  │
│  │  • list_personas() → [String]                         │  │
│  │  • check_health() → bool                              │  │
│  │  • get_stats() → {messages_sent, tokens_used}         │  │
│  │  • set_api_url(url)                                   │  │
│  │  • set_api_token(token?)                              │  │
│  └────────────────────────────────────────────────────────┘  │
│                          ↕ HTTP                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Aion HTTP API server (aion_core/api/)                │  │
│  │  Default: http://localhost:8000                       │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

The desktop app talks to the Aion HTTP API server (`aion-hand serve`) via HTTP, just like the web UI does. The Rust layer provides:

- Native window chrome (close/minimize/maximize buttons)
- System tray icon with menu
- Native file open/save dialogs
- Desktop notifications
- Clipboard read/write
- Persistent window size/position (via OS)

## Prerequisites

### All platforms
- [Node.js](https://nodejs.org/) 18+ (for the Next.js frontend)
- [Rust](https://www.rust-lang.org/tools/install) 1.70+ (for the Tauri backend)
- The Aion Hand Python package: `pip install -e ".[all]"`

### macOS
- Xcode Command Line Tools: `xcode-select --install`

### Windows
- Microsoft Visual C++ Build Tools (or Visual Studio with C++ workload)
- WebView2 (preinstalled on Windows 11; download on Windows 10)

### Linux
- `webkit2gtk-4.1`, `libgtk-3-dev`, `libappindicator3-dev`, `librsvg2-dev`
  - Debian/Ubuntu: `sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libappindicator3-dev librsvg2-dev patchelf`
  - Fedora: `sudo dnf install webkit2gtk4.1-devel gtk3-devel libappindicator-gtk3-devel librsvg2-devel`
  - Arch: `sudo pacman -S webkit2gtk-4.1 gtk3 libappindicator-gtk3 librsvg`

## Development

```bash
# 1. Start the Aion HTTP API server (in one terminal)
aion-hand serve --port 8000

# 2. Start the desktop dev environment (in another terminal)
cd desktop/src-tauri
cargo tauri dev
```

This will:
1. Build the Next.js web UI in dev mode (hot reload)
2. Open a native desktop window pointing at http://localhost:3000
3. Hot-reload both the frontend and Rust backend on changes

## Production build

```bash
cd desktop/src-tauri
cargo tauri build
```

This produces installable bundles in `desktop/src-tauri/target/release/bundle/`:
- **macOS**: `.app` and `.dmg`
- **Windows**: `.exe` (NSIS installer) and `.msi`
- **Linux**: `.deb`, `.AppImage`, and `.rpm`

## Configuration

The desktop app connects to `http://localhost:8000` by default. To change this:

1. Open the desktop app settings (gear icon in the header)
2. Set the API URL to your Aion server (e.g., `https://aion.example.com`)
3. Optionally set an API token for authentication

Settings persist in the OS's native app config directory:
- macOS: `~/Library/Application Support/com.aionhand.desktop/`
- Windows: `%APPDATA%\com.aionhand.desktop\`
- Linux: `~/.config/com.aionhand.desktop/`

## Building for release (CI/CD)

A GitHub Actions workflow for cross-platform desktop builds is planned. The matrix will cover:

| Platform | Target | Output |
|---|---|---|
| macOS (Intel) | `x86_64-apple-darwin` | `.dmg`, `.app` |
| macOS (Apple Silicon) | `aarch64-apple-darwin` | `.dmg`, `.app` |
| Windows | `x86_64-pc-windows-msvc` | `.exe`, `.msi` |
| Linux | `x86_64-unknown-linux-gnu` | `.deb`, `.AppImage`, `.rpm` |

## System tray

When the desktop app is running, a tray icon appears in your OS menubar/taskbar. Right-click (or click on macOS) to:

- Show / hide the main window
- Quick chat (open the chat view)
- Quit Aion

## Troubleshooting

### `error: failed to run custom build command for openssl-sys`
Install OpenSSL dev headers:
- macOS: `brew install openssl@3`
- Linux: `sudo apt install libssl-dev`

### Blank window on Linux
Make sure webkit2gtk-4.1 is installed (not 4.0).

### WebView2 missing on Windows
Download from: https://developer.microsoft.com/microsoft-edge/webview2/

### Can't connect to backend
Verify the API server is running: `curl http://localhost:8000/health/live`
Verify the URL in the desktop app settings.

## Comparison with Hermes desktop

| Feature | Aion Hand | Hermes |
|---|---|---|
| Cross-platform | ✅ macOS, Windows, Linux | ✅ macOS, Windows, Linux |
| Framework | Tauri 2.0 (Rust + WebView) | Tauri (Rust + WebView) |
| Bundle size | ~10-15 MB | ~30-50 MB |
| Native menus | ✅ | ✅ |
| System tray | ✅ | ✅ |
| Native notifications | ✅ | ✅ |
| File dialogs | ✅ | ✅ |
| Auto-update | planned | ✅ |
| Plugin ecosystem | ✅ (via Tauri plugins) | ✅ |

Aion's desktop app matches Hermes on all core native capabilities. The only missing feature is auto-update (planned for v0.5.0).
