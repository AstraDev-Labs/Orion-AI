mod app_update;

use std::sync::Arc;
use std::time::Duration;
use tauri::menu::{CheckMenuItemBuilder, MenuBuilder, MenuItemBuilder};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_autostart::MacosLauncher;
use tokio::sync::Mutex;

const OLLAMA_PORT: u16 = 11434;
const ORION_PORT: u16 = 8000;

/// Small, fast model pulled at startup so the app opens quickly.
const STARTUP_MODEL: &str = "qwen3.5:4b";

/// Tiny fallback model if even the startup model can't be pulled.
const FALLBACK_MODEL: &str = "qwen3:0.6b";

/// Qwen3.5 model variants, ordered smallest to largest.
/// Each entry is (ollama_tag, approximate_download_size_gb, min_ram_gb).
const QWEN35_MODELS: &[(&str, f64, f64)] = &[
    ("qwen3.5:0.8b", 1.0, 4.0),
    ("qwen3.5:2b", 2.7, 6.0),
    ("qwen3.5:4b", 3.4, 8.0),
    ("qwen3.5:9b", 6.6, 12.0),
    ("qwen3.5:27b", 17.0, 24.0),
    ("qwen3.5:35b", 24.0, 32.0),
    ("qwen3.5:122b", 81.0, 96.0),
];

/// Get total system RAM in GB.
fn total_ram_gb() -> f64 {
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("sysctl").args(["-n", "hw.memsize"]).output() {
            if let Ok(s) = String::from_utf8(output.stdout) {
                if let Ok(bytes) = s.trim().parse::<u64>() {
                    return bytes as f64 / (1024.0 * 1024.0 * 1024.0);
                }
            }
        }
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(contents) = std::fs::read_to_string("/proc/meminfo") {
            for line in contents.lines() {
                if line.starts_with("MemTotal:") {
                    if let Some(kb_str) = line.split_whitespace().nth(1) {
                        if let Ok(kb) = kb_str.parse::<u64>() {
                            return kb as f64 / (1024.0 * 1024.0);
                        }
                    }
                }
            }
        }
    }
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        // wmic returns TotalVisibleMemorySize in KB
        if let Ok(output) = Command::new("wmic")
            .no_window()
            .args(["OS", "get", "TotalVisibleMemorySize", "/value"])
            .output()
        {
            if let Ok(s) = String::from_utf8(output.stdout) {
                for line in s.lines() {
                    if let Some(val) = line.strip_prefix("TotalVisibleMemorySize=") {
                        if let Ok(kb) = val.trim().parse::<u64>() {
                            return kb as f64 / (1024.0 * 1024.0);
                        }
                    }
                }
            }
        }
    }
    8.0
}

/// Return the list of Qwen3.5 models that fit on this machine, smallest first.
fn models_that_fit() -> Vec<&'static str> {
    let ram = total_ram_gb();
    QWEN35_MODELS
        .iter()
        .filter(|(_, _, min_ram)| ram >= *min_ram)
        .map(|(tag, _, _)| *tag)
        .collect()
}

/// Read the user's persisted chat-model preference without changing settings.
fn configured_chat_model() -> Option<String> {
    let path = std::env::var_os("OPENORION_CONFIG")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from(home_dir()).join(".orion/config.toml"));
    let text = std::fs::read_to_string(path).ok()?;
    let config: toml::Value = text.parse().ok()?;
    let model = config.get("intelligence")?.get("default_model")?.as_str()?.trim();
    let lower = model.to_lowercase();
    let family = lower.rsplit('/').next()?.split(':').next()?;
    if model.is_empty() || family.starts_with("moondream") || family.contains("embed") || family.starts_with("bge-") {
        return None;
    }
    Some(model.to_string())
}

/// Pick the installer recommendation when no installed preference is available.
fn preferred_model() -> &'static str {
    let fitting = models_that_fit();
    // Prefer STARTUP_MODEL when it fits (fast, good quality)
    if fitting.contains(&STARTUP_MODEL) {
        return STARTUP_MODEL;
    }
    match fitting.len() {
        0 => FALLBACK_MODEL,
        1 => fitting[0],
        2 => fitting[0],
        n => fitting[n - 3], // third-largest
    }
}

/// Start a console program without a console window of its own.
///
/// Orion.exe is a windowed app, so every console child it started (the API
/// server, Ollama, uv, setup) opened a terminal window next to the app. With
/// this flag they run in a hidden console, which their own children (the
/// WhatsApp bridge, PowerShell calls from tools) share rather than opening more.
trait NoWindow {
    fn no_window(&mut self) -> &mut Self;
}

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

impl NoWindow for std::process::Command {
    fn no_window(&mut self) -> &mut Self {
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            self.creation_flags(CREATE_NO_WINDOW);
        }
        self
    }
}

impl NoWindow for tokio::process::Command {
    fn no_window(&mut self) -> &mut Self {
        #[cfg(target_os = "windows")]
        self.creation_flags(CREATE_NO_WINDOW);
        self
    }
}

/// Get the user home directory, handling both Unix (HOME) and Windows (USERPROFILE).
fn home_dir() -> String {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default()
}

/// Where setup puts Orion's runtime\, tools\, models\ and install.json.
///
/// An installed app keeps them in its own folder, which the user picked in
/// the installer (so a D: drive install keeps the multi-GB downloads off C:).
/// Otherwise %LOCALAPPDATA%\Orion on Windows and ~/.orion-app elsewhere.
fn install_root() -> std::path::PathBuf {
    if let Some(exe_dir) = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())) {
        if exe_dir.join("setup").join("orion-setup.ps1").exists() {
            return exe_dir;
        }
    }
    #[cfg(target_os = "windows")]
    {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            if !local.is_empty() {
                return std::path::PathBuf::from(local).join("Orion");
            }
        }
    }
    std::path::PathBuf::from(home_dir()).join(".orion-app")
}

/// install.json written by installer/windows/orion-setup.ps1, if setup ran.
fn installed_info() -> Option<serde_json::Value> {
    let raw = std::fs::read_to_string(install_root().join("install.json")).ok()?;
    // Windows PowerShell 5.1 writes UTF-8 with a byte-order mark.
    serde_json::from_str(raw.trim_start_matches('\u{feff}')).ok()
}

/// The model setup chose for this machine's memory.
fn installed_model() -> Option<String> {
    installed_info()?
        .get("model")?
        .as_str()
        .map(|m| m.trim().to_string())
        .filter(|m| !m.is_empty())
}

/// A folder recorded in install.json (e.g. "hf_home"), if it is set.
fn installed_dir(key: &str) -> Option<std::path::PathBuf> {
    installed_info()?
        .get(key)?
        .as_str()
        .map(|p| p.trim().to_string())
        .filter(|p| !p.is_empty())
        .map(std::path::PathBuf::from)
}

/// The runtime's own `orion` executable, when a virtual environment exists.
fn venv_orion(root: &std::path::Path) -> Option<std::path::PathBuf> {
    let candidates = [
        root.join(".venv").join("Scripts").join("orion.exe"),
        root.join(".venv").join("bin").join("orion"),
    ];
    candidates.into_iter().find(|p| p.exists())
}

/// Setup script and backend payload shipped next to the installed app.
fn bundled_setup() -> Option<(std::path::PathBuf, std::path::PathBuf)> {
    let exe_dir = std::env::current_exe().ok()?.parent()?.to_path_buf();
    let script = exe_dir.join("setup").join("orion-setup.ps1");
    let payload = exe_dir.join("backend");
    if script.exists() && payload.join("pyproject.toml").exists() {
        Some((script, payload))
    } else {
        None
    }
}

/// Resolve full path to a binary by checking common locations.
/// macOS .app bundles don't inherit the shell PATH, so we probe manually.
fn resolve_bin(name: &str) -> String {
    let home = home_dir();

    #[cfg(not(target_os = "windows"))]
    let candidates = vec![
        format!("/opt/homebrew/bin/{name}"),
        format!("{home}/.local/bin/{name}"),
        format!("{home}/.cargo/bin/{name}"),
        format!("/usr/local/bin/{name}"),
        format!("/usr/bin/{name}"),
    ];

    #[cfg(target_os = "windows")]
    let candidates = {
        let localappdata = std::env::var("LOCALAPPDATA").unwrap_or_default();
        let programfiles = std::env::var("ProgramFiles").unwrap_or_default();
        let programfiles_x86 = std::env::var("ProgramFiles(x86)").unwrap_or_default();
        vec![
            // Git for Windows — standard install paths
            format!("{programfiles}\\Git\\cmd\\{name}.exe"),
            format!("{programfiles_x86}\\Git\\cmd\\{name}.exe"),
            format!("{localappdata}\\Programs\\Git\\cmd\\{name}.exe"),
            // Scoop package manager
            format!("{home}\\scoop\\shims\\{name}.exe"),
            // Cargo, local bin
            format!("{home}\\.cargo\\bin\\{name}.exe"),
            format!("{home}\\.local\\bin\\{name}.exe"),
            // Generic program locations
            format!("{localappdata}\\Programs\\{name}\\{name}.exe"),
            format!("{programfiles}\\{name}\\{name}.exe"),
            // Ollama installs to LOCALAPPDATA on Windows
            format!("{localappdata}\\Programs\\Ollama\\{name}.exe"),
            // uv installs via pip/pipx
            format!("{home}\\AppData\\Roaming\\Python\\Scripts\\{name}.exe"),
        ]
    };

    for path in &candidates {
        if std::path::Path::new(path).exists() {
            return path.clone();
        }
    }

    // Fallback: ask the OS to find it on PATH.
    // On Windows this uses `where.exe`, on Unix `which`.
    #[cfg(target_os = "windows")]
    {
        if let Ok(output) = std::process::Command::new("where")
            .no_window()
            .arg(format!("{name}.exe"))
            .output()
        {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = stdout.lines().next() {
                    let p = first_line.trim();
                    if !p.is_empty() && std::path::Path::new(p).exists() {
                        return p.to_string();
                    }
                }
            }
        }
    }
    #[cfg(not(target_os = "windows"))]
    {
        if let Ok(output) = std::process::Command::new("which").arg(name).output() {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Some(first_line) = stdout.lines().next() {
                    let p = first_line.trim();
                    if !p.is_empty() && std::path::Path::new(p).exists() {
                        return p.to_string();
                    }
                }
            }
        }
    }

    name.to_string()
}

/// Find the Orion project root (contains pyproject.toml).
/// Checks OPENORION_ROOT env var, walks up from the executable, then
/// probes common clone locations.
fn find_project_root() -> Option<std::path::PathBuf> {
    // 0. The runtime installed by Orion's setup.
    let installed = install_root().join("runtime");
    if installed.join("pyproject.toml").exists() && venv_orion(&installed).is_some() {
        return Some(installed);
    }

    // 1. Explicit env var override
    if let Ok(root) = std::env::var("OPENORION_ROOT") {
        let path = std::path::PathBuf::from(&root);
        if path.join("pyproject.toml").exists() {
            return Some(path);
        }
    }

    // 2. Walk up from the running executable (works in dev and .app bundle)
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().map(|p| p.to_path_buf());
        for _ in 0..8 {
            if let Some(ref d) = dir {
                if d.join("pyproject.toml").exists() {
                    return Some(d.clone());
                }
                dir = d.parent().map(|p| p.to_path_buf());
            }
        }
    }

    // 3. Fallback: well-known direct paths
    let home = home_dir();
    let direct = [
        format!("{home}/Orion"),
        format!("{home}/projects/hazy/Orion"),
        format!("{home}/projects/Orion"),
        format!("{home}/src/Orion"),
        format!("{home}/Documents/Orion"),
        format!("{home}/Desktop/Orion"),
        format!("{home}/Developer/Orion"),
        format!("{home}/dev/Orion"),
        format!("{home}/Code/Orion"),
        format!("{home}/code/Orion"),
        format!("{home}/repos/Orion"),
        format!("{home}/github/Orion"),
    ];
    for p in &direct {
        let path = std::path::PathBuf::from(p);
        if path.join("pyproject.toml").exists() {
            return Some(path);
        }
    }

    // 4. Shallow scan: look for Orion one level inside common parent dirs.
    //    This catches clones like ~/Documents/my-stuff/Orion without
    //    needing to enumerate every possible intermediate folder.
    let scan_parents = [
        format!("{home}/Documents"),
        format!("{home}/Desktop"),
        format!("{home}/Developer"),
        format!("{home}/projects"),
        format!("{home}/repos"),
        format!("{home}/src"),
        format!("{home}/Code"),
        format!("{home}/code"),
        format!("{home}/dev"),
        format!("{home}/github"),
    ];
    for parent in &scan_parents {
        let parent_path = std::path::PathBuf::from(parent);
        if let Ok(entries) = std::fs::read_dir(&parent_path) {
            for entry in entries.flatten() {
                let candidate = entry.path().join("Orion");
                if candidate.join("pyproject.toml").exists() {
                    return Some(candidate);
                }
                // Also check if the entry itself is Orion (case-insensitive match)
                if let Some(name) = entry.file_name().to_str() {
                    if name.eq_ignore_ascii_case("orion")
                        && entry.path().join("pyproject.toml").exists()
                    {
                        return Some(entry.path());
                    }
                }
            }
        }
    }

    None
}

// ---------------------------------------------------------------------------
// BackendManager — owns the Ollama + Orion server child processes
// ---------------------------------------------------------------------------

struct ChildHandle {
    child: tokio::process::Child,
}

impl ChildHandle {
    async fn kill(&mut self) {
        // The API server is a launcher (orion.exe) running python.exe, which
        // runs another python.exe: killing only the top process left the
        // server holding port 8000 after Orion quit. Take the whole tree.
        #[cfg(target_os = "windows")]
        if let Some(pid) = self.child.id() {
            let _ = std::process::Command::new("taskkill")
                .no_window()
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .status();
        }
        let _ = self.child.kill().await;
    }
}

#[derive(Default)]
struct BackendManager {
    ollama: Option<ChildHandle>,
    orion: Option<ChildHandle>,
}

impl BackendManager {
    async fn stop_all(&mut self) {
        if let Some(ref mut h) = self.orion {
            h.kill().await;
        }
        self.orion = None;
        if let Some(ref mut h) = self.ollama {
            h.kill().await;
        }
        self.ollama = None;
    }
}

type SharedBackend = Arc<Mutex<BackendManager>>;

// ---------------------------------------------------------------------------
// Setup status (reported to frontend)
// ---------------------------------------------------------------------------

#[derive(serde::Serialize, Clone)]
struct SetupStatus {
    phase: String,
    detail: String,
    ollama_ready: bool,
    server_ready: bool,
    model_ready: bool,
    error: Option<String>,
}

impl Default for SetupStatus {
    fn default() -> Self {
        Self {
            phase: "starting".into(),
            detail: "Initializing...".into(),
            ollama_ready: false,
            server_ready: false,
            model_ready: false,
            error: None,
        }
    }
}

type SharedStatus = Arc<Mutex<SetupStatus>>;

/// Latest clipboard text ORION has seen — shared between the background
/// watcher loop and the clipboard-panel window's commands.
type SharedClipboard = Arc<Mutex<String>>;

// ---------------------------------------------------------------------------
// Health-check helpers
// ---------------------------------------------------------------------------

async fn wait_for_url(url: &str, timeout: Duration) -> bool {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();
    let deadline = tokio::time::Instant::now() + timeout;
    while tokio::time::Instant::now() < deadline {
        if let Ok(resp) = client.get(url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    false
}

async fn ollama_has_model(model: &str) -> bool {
    let url = format!("http://127.0.0.1:{}/api/tags", OLLAMA_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .unwrap();
    if let Ok(resp) = client.get(&url).send().await {
        if let Ok(body) = resp.json::<serde_json::Value>().await {
            if let Some(models) = body.get("models").and_then(|m| m.as_array()) {
                return models.iter().any(|m| {
                    m.get("name")
                        .and_then(|n| n.as_str())
                        .map(|n| {
                            n == model
                                || n.strip_suffix(":latest") == Some(model)
                                || model.strip_suffix(":latest") == Some(n)
                        })
                        .unwrap_or(false)
                });
            }
        }
    }
    false
}

async fn pull_model(model: &str) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{}/api/pull", OLLAMA_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(600))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .post(&url)
        .json(&serde_json::json!({"name": model, "stream": false}))
        .send()
        .await
        .map_err(|e| format!("Pull request failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("Pull returned status {}", resp.status()));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Backend boot sequence (runs in background after app launch)
// ---------------------------------------------------------------------------

/// Spawn the Python API server. Shared by first boot and by the supervisor,
/// so a restarted backend is launched exactly the same way as the original.
fn spawn_orion_server(
    uv_bin: &str,
    root: &std::path::Path,
    startup_model: &str,
) -> std::io::Result<tokio::process::Child> {
    let serve_args = [
        "serve".to_string(),
        // This computer only, whatever the config file says: older generated
        // configs set host = "0.0.0.0", which exposed Orion to the network.
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        ORION_PORT.to_string(),
        "--model".to_string(),
        startup_model.to_string(),
        "--agent".to_string(),
        "orchestrator".to_string(),
    ];
    // Run the environment's own executable when there is one. `uv run` syncs
    // first, and a sync removes the compiled orion_rust extension (it is
    // installed from a wheel, not declared in the lock), breaking the backend.
    let mut cmd = match venv_orion(root) {
        Some(exe) => {
            let mut c = tokio::process::Command::new(exe);
            c.args(&serve_args);
            c
        }
        None => {
            let mut c = tokio::process::Command::new(uv_bin);
            c.args(["run", "--no-sync", "orion"]).args(&serve_args);
            c
        }
    };
    cmd.no_window()
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        .current_dir(root);

    // A private Node.js from setup (used by the WhatsApp bridge) goes first on PATH.
    let node_dir = install_root().join("tools").join("node");
    if node_dir.join(if cfg!(windows) { "node.exe" } else { "node" }).exists() {
        let current = std::env::var("PATH").unwrap_or_default();
        let sep = if cfg!(windows) { ";" } else { ":" };
        cmd.env("PATH", format!("{}{}{}", node_dir.display(), sep, current));
    }
    // Voice models (speech recognition, Kokoro) downloaded into the install folder.
    if let Some(hf_home) = installed_dir("hf_home") {
        cmd.env("HF_HOME", hf_home);
    }

    // Inject cloud API keys from ~/.orion/cloud-keys.env
    for (key, value) in read_cloud_keys() {
        cmd.env(&key, &value);
    }
    cmd.spawn()
}

/// Restart the API server if its process exits unexpectedly.
///
/// `boot_backend` only ran once, at startup, so a backend that died left the
/// app sitting on a permanently unresponsive window until it was relaunched
/// by hand. Only an actual process exit triggers a restart -- polling /health
/// would misread a long local-model inference as a crash. Restarts are capped
/// so a backend that cannot start (a bad config, say) surfaces an error
/// instead of respawning forever.
async fn supervise_backend(
    backend: SharedBackend,
    status: SharedStatus,
    uv_bin: String,
    root: std::path::PathBuf,
    startup_model: String,
) {
    const MAX_RESTARTS: u32 = 5;
    const POLL: Duration = Duration::from_secs(5);
    let mut restarts: u32 = 0;

    loop {
        tokio::time::sleep(POLL).await;

        let exited = {
            let mut mgr = backend.lock().await;
            match mgr.orion {
                // `None` means shutdown deliberately cleared it -- stop watching.
                None => return,
                Some(ref mut h) => match h.child.try_wait() {
                    Ok(Some(_status)) => true,
                    Ok(None) => false,
                    Err(_) => false,
                },
            }
        };

        if !exited {
            continue;
        }

        if restarts >= MAX_RESTARTS {
            let mut s = status.lock().await;
            s.server_ready = false;
            s.error = Some(format!(
                "The Orion backend stopped {} times and could not be restarted. \
                 Check ~/.orion/config.toml, then restart the app.",
                restarts
            ));
            return;
        }

        restarts += 1;
        {
            let mut s = status.lock().await;
            s.server_ready = false;
            s.phase = "restarting".into();
            s.detail = format!("Backend stopped unexpectedly — restarting ({}/{})...", restarts, MAX_RESTARTS);
        }

        match spawn_orion_server(&uv_bin, &root, &startup_model) {
            Ok(child) => {
                backend.lock().await.orion = Some(ChildHandle { child });
            }
            Err(e) => {
                let mut s = status.lock().await;
                s.error = Some(format!("Could not restart the Orion backend: {}", e));
                return;
            }
        }

        let server_url = format!("http://127.0.0.1:{}/health", ORION_PORT);
        if wait_for_url(&server_url, Duration::from_secs(300)).await {
            let mut s = status.lock().await;
            s.server_ready = true;
            s.phase = "ready".into();
            s.detail = "All systems ready.".into();
            s.error = None;
        }
    }
}

async fn boot_backend(backend: SharedBackend, status: SharedStatus) {
    // Phase 1: Start Ollama
    {
        let mut s = status.lock().await;
        s.phase = "ollama".into();
        s.detail = "Starting inference engine...".into();
    }

    // Setup has not finished (it was cancelled, failed, or the installer ran
    // silently offline): finish it before anything else, since it installs
    // Ollama itself. install.json is only written once setup succeeds.
    if installed_info().is_none() {
        if let Some((script, payload)) = bundled_setup() {
            run_bundled_setup(&script, &payload, &status).await;
            if installed_info().is_none() {
                return; // run_bundled_setup reported the error
            }
        }
    }

    // The Ollama setup installed or found, else the one on this system.
    let ollama_child = {
        let ollama_bin = installed_dir("ollama")
            .filter(|p| p.exists())
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| resolve_bin("ollama"));
        let mut sidecar_cmd = tokio::process::Command::new(&ollama_bin);
        sidecar_cmd.no_window().arg("serve");
        // Models live where setup put them (the install folder on a new install).
        // Passed explicitly: this process's environment predates setup setting it.
        if let Some(models) = installed_dir("ollama_models") {
            sidecar_cmd.env("OLLAMA_MODELS", models);
        }
        let sidecar = sidecar_cmd
            .env("OLLAMA_HOST", format!("127.0.0.1:{}", OLLAMA_PORT))
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn();
        match sidecar {
            Ok(child) => Some(child),
            Err(_) => None,
        }
    };

    if let Some(child) = ollama_child {
        backend.lock().await.ollama = Some(ChildHandle { child });
    }

    let ollama_url = format!("http://127.0.0.1:{}/api/tags", OLLAMA_PORT);
    let ollama_ok = wait_for_url(&ollama_url, Duration::from_secs(30)).await;

    if !ollama_ok {
        let mut s = status.lock().await;
        s.error = Some("Could not start Ollama. Install it from https://ollama.com".into());
        return;
    }

    {
        let mut s = status.lock().await;
        s.ollama_ready = true;
        s.detail = "Inference engine ready.".into();
    }

    // Phase 2: make sure the model this machine uses is present. Setup picked
    // it from this PC's memory (install.json); without setup, pick the same way.
    let mut wanted_model: String = installed_model().unwrap_or_else(|| preferred_model().to_string());
    // A user's installed chat-model choice takes priority over the setup-time
    // hardware recommendation. Never download a stale saved preference here.
    if let Some(saved) = configured_chat_model() {
        if ollama_has_model(&saved).await {
            wanted_model = saved;
        }
    }
    {
        let mut s = status.lock().await;
        s.phase = "model".into();
        s.detail = format!("Checking for {}...", wanted_model);
    }

    if !ollama_has_model(&wanted_model).await {
        {
            let mut s = status.lock().await;
            s.detail = format!("Downloading {}... (this may take a while)", wanted_model);
        }
        if let Err(e) = pull_model(&wanted_model).await {
            // If the startup model fails, try the tiny fallback
            eprintln!("Warning: failed to pull {}: {}", wanted_model, e);
            if !ollama_has_model(FALLBACK_MODEL).await {
                let mut s = status.lock().await;
                s.detail = format!("Downloading {}...", FALLBACK_MODEL);
                drop(s);
                if let Err(e2) = pull_model(FALLBACK_MODEL).await {
                    let mut s = status.lock().await;
                    s.error = Some(format!("Failed to download model: {}", e2));
                    return;
                }
            }
        }
    }

    {
        let mut s = status.lock().await;
        s.model_ready = true;
        s.detail = "Model ready.".into();
    }

    // Phase 3: Start orion serve
    {
        let mut s = status.lock().await;
        s.phase = "server".into();
        s.detail = "Starting API server...".into();
    }

    let uv_bin = resolve_bin("uv");
    let mut project_root = find_project_root();

    // No runtime yet (setup was skipped, cancelled or failed): run the bundled
    // setup again, showing its progress on the loading screen.
    if project_root.is_none() {
        if let Some((script, payload)) = bundled_setup() {
            run_bundled_setup(&script, &payload, &status).await;
            project_root = find_project_root();
            if project_root.is_none() {
                return; // run_bundled_setup reported the error
            }
        }
    }

    // Verify uv is actually installed (only needed for a developer checkout)
    let has_runtime = project_root.as_ref().map(|r| venv_orion(r).is_some()).unwrap_or(false);
    if !has_runtime && !std::path::Path::new(&uv_bin).exists() && uv_bin == "uv" {
        let mut s = status.lock().await;
        s.error = Some(
            "Could not find 'uv' (Python package manager). \
             Install it from https://astral.sh/uv then relaunch."
                .into(),
        );
        return;
    }

    if project_root.is_none() {
        // Auto-clone on first launch
        let git_bin = resolve_bin("git");

        // Check that git is installed
        if !std::path::Path::new(&git_bin).exists() && git_bin == "git" {
            let mut s = status.lock().await;
            s.error = Some(
                "Could not find 'git'. \
                 Install it from https://git-scm.com then relaunch."
                    .into(),
            );
            return;
        }

        let target_path = std::path::PathBuf::from(home_dir()).join("Orion");
        let clone_target = target_path.display().to_string();

        // If the directory exists but is not a valid project, don't overwrite
        if target_path.exists() && !target_path.join("pyproject.toml").exists() {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "{} exists but is not a valid Orion project. \
                 Remove it and relaunch, or set OPENORION_ROOT to the correct path.",
                clone_target,
            ));
            return;
        }

        {
            let mut s = status.lock().await;
            s.detail = "Downloading Orion (first launch)...".into();
        }

        let clone_result = tokio::process::Command::new(&git_bin)
            .no_window()
            .args([
                "clone",
                "--depth",
                "1",
                "https://github.com/AstraDev-Labs/Orion-AI.git",
                &clone_target,
            ])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::piped())
            .spawn();

        match clone_result {
            Ok(child) => match child.wait_with_output().await {
                Ok(output) if output.status.success() => {
                    project_root = Some(target_path);
                }
                Ok(output) => {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    let mut s = status.lock().await;
                    s.error = Some(format!(
                        "Failed to download Orion: {}. \
                         Clone manually: git clone https://github.com/AstraDev-Labs/Orion-AI.git {}",
                        stderr.trim(),
                        clone_target,
                    ));
                    return;
                }
                Err(e) => {
                    let mut s = status.lock().await;
                    s.error = Some(format!(
                        "Failed to download Orion: {}. \
                         Clone manually: git clone https://github.com/AstraDev-Labs/Orion-AI.git {}",
                        e, clone_target,
                    ));
                    return;
                }
            },
            Err(e) => {
                let mut s = status.lock().await;
                s.error = Some(format!(
                    "Could not run git: {}. \
                     Install git from https://git-scm.com then relaunch.",
                    e,
                ));
                return;
            }
        }
    }

    // Kill any leftover server on our port from a previous run
    {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        if client
            .get(format!("http://127.0.0.1:{}/health", ORION_PORT))
            .send()
            .await
            .is_ok()
        {
            // Something is already listening — try to kill it
            #[cfg(unix)]
            {
                let _ = tokio::process::Command::new("fuser")
                    .args(["-k", &format!("{}/tcp", ORION_PORT)])
                    .output()
                    .await;
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
            #[cfg(target_os = "windows")]
            {
                // Find the PID holding the port via netstat, then kill it
                if let Ok(output) = tokio::process::Command::new("cmd")
                    .no_window()
                    .args(["/C", &format!(
                        "for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :{port} ^| findstr LISTENING') do taskkill /PID %a /F",
                        port = ORION_PORT,
                    )])
                    .output()
                    .await
                {
                    let _ = output; // best-effort
                }
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
        }
    }

    let startup_model: String = if ollama_has_model(&wanted_model).await {
        wanted_model.clone()
    } else {
        FALLBACK_MODEL.to_string()
    };

    let root = project_root.as_ref().unwrap();

    // A developer checkout without an environment yet: create one. --inexact
    // keeps packages installed outside the lock (the orion_rust extension),
    // which a plain `uv sync` would delete.
    if venv_orion(root).is_none() {
        {
            let mut s = status.lock().await;
            s.detail = "Installing dependencies...".into();
        }
        let _ = tokio::process::Command::new(&uv_bin)
            .no_window()
            .args(["sync", "--inexact", "--extra", "server", "--extra", "speech", "--extra", "speech-kokoro"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .current_dir(root)
            .status()
            .await;
    }

    {
        let mut s = status.lock().await;
        s.detail = format!(
            "Starting server with {} from {}...",
            startup_model,
            root.display(),
        );
    }

    let orion_child = spawn_orion_server(&uv_bin, root, &startup_model);

    match orion_child {
        Ok(child) => {
            backend.lock().await.orion = Some(ChildHandle { child });
        }
        Err(e) => {
            let mut s = status.lock().await;
            s.error = Some(format!(
                "Could not start orion server: {}. \
                 Make sure uv is installed (https://astral.sh/uv) and the Orion repo is cloned at {}",
                e,
                root.display(),
            ));
            return;
        }
    }

    let server_url = format!("http://127.0.0.1:{}/health", ORION_PORT);
    let server_ok = wait_for_url(&server_url, Duration::from_secs(600)).await;

    if !server_ok {
        // Try to read stderr from the failed process for a useful error
        let mut stderr_msg = String::new();
        {
            let mut mgr = backend.lock().await;
            if let Some(ref mut h) = mgr.orion {
                if let Some(ref mut stderr) = h.child.stderr.take() {
                    use tokio::io::AsyncReadExt;
                    let mut buf = vec![0u8; 4096];
                    if let Ok(n) = stderr.read(&mut buf).await {
                        stderr_msg = String::from_utf8_lossy(&buf[..n]).to_string();
                    }
                }
            }
        }
        let detail = if stderr_msg.is_empty() {
            format!(
                "Orion server did not start. Check that:\n\
                 1. uv is installed ({})\n\
                 2. The Orion repo is at {}\n\
                 3. Run 'uv sync' in that directory",
                uv_bin,
                root.display(),
            )
        } else {
            format!("Server failed to start: {}", stderr_msg.trim())
        };
        let mut s = status.lock().await;
        s.error = Some(detail);
        return;
    }

    {
        let mut s = status.lock().await;
        s.server_ready = true;
        s.phase = "ready".into();
        s.detail = "All systems ready.".into();
    }

    // Keep the backend alive for the rest of the session.
    {
        let sup_backend = Arc::clone(&backend);
        let sup_status = Arc::clone(&status);
        let sup_uv = uv_bin.clone();
        let sup_root = root.to_path_buf();
        let sup_model = startup_model.to_string();
        tokio::spawn(async move {
            supervise_backend(sup_backend, sup_status, sup_uv, sup_root, sup_model).await;
        });
    }

    // No background downloads of other model sizes: that silently fetched
    // every model that fits in memory (tens of GB on a large machine). Extra
    // models are pulled only when the user asks for one.
}

/// Run the bundled setup script and mirror its progress into the boot status.
#[cfg(target_os = "windows")]
async fn run_bundled_setup(script: &std::path::Path, payload: &std::path::Path, status: &SharedStatus) {
    let status_file = install_root().join("setup-status.json");
    let _ = std::fs::create_dir_all(install_root());
    let _ = std::fs::remove_file(&status_file);
    {
        let mut s = status.lock().await;
        s.phase = "setup".into();
        s.detail = "Finishing Orion setup...".into();
        s.error = None;
    }
    let child = tokio::process::Command::new("powershell.exe")
        .no_window()
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File"])
        .arg(script)
        .arg("-PayloadDir")
        .arg(payload)
        .arg("-InstallRoot")
        .arg(install_root())
        .arg("-StatusFile")
        .arg(&status_file)
        .arg("-NoPause")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
    let mut child = match child {
        Ok(c) => c,
        Err(e) => {
            let mut s = status.lock().await;
            s.error = Some(format!("Could not run Orion setup: {}", e));
            return;
        }
    };
    loop {
        if let Ok(Some(_)) = child.try_wait() {
            break;
        }
        if let Ok(raw) = std::fs::read_to_string(&status_file) {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(raw.trim_start_matches('\u{feff}')) {
                let label = v.get("label").and_then(|x| x.as_str()).unwrap_or("");
                let detail = v.get("detail").and_then(|x| x.as_str()).unwrap_or("");
                let mut s = status.lock().await;
                s.detail = if detail.is_empty() { format!("Setup: {}", label) } else { format!("Setup: {} ({})", label, detail) };
            }
        }
        tokio::time::sleep(Duration::from_millis(700)).await;
    }
    if let Ok(raw) = std::fs::read_to_string(&status_file) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(raw.trim_start_matches('\u{feff}')) {
            if let Some(err) = v.get("error").and_then(|x| x.as_str()).filter(|e| !e.is_empty()) {
                let mut s = status.lock().await;
                s.error = Some(format!(
                    "Setup could not finish: {} (log: {})",
                    err,
                    install_root().join("setup.log").display()
                ));
            }
        }
    }
}

#[cfg(not(target_os = "windows"))]
async fn run_bundled_setup(_script: &std::path::Path, _payload: &std::path::Path, _status: &SharedStatus) {}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

fn api_base() -> String {
    format!("http://127.0.0.1:{}", ORION_PORT)
}

#[tauri::command]
async fn get_setup_status(state: tauri::State<'_, SharedStatus>) -> Result<SetupStatus, String> {
    Ok(state.lock().await.clone())
}

#[tauri::command]
fn get_api_base() -> String {
    api_base()
}

// ---------------------------------------------------------------------------
// Clipboard Intelligence — watches the clipboard and pops a small floating
// panel (Translate / Summarize / Explain / Fix) near the cursor whenever new
// text is copied.
// ---------------------------------------------------------------------------

const CLIPBOARD_PANEL_LABEL: &str = "clipboard-panel";
/// Setting for popping the clipboard panel up on every copy. Off by default:
/// a window appearing over whatever you were doing each time you copied text
/// got in the way. Switch it on from the tray menu.
const CLIPBOARD_PANEL_SETTING: &str = "clipboard_panel_on_copy";
const CLIPBOARD_MIN_LEN: usize = 3;
const CLIPBOARD_MAX_LEN: usize = 20_000;

#[tauri::command]
async fn get_pending_clipboard_text(state: tauri::State<'_, SharedClipboard>) -> Result<String, String> {
    Ok(state.lock().await.clone())
}

/// Called by the panel after it writes a result back to the clipboard, so the
/// watcher doesn't immediately re-trigger on the text ORION itself just wrote.
#[tauri::command]
async fn mark_clipboard_seen(text: String, state: tauri::State<'_, SharedClipboard>) -> Result<(), String> {
    *state.lock().await = text;
    Ok(())
}

#[tauri::command]
async fn close_clipboard_panel(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window(CLIPBOARD_PANEL_LABEL) {
        let _ = win.close();
    }
    Ok(())
}

fn show_clipboard_panel(app: &tauri::AppHandle) {
    // Replace any panel that's already open rather than stacking windows.
    if let Some(win) = app.get_webview_window(CLIPBOARD_PANEL_LABEL) {
        let _ = win.close();
    }

    let (x, y) = app
        .get_webview_window("main")
        .and_then(|w| w.cursor_position().ok())
        .map(|p| (p.x, p.y))
        .unwrap_or((200.0, 200.0));

    let builder = WebviewWindowBuilder::new(
        app,
        CLIPBOARD_PANEL_LABEL,
        WebviewUrl::App("index.html?panel=clipboard".into()),
    )
    .title("Orion")
    .inner_size(340.0, 300.0)
    .position(x, y)
    .decorations(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .resizable(false)
    .shadow(true)
    .visible(true)
    .focused(true);

    if let Err(e) = builder.build() {
        eprintln!("Failed to create clipboard panel: {e}");
    }
}

/// Poll the system clipboard for new text and pop the panel when it changes.
/// Clipboard reads can transiently fail (e.g. another app holding the
/// clipboard open) — those are ignored and retried on the next tick.
async fn run_clipboard_watcher(app: tauri::AppHandle, state: SharedClipboard) {
    let mut interval = tokio::time::interval(Duration::from_millis(700));
    loop {
        interval.tick().await;

        let text = match arboard::Clipboard::new().and_then(|mut cb| cb.get_text()) {
            Ok(t) => t,
            Err(_) => continue,
        };
        let trimmed = text.trim();
        if trimmed.len() < CLIPBOARD_MIN_LEN || trimmed.len() > CLIPBOARD_MAX_LEN {
            continue;
        }

        {
            let mut last = state.lock().await;
            if *last == text {
                continue;
            }
            *last = text.clone();
        }

        // Still tracked above while off, so switching it on never pops up
        // for something copied earlier.
        if app_update::bool_setting(CLIPBOARD_PANEL_SETTING, false) {
            show_clipboard_panel(&app);
        }
    }
}

#[tauri::command]
async fn start_backend(
    backend: tauri::State<'_, SharedBackend>,
    status: tauri::State<'_, SharedStatus>,
) -> Result<(), String> {
    let b = backend.inner().clone();
    let s = status.inner().clone();
    tauri::async_runtime::spawn(boot_backend(b, s));
    Ok(())
}

#[tauri::command]
async fn stop_backend(backend: tauri::State<'_, SharedBackend>) -> Result<(), String> {
    backend.lock().await.stop_all().await;
    Ok(())
}

#[tauri::command]
async fn check_health(api_url: String) -> Result<serde_json::Value, String> {
    let url = format!(
        "{}/health",
        if api_url.is_empty() {
            api_base()
        } else {
            api_url
        }
    );
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_energy(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/telemetry/energy", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_telemetry(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/telemetry/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_traces(api_url: String, limit: u32) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/traces?limit={}", base, limit))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_trace(api_url: String, trace_id: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/traces/{}", base, trace_id))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_learning_stats(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/learning/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_learning_policy(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/learning/policy", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_memory_stats(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/memory/stats", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn search_memory(
    api_url: String,
    query: String,
    top_k: u32,
) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let client = reqwest::Client::new();
    let resp = client
        .post(format!("{}/v1/memory/search", base))
        .json(&serde_json::json!({"query": query, "top_k": top_k}))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_agents(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/agents", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn fetch_models(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/models", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

#[tauri::command]
async fn run_orion_command(args: Vec<String>) -> Result<String, String> {
    let mut cmd_args = vec!["run".to_string(), "orion".to_string()];
    cmd_args.extend(args);
    let uv_bin = resolve_bin("uv");
    let output = tokio::process::Command::new(&uv_bin)
        .no_window()
        .args(&cmd_args)
        .output()
        .await
        .map_err(|e| format!("Failed to launch orion: {}", e))?;

    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

#[tauri::command]
async fn fetch_savings(api_url: String) -> Result<serde_json::Value, String> {
    let base = if api_url.is_empty() {
        api_base()
    } else {
        api_url
    };
    let resp = reqwest::get(format!("{}/v1/savings", base))
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    resp.json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))
}

/// Transcribe audio via the speech API endpoint.
#[tauri::command]
async fn transcribe_audio(
    api_url: String,
    audio_data: Vec<u8>,
    filename: String,
) -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/speech/transcribe", api_url);
    let client = reqwest::Client::new();

    let part = reqwest::multipart::Part::bytes(audio_data)
        .file_name(filename)
        .mime_str("audio/webm")
        .map_err(|e| format!("Failed to create multipart: {}", e))?;

    let form = reqwest::multipart::Form::new().part("file", part);

    let resp = client
        .post(&url)
        .multipart(form)
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))?;
    Ok(body)
}

/// Submit savings to Supabase leaderboard.
#[tauri::command]
async fn submit_savings(
    supabase_url: String,
    supabase_key: String,
    payload: serde_json::Value,
) -> Result<bool, String> {
    if supabase_url.is_empty() || supabase_key.is_empty() {
        return Ok(false);
    }
    let client = reqwest::Client::new();
    let resp = client
        .post(format!(
            "{}/rest/v1/savings_entries?on_conflict=anon_id",
            supabase_url
        ))
        .header("Content-Type", "application/json")
        .header("apikey", &supabase_key)
        .header("Authorization", format!("Bearer {}", supabase_key))
        .header("Prefer", "resolution=merge-duplicates")
        .json(&payload)
        .send()
        .await
        .map_err(|e| format!("Supabase POST failed: {}", e))?;
    Ok(resp.status().is_success())
}

// ---------------------------------------------------------------------------
// Cloud API key management
// ---------------------------------------------------------------------------

/// Path to the cloud keys file (~/.orion/cloud-keys.env).
fn cloud_keys_path() -> std::path::PathBuf {
    let home = home_dir();
    std::path::PathBuf::from(home)
        .join(".orion")
        .join("cloud-keys.env")
}

/// Read cloud keys from disk and return as key=value pairs.
fn read_cloud_keys() -> Vec<(String, String)> {
    let path = cloud_keys_path();
    let mut keys = Vec::new();
    if let Ok(contents) = std::fs::read_to_string(&path) {
        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if let Some((k, v)) = line.split_once('=') {
                keys.push((k.trim().to_string(), v.trim().to_string()));
            }
        }
    }
    keys
}

/// Save a single cloud API key to the keys file.
#[tauri::command]
async fn save_cloud_key(key_name: String, key_value: String) -> Result<(), String> {
    let path = cloud_keys_path();
    // Ensure directory exists
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    // Read existing keys, update/add the one being saved
    let mut keys: Vec<(String, String)> = read_cloud_keys()
        .into_iter()
        .filter(|(k, _)| k != &key_name)
        .collect();
    if !key_value.is_empty() {
        keys.push((key_name, key_value));
    }

    // Write back
    let content: String = keys
        .iter()
        .map(|(k, v)| format!("{}={}", k, v))
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(&path, content + "\n").map_err(|e| format!("Failed to save key: {}", e))?;

    // Set permissions to owner-only (chmod 600)
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600));
    }

    // Tell the running server to hot-reload its cloud engine so the user
    // doesn't need to restart the app after entering an API key.
    let reload_url = format!("http://127.0.0.1:{}/v1/cloud/reload", ORION_PORT);
    let _ = reqwest::Client::new()
        .post(&reload_url)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await;

    Ok(())
}

/// Get which cloud providers have keys configured (without exposing values).
#[tauri::command]
async fn get_cloud_key_status() -> Result<serde_json::Value, String> {
    let keys = read_cloud_keys();
    let status: Vec<serde_json::Value> = keys
        .iter()
        .map(|(k, v)| serde_json::json!({ "key": k, "set": !v.is_empty() }))
        .collect();
    Ok(serde_json::json!(status))
}

/// Pull a model via Ollama (called from frontend download button).
#[tauri::command]
async fn pull_ollama_model(model_name: String) -> Result<serde_json::Value, String> {
    pull_model(&model_name)
        .await
        .map_err(|e| format!("Failed to pull {}: {}", model_name, e))?;
    Ok(serde_json::json!({"status": "ok", "model": model_name}))
}

/// Delete a model from Ollama.
#[tauri::command]
async fn delete_ollama_model(model_name: String) -> Result<serde_json::Value, String> {
    let url = format!("http://127.0.0.1:{}/api/delete", OLLAMA_PORT);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .delete(&url)
        .json(&serde_json::json!({"name": model_name}))
        .send()
        .await
        .map_err(|e| format!("Delete failed: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("Delete returned status {}", resp.status()));
    }
    Ok(serde_json::json!({"status": "deleted", "model": model_name}))
}

/// Check speech backend health.
#[tauri::command]
async fn speech_health(api_url: String) -> Result<serde_json::Value, String> {
    let url = format!("{}/v1/speech/health", api_url);
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    let body: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Invalid response: {}", e))?;
    Ok(body)
}

// ---------------------------------------------------------------------------
// Native macOS overlay — NSPanel + WKWebView, entirely bypassing Tauri's
// window management so we get proper always-on-top, transparency, non-
// activating panel behaviour and cross-Space support.
// ---------------------------------------------------------------------------

#[cfg(target_os = "macos")]
mod native_overlay {
    use objc::declare::ClassDecl;
    use objc::runtime::{Class, Object, Sel, BOOL, NO, YES};
    use objc::{class, msg_send, sel, sel_impl};
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Raw pointer to the NSPanel, stored as usize for atomicity.
    static PANEL_PTR: AtomicUsize = AtomicUsize::new(0);
    /// Raw pointer to the WKWebView inside the panel.
    static WEBVIEW_PTR: AtomicUsize = AtomicUsize::new(0);
    /// Raw pointer to the previously-frontmost NSRunningApplication.
    static PREV_APP: AtomicUsize = AtomicUsize::new(0);

    // CoreGraphics geometry types expected by AppKit.
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGPoint {
        x: f64,
        y: f64,
    }
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGSize {
        width: f64,
        height: f64,
    }
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct CGRect {
        origin: CGPoint,
        size: CGSize,
    }

    /// Create an autoreleased NSString from a Rust &str.
    unsafe fn nsstring(s: &str) -> *mut Object {
        let obj: *mut Object = msg_send![class!(NSString), alloc];
        msg_send![obj,
            initWithBytes: s.as_ptr()
            length: s.len()
            encoding: 4usize  // NSUTF8StringEncoding
        ]
    }

    // ------------------------------------------------------------------
    // Conversation persistence
    // ------------------------------------------------------------------

    fn conversation_path() -> std::path::PathBuf {
        std::path::PathBuf::from(super::home_dir())
            .join(".orion")
            .join("overlay-conversation.json")
    }

    pub fn load_conversation() -> String {
        std::fs::read_to_string(conversation_path()).unwrap_or_else(|_| "[]".into())
    }

    /// Read cloud API keys and return a JSON array of model IDs
    /// whose provider has a key configured.
    fn cloud_models_json() -> String {
        let keys = super::read_cloud_keys();
        let mut models: Vec<&str> = Vec::new();
        for (name, value) in &keys {
            if value.is_empty() {
                continue;
            }
            match name.as_str() {
                "OPENAI_API_KEY" => models.extend(["gpt-4o", "gpt-4o-mini"]),
                "ANTHROPIC_API_KEY" => {
                    models.extend(["claude-sonnet-4-20250514", "claude-haiku-4-20250414"])
                }
                "GEMINI_API_KEY" | "GOOGLE_API_KEY" => {
                    models.extend(["gemini-2.5-flash", "gemini-2.5-pro"])
                }
                _ => {}
            }
        }
        serde_json::to_string(&models).unwrap_or_else(|_| "[]".into())
    }

    fn save_conversation(json: &str) {
        let path = conversation_path();
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&path, json);
    }

    /// Apply every transparency trick to the WKWebView.
    /// Called once at creation and again after the page finishes loading.
    unsafe fn force_transparent(wv: *mut Object) {
        let clear: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![wv, _setDrawsBackground: NO];
        let no_num: *mut Object = msg_send![class!(NSNumber), numberWithBool: NO];
        let _: () = msg_send![wv, setValue: no_num forKey: nsstring("drawsBackground")];
        let _: () = msg_send![wv, setUnderPageBackgroundColor: clear];
        // Also inject CSS to nuke any remaining background
        let js = nsstring(
            "document.documentElement.style.background='transparent';\
             document.body.style.background='transparent';"
        );
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![wv, evaluateJavaScript: js completionHandler: nil];
    }

    // ------------------------------------------------------------------
    // Public API (must be called on the main thread)
    // ------------------------------------------------------------------

    /// Build the native overlay panel.  Call once during app setup.
    pub unsafe fn create(html: &str, api_port: u16) {
        // --- Custom NSPanel subclass that accepts keyboard input ------
        if Class::get("OrionOverlayPanel").is_none() {
            let sup = Class::get("NSPanel").unwrap();
            let mut decl = ClassDecl::new("OrionOverlayPanel", sup).unwrap();
            extern "C" fn yes(_: &Object, _: Sel) -> BOOL {
                YES
            }
            decl.add_method(
                sel!(canBecomeKeyWindow),
                yes as extern "C" fn(&Object, Sel) -> BOOL,
            );
            decl.register();
        }

        // --- WKNavigationDelegate — re-apply transparency after load --
        if Class::get("OrionOverlayNavDelegate").is_none() {
            let sup = Class::get("NSObject").unwrap();
            let mut decl = ClassDecl::new("OrionOverlayNavDelegate", sup).unwrap();
            extern "C" fn did_finish(_: &Object, _: Sel, wv: *mut Object, _nav: *mut Object) {
                unsafe { force_transparent(wv); }
            }
            decl.add_method(
                sel!(webView:didFinishNavigation:),
                did_finish as extern "C" fn(&Object, Sel, *mut Object, *mut Object),
            );
            decl.register();
        }

        // --- WKScriptMessageHandler so JS can call hide() ------------
        if Class::get("OrionOverlayMsgHandler").is_none() {
            let sup = Class::get("NSObject").unwrap();
            let mut decl = ClassDecl::new("OrionOverlayMsgHandler", sup).unwrap();
            extern "C" fn on_msg(_: &Object, _: Sel, _ctrl: *mut Object, msg: *mut Object) {
                unsafe {
                    let body: *mut Object = msg_send![msg, body];
                    if body.is_null() {
                        return;
                    }
                    let c: *const std::os::raw::c_char = msg_send![body, UTF8String];
                    if c.is_null() {
                        return;
                    }
                    if let Ok(s) = std::ffi::CStr::from_ptr(c).to_str() {
                        if s == "hide" {
                            hide();
                        } else if let Some(json) = s.strip_prefix("save:") {
                            save_conversation(json);
                        } else if let Some(coords) = s.strip_prefix("drag:") {
                            drag(coords);
                        }
                    }
                }
            }
            decl.add_method(
                sel!(userContentController:didReceiveScriptMessage:),
                on_msg as extern "C" fn(&Object, Sel, *mut Object, *mut Object),
            );
            decl.register();
        }

        // --- Create the NSPanel --------------------------------------
        let frame = CGRect {
            origin: CGPoint { x: 0.0, y: 0.0 },
            size: CGSize {
                width: 560.0,
                height: 400.0,
            },
        };
        // NSWindowStyleMaskNonactivatingPanel = 1 << 7
        let style: u64 = 1 << 7;

        let cls = Class::get("OrionOverlayPanel").unwrap();
        let panel: *mut Object = msg_send![cls, alloc];
        let panel: *mut Object = msg_send![panel,
            initWithContentRect: frame
            styleMask: style
            backing: 2u64       // NSBackingStoreBuffered
            defer: NO
        ];

        // Window level — NSFloatingWindowLevel (3).
        let _: () = msg_send![panel, setLevel: 3_i64];
        // canJoinAllSpaces (1) | fullScreenAuxiliary (1<<8)
        let _: () = msg_send![panel, setCollectionBehavior: 257_u64];
        let _: () = msg_send![panel, setHidesOnDeactivate: NO];
        let _: () = msg_send![panel, setOpaque: NO];
        let _: () = msg_send![panel, setHasShadow: NO];
        let _: () = msg_send![panel, setMovableByWindowBackground: YES];

        let clear: *mut Object = msg_send![class!(NSColor), clearColor];
        let _: () = msg_send![panel, setBackgroundColor: clear];
        let _: () = msg_send![panel, center];

        // --- WKWebView -----------------------------------------------
        let cfg: *mut Object = msg_send![class!(WKWebViewConfiguration), alloc];
        let cfg: *mut Object = msg_send![cfg, init];

        // Attach message handler ("overlay" channel)
        let hcls = Class::get("OrionOverlayMsgHandler").unwrap();
        let handler: *mut Object = msg_send![hcls, alloc];
        let handler: *mut Object = msg_send![handler, init];
        let uc: *mut Object = msg_send![cfg, userContentController];
        let _: () = msg_send![uc,
            addScriptMessageHandler: handler
            name: nsstring("overlay")
        ];

        let wv: *mut Object = msg_send![class!(WKWebView), alloc];
        let wv: *mut Object = msg_send![wv,
            initWithFrame: frame
            configuration: cfg
        ];

        // ---- Make the webview fully transparent ----
        force_transparent(wv);

        // Set navigation delegate so we re-apply after page loads
        let nav_cls = Class::get("OrionOverlayNavDelegate").unwrap();
        let nav_del: *mut Object = msg_send![nav_cls, alloc];
        let nav_del: *mut Object = msg_send![nav_del, init];
        let _: () = msg_send![wv, setNavigationDelegate: nav_del];

        let _: () = msg_send![panel, setContentView: wv];
        WEBVIEW_PTR.store(wv as usize, Ordering::SeqCst);

        // Inject saved conversation into the HTML template, then load it.
        // Use the API server as the base URL so fetch() is same-origin.
        // Escape "</" so the JSON can't prematurely close the <script> tag.
        // ("\/" is valid JSON — resolves back to "/" when parsed.)
        let saved = load_conversation().replace("</", "<\\/");
        let cloud = cloud_models_json();
        let filled = html
            .replace("__SAVED_MESSAGES__", &saved)
            .replace("__CLOUD_MODELS__", &cloud);
        let base_str = nsstring(&format!("http://127.0.0.1:{}", api_port));
        let base_url: *mut Object = msg_send![class!(NSURL), URLWithString: base_str];
        let _: () = msg_send![wv,
            loadHTMLString: nsstring(&filled)
            baseURL: base_url
        ];

        PANEL_PTR.store(panel as usize, Ordering::SeqCst);
    }

    pub unsafe fn toggle() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let vis: BOOL = msg_send![panel, isVisible];
        if vis != NO {
            hide();
        } else {
            show();
        }
    }

    pub unsafe fn show() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;

        // Re-apply transparency every time (the webview can reset it)
        let wv_ptr = WEBVIEW_PTR.load(Ordering::SeqCst);
        if wv_ptr != 0 {
            force_transparent(wv_ptr as *mut Object);
        }

        // Remember the currently-frontmost app so we can restore it.
        let ws: *mut Object = msg_send![class!(NSWorkspace), sharedWorkspace];
        let front: *mut Object = msg_send![ws, frontmostApplication];
        if !front.is_null() {
            let _: () = msg_send![front, retain];
            let old = PREV_APP.swap(front as usize, Ordering::SeqCst);
            if old != 0 {
                let _: () = msg_send![(old as *mut Object), release];
            }
        }

        // Activate our process so the panel receives keyboard input.
        let app: *mut Object = msg_send![class!(NSApplication), sharedApplication];
        let _: () = msg_send![app, activateIgnoringOtherApps: YES];
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![panel, makeKeyAndOrderFront: nil];

        // Focus the text field inside the webview.
        let wv: *mut Object = msg_send![panel, contentView];
        let js = nsstring("document.getElementById('input').focus()");
        let _: () = msg_send![wv, evaluateJavaScript: js completionHandler: nil];
    }

    /// Move the panel by a screen-space delta (called from JS drag handler).
    unsafe fn drag(coords: &str) {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let Some((dxs, dys)) = coords.split_once(',') else {
            return;
        };
        let Ok(dx) = dxs.parse::<f64>() else { return };
        let Ok(dy) = dys.parse::<f64>() else { return };
        // NSWindow frame origin is bottom-left; screen Y increases upward,
        // but mouse screenY increases downward, so invert dy.
        let frame: CGRect = msg_send![panel, frame];
        let origin = CGPoint {
            x: frame.origin.x + dx,
            y: frame.origin.y - dy,
        };
        let _: () = msg_send![panel, setFrameOrigin: origin];
    }

    pub unsafe fn hide() {
        let ptr = PANEL_PTR.load(Ordering::SeqCst);
        if ptr == 0 {
            return;
        }
        let panel = ptr as *mut Object;
        let nil: *mut Object = std::ptr::null_mut();
        let _: () = msg_send![panel, orderOut: nil];

        // Give focus back to whatever app was frontmost before.
        let prev = PREV_APP.swap(0, Ordering::SeqCst);
        if prev != 0 {
            let prev_app = prev as *mut Object;
            let _: BOOL = msg_send![prev_app, activateWithOptions: 2_u64];
            let _: () = msg_send![prev_app, release];
        }
    }
}

/// Dispatch a closure onto the main thread via GCD.
#[cfg(target_os = "macos")]
fn on_main_thread(f: impl FnOnce() + Send + 'static) {
    dispatch::Queue::main().exec_async(f);
}

// ---------------------------------------------------------------------------
// Overlay Tauri commands (thin wrappers that dispatch to the main thread)
// ---------------------------------------------------------------------------

#[tauri::command]
async fn get_overlay_conversation() -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        return Ok(native_overlay::load_conversation());
    }
    #[cfg(not(target_os = "macos"))]
    Ok("[]".into())
}

#[tauri::command]
fn app_update_supported() -> bool {
    app_update::is_supported()
}

#[tauri::command]
async fn get_app_update(
    app: tauri::AppHandle,
    state: tauri::State<'_, app_update::SharedUpdate>,
) -> Result<Option<app_update::AppUpdate>, String> {
    Ok(app_update::cached(&app, state.inner()).await)
}

#[tauri::command]
async fn check_app_update(
    app: tauri::AppHandle,
    state: tauri::State<'_, app_update::SharedUpdate>,
) -> Result<Option<app_update::AppUpdate>, String> {
    app_update::check_now(&app, state.inner()).await
}

#[tauri::command]
async fn install_app_update(
    app: tauri::AppHandle,
    state: tauri::State<'_, app_update::SharedUpdate>,
) -> Result<(), String> {
    app_update::install(&app, state.inner()).await
}

#[tauri::command]
async fn toggle_overlay() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    on_main_thread(|| unsafe { native_overlay::toggle() });
    Ok(())
}

#[tauri::command]
async fn hide_overlay() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    on_main_thread(|| unsafe { native_overlay::hide() });
    Ok(())
}

// ---------------------------------------------------------------------------
// Tray
// ---------------------------------------------------------------------------

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// One short line for the tray menu and tooltip.
fn tray_status_text(s: &SetupStatus) -> String {
    if s.error.is_some() {
        return "Needs attention - open Orion".into();
    }
    if s.server_ready {
        return match installed_model() {
            Some(model) => format!("Ready - {}", model),
            None => "Ready".into(),
        };
    }
    match s.phase.as_str() {
        "setup" => "Finishing setup...".into(),
        "model" => "Preparing the AI model...".into(),
        _ => "Starting...".into(),
    }
}

/// Earlier desktop builds registered the web dashboard's offline service
/// worker inside the app's WebView, and it kept serving the previous version's
/// interface after every install or update (the worker only swaps itself out
/// whenever WebView2 next decides to check). Delete its storage once per app
/// version, before the window starts. Saved app data lives elsewhere in the
/// profile and is untouched.
fn clear_stale_service_worker(identifier: &str) {
    #[cfg(target_os = "windows")]
    {
        let Ok(local) = std::env::var("LOCALAPPDATA") else { return };
        let profile = std::path::PathBuf::from(local).join(identifier).join("EBWebView");
        let marker = profile.join(format!("orion-sw-cleared-{}", env!("CARGO_PKG_VERSION")));
        if !profile.exists() || marker.exists() {
            return;
        }
        let worker_dir = profile.join("Default").join("Service Worker");
        // Fails while another Orion window holds the profile open; try again
        // next launch rather than recording it as done.
        if !worker_dir.exists() || std::fs::remove_dir_all(&worker_dir).is_ok() {
            let _ = std::fs::write(&marker, b"");
        }
    }
    #[cfg(not(target_os = "windows"))]
    let _ = identifier;
}

#[cfg(target_os = "windows")]
const AUTOSTART_LABEL: &str = "Start with Windows";
#[cfg(not(target_os = "windows"))]
const AUTOSTART_LABEL: &str = "Start at login";

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let context = tauri::generate_context!();
    clear_stale_service_worker(&context.config().identifier);

    let backend: SharedBackend = Arc::new(Mutex::new(BackendManager::default()));
    let status: SharedStatus = Arc::new(Mutex::new(SetupStatus::default()));
    let clipboard_state: SharedClipboard = Arc::new(Mutex::new(String::new()));

    let boot_backend_ref = backend.clone();
    let boot_status_ref = status.clone();
    let tray_status_ref = status.clone();
    let update_state: app_update::SharedUpdate = Arc::new(Mutex::new(app_update::UpdateState::default()));
    let clipboard_watch_ref = clipboard_state.clone();

    tauri::Builder::default()
        .manage(backend.clone())
        .manage(status.clone())
        .manage(clipboard_state.clone())
        .manage(update_state.clone())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // The window may be hidden in the tray: bring it back.
            show_main_window(app);
        }))
        // Closing the window keeps Orion running in the tray, so WhatsApp
        // auto-replies, reminders and the backend keep working. Quit from the
        // tray menu stops everything.
        .on_window_event(|window, event| {
            if window.label() != "main" {
                return;
            }
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
                static HINT_SHOWN: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
                if !HINT_SHOWN.swap(true, std::sync::atomic::Ordering::SeqCst) {
                    use tauri_plugin_notification::NotificationExt;
                    let _ = window
                        .app_handle()
                        .notification()
                        .builder()
                        .title("Orion is still running")
                        .body("Orion keeps working in the background. Click the tray icon to open it, or right-click it to quit.")
                        .show();
                }
            }
        })
        .setup(move |app| {
            // System tray: click to open, right-click for the menu.
            let open = MenuItemBuilder::with_id("show", "Open Orion").build(app)?;
            let health = MenuItemBuilder::with_id("health", "Starting...")
                .enabled(false)
                .build(app)?;
            let autostart_on = {
                use tauri_plugin_autostart::ManagerExt;
                app.autolaunch().is_enabled().unwrap_or(false)
            };
            let autostart = CheckMenuItemBuilder::with_id("autostart", AUTOSTART_LABEL)
                .checked(autostart_on)
                .build(app)?;
            let quit = MenuItemBuilder::with_id("quit", "Quit Orion").build(app)?;
            let clipboard_toggle = CheckMenuItemBuilder::with_id("clipboard_panel", "Show actions when I copy text")
                .checked(app_update::bool_setting(CLIPBOARD_PANEL_SETTING, false))
                .build(app)?;
            let updates_supported = app_update::is_supported();
            let update_item = MenuItemBuilder::with_id("update", "Check for updates").build(app)?;
            let auto_update = CheckMenuItemBuilder::with_id("auto_update", "Check for updates automatically")
                .checked(app_update::auto_check_enabled())
                .build(app)?;

            let mut menu_builder = MenuBuilder::new(app)
                .item(&open)
                .separator()
                .item(&health)
                .separator();
            if updates_supported {
                menu_builder = menu_builder.item(&update_item).item(&auto_update).separator();
            }
            let menu = menu_builder.item(&clipboard_toggle).item(&autostart).item(&quit).build()?;

            let autostart_item = autostart.clone();
            let auto_update_item = auto_update.clone();
            let clipboard_item = clipboard_toggle.clone();
            let tray_update_item = update_item.clone();
            let tray_update_state = update_state.clone();
            let _tray = TrayIconBuilder::with_id("main")
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Orion - starting")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                })
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "show" => show_main_window(app),
                    "autostart" => {
                        use tauri_plugin_autostart::ManagerExt;
                        let manager = app.autolaunch();
                        let _ = if manager.is_enabled().unwrap_or(false) {
                            manager.disable()
                        } else {
                            manager.enable()
                        };
                        // Show the real state, whether or not the change worked.
                        let _ = autostart_item.set_checked(manager.is_enabled().unwrap_or(false));
                    }
                    "update" => {
                        // Install a known update, or check now and say what was found.
                        let app = app.clone();
                        let state = tray_update_state.clone();
                        let item = tray_update_item.clone();
                        tauri::async_runtime::spawn(async move {
                            use tauri_plugin_notification::NotificationExt;
                            if app_update::cached(&app, &state).await.is_some() {
                                let _ = item.set_text("Updating...");
                                if let Err(e) = app_update::install(&app, &state).await {
                                    let _ = item.set_text("Update now");
                                    let _ = app.notification().builder().title("Orion could not update").body(e).show();
                                }
                                return;
                            }
                            match app_update::check_now(&app, &state).await {
                                Ok(Some(update)) => {
                                    let _ = item.set_text(format!("Update now to Orion {}", update.version));
                                    app_update::announce(&app, &state, &update).await;
                                }
                                Ok(None) => {
                                    let _ = app.notification().builder().title("Orion is up to date")
                                        .body(format!("You have the latest version ({}).", app.package_info().version)).show();
                                }
                                Err(e) => {
                                    let _ = app.notification().builder().title("Could not check for updates").body(e).show();
                                }
                            }
                        });
                    }
                    "clipboard_panel" => {
                        let enabled = !app_update::bool_setting(CLIPBOARD_PANEL_SETTING, false);
                        app_update::set_bool_setting(CLIPBOARD_PANEL_SETTING, enabled);
                        let _ = clipboard_item.set_checked(enabled);
                        if !enabled {
                            if let Some(win) = app.get_webview_window(CLIPBOARD_PANEL_LABEL) {
                                let _ = win.hide();
                            }
                        }
                    }
                    "auto_update" => {
                        let enabled = !app_update::auto_check_enabled();
                        app_update::set_auto_check(enabled);
                        let _ = auto_update_item.set_checked(enabled);
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            // Look for updates in the background (installer builds only).
            if updates_supported {
                let app_handle = app.handle().clone();
                let state = update_state.clone();
                let item = update_item.clone();
                tauri::async_runtime::spawn(async move {
                    tokio::time::sleep(app_update::FIRST_CHECK_DELAY).await;
                    loop {
                        if app_update::auto_check_enabled() {
                            if let Ok(Some(update)) = app_update::check_now(&app_handle, &state).await {
                                let _ = item.set_text(format!("Update now to Orion {}", update.version));
                                app_update::announce(&app_handle, &state, &update).await;
                            }
                        }
                        tokio::time::sleep(app_update::CHECK_INTERVAL).await;
                    }
                });
            }

            // Keep the tray's status line and tooltip current.
            {
                let health_item = health.clone();
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    let mut last = String::new();
                    loop {
                        let text = {
                            let s = tray_status_ref.lock().await;
                            tray_status_text(&s)
                        };
                        if text != last {
                            let _ = health_item.set_text(&text);
                            if let Some(tray) = handle.tray_by_id("main") {
                                let _ = tray.set_tooltip(Some(format!("Orion - {}", text)));
                            }
                            last = text;
                        }
                        tokio::time::sleep(Duration::from_secs(2)).await;
                    }
                });
            }

            // Started at login with --hidden: stay in the tray. Otherwise show
            // the window (it starts hidden so a login start never flashes it).
            if !std::env::args().any(|a| a == "--hidden") {
                show_main_window(app.handle());
            }

            // Create native macOS overlay panel
            #[cfg(target_os = "macos")]
            unsafe {
                native_overlay::create(include_str!("overlay.html"), ORION_PORT);
            }

            // Register Cmd+Shift+Space to toggle the overlay
            {
                use tauri_plugin_global_shortcut::{
                    Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState,
                };
                let sc = Shortcut::new(Some(Modifiers::META | Modifiers::SHIFT), Code::Space);
                if let Err(e) = app.global_shortcut().on_shortcut(sc, |_app, _sc, ev| {
                    if ev.state == ShortcutState::Pressed {
                        #[cfg(target_os = "macos")]
                        unsafe {
                            native_overlay::toggle();
                        }
                    }
                }) {
                    eprintln!("Warning: could not register Cmd+Shift+Space: {e}");
                }
            }

            // Auto-start backend services on launch
            tauri::async_runtime::spawn(boot_backend(boot_backend_ref, boot_status_ref));

            // Clipboard Intelligence — watch for copied text and pop the panel
            tauri::async_runtime::spawn(run_clipboard_watcher(
                app.handle().clone(),
                clipboard_watch_ref,
            ));

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_setup_status,
            get_api_base,
            start_backend,
            stop_backend,
            check_health,
            fetch_energy,
            fetch_telemetry,
            fetch_traces,
            fetch_trace,
            fetch_learning_stats,
            fetch_learning_policy,
            fetch_memory_stats,
            search_memory,
            fetch_agents,
            fetch_models,
            run_orion_command,
            fetch_savings,
            submit_savings,
            transcribe_audio,
            speech_health,
            pull_ollama_model,
            delete_ollama_model,
            save_cloud_key,
            get_cloud_key_status,
            toggle_overlay,
            hide_overlay,
            app_update_supported,
            get_app_update,
            check_app_update,
            install_app_update,
            get_overlay_conversation,
            get_pending_clipboard_text,
            mark_clipboard_seen,
            close_clipboard_panel,
        ])
        .build(context)
        .expect("error while building Orion Desktop")
        .run(move |_app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                // Wait for the servers to stop: spawning this and returning let
                // the process exit first, leaving the backend running.
                let b = backend.clone();
                tauri::async_runtime::block_on(async move {
                    b.lock().await.stop_all().await;
                });
            }
        });
}
