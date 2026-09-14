//! In-app updates for Orion installed with the Windows installer.
//!
//! Tauri's own updater installs Tauri's NSIS/MSI bundles, a different package
//! from the Inno Setup installer (no bundled backend, no setup step, another
//! install location), so it cannot update these installs. Instead:
//!
//! 1. Every few hours (and on demand) read `orion-windows-update.json` from the
//!    latest GitHub release: `{ version, notes, url, signature }`.
//! 2. If it is newer than this build, notify: a system notification, an event
//!    the window turns into an "Update now" prompt, and a tray menu item.
//! 3. On "Update now", download the installer, verify its minisign signature
//!    against the public key built into this app (`plugins.updater.pubkey`,
//!    the same key Tauri's updater uses), run it silently with `/UPDATE=1`,
//!    and quit. The installer keeps the install folder and chosen features,
//!    reruns setup, and starts Orion again (see Orion.iss).
//!
//! A file whose signature does not verify is never run. The check sends no
//! personal data: one GET request for a public file.

use std::sync::Arc;
use std::time::Duration;

use tauri::{AppHandle, Emitter};
use tokio::sync::Mutex;

/// Public update information for this product's releases (not user-specific).
pub const UPDATE_MANIFEST_URL: &str =
    "https://github.com/AstraDev-Labs/Orion-AI/releases/latest/download/orion-windows-update.json";

pub const CHECK_INTERVAL: Duration = Duration::from_secs(6 * 60 * 60);
pub const FIRST_CHECK_DELAY: Duration = Duration::from_secs(90);

#[derive(Clone, Debug, serde::Deserialize)]
pub struct UpdateManifest {
    pub version: String,
    #[serde(default)]
    pub notes: String,
    pub url: String,
    pub signature: String,
}

#[derive(Clone, Debug, serde::Serialize)]
pub struct AppUpdate {
    pub version: String,
    pub current: String,
    pub notes: String,
}

#[derive(Default)]
pub struct UpdateState {
    pub available: Option<UpdateManifest>,
    /// Last version announced, so each version notifies once.
    pub notified: Option<String>,
    pub installing: bool,
}

pub type SharedUpdate = Arc<Mutex<UpdateState>>;

/// In-app updates apply to installs made by the Windows installer.
pub fn is_supported() -> bool {
    cfg!(target_os = "windows") && super::bundled_setup().is_some()
}

/// True when `candidate` is a later version than `current` ("1.0.10" > "1.0.9").
pub fn version_newer(candidate: &str, current: &str) -> bool {
    fn parts(v: &str) -> Vec<u64> {
        v.trim()
            .trim_start_matches('v')
            .split(['-', '+'])
            .next()
            .unwrap_or("")
            .split('.')
            .map(|p| p.trim().parse::<u64>().unwrap_or(0))
            .collect()
    }
    let (mut a, mut b) = (parts(candidate), parts(current));
    let n = a.len().max(b.len());
    a.resize(n, 0);
    b.resize(n, 0);
    a > b
}

/// Verify a minisign signature the way Tauri's updater does: both the key and
/// the signature are base64 of minisign's text format.
pub fn verify_signature(data: &[u8], signature_b64: &str, pubkey_b64: &str) -> Result<(), String> {
    use base64::Engine;
    let decode = |s: &str| -> Result<String, String> {
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(s.trim())
            .map_err(|e| format!("not base64: {e}"))?;
        String::from_utf8(bytes).map_err(|e| format!("not text: {e}"))
    };
    let key = minisign_verify::PublicKey::decode(&decode(pubkey_b64)?)
        .map_err(|e| format!("Orion's update key is invalid: {e}"))?;
    let signature = minisign_verify::Signature::decode(&decode(signature_b64)?)
        .map_err(|e| format!("The update's signature is invalid: {e}"))?;
    key.verify(data, &signature, true)
        .map_err(|_| "The downloaded update is not signed by Orion's release key, so it was not installed.".to_string())
}

fn settings_path() -> std::path::PathBuf {
    super::install_root().join("app-settings.json")
}

fn read_settings() -> serde_json::Map<String, serde_json::Value> {
    std::fs::read_to_string(settings_path())
        .ok()
        .and_then(|raw| serde_json::from_str::<serde_json::Value>(raw.trim_start_matches('\u{feff}')).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

/// Whether Orion checks for updates by itself (tray: "Check for updates automatically").
pub fn auto_check_enabled() -> bool {
    read_settings()
        .get("auto_update_check")
        .and_then(|v| v.as_bool())
        .unwrap_or(true)
}

pub fn set_auto_check(enabled: bool) {
    set_bool_setting("auto_update_check", enabled);
}

/// A true/false app setting from app-settings.json, or `default` if unset.
pub fn bool_setting(key: &str, default: bool) -> bool {
    read_settings().get(key).and_then(|v| v.as_bool()).unwrap_or(default)
}

pub fn set_bool_setting(key: &str, value: bool) {
    let mut settings = read_settings();
    settings.insert(key.into(), serde_json::Value::Bool(value));
    let _ = std::fs::create_dir_all(super::install_root());
    let _ = std::fs::write(settings_path(), serde_json::Value::Object(settings).to_string());
}

fn manifest_url() -> String {
    // For testing an update end to end against a local server. Safe to allow:
    // whatever it points at must still carry a valid signature from Orion's key.
    std::env::var("ORION_UPDATE_MANIFEST_URL")
        .ok()
        .filter(|u| !u.trim().is_empty())
        .unwrap_or_else(|| UPDATE_MANIFEST_URL.to_string())
}

fn allowed_url(url: &str) -> bool {
    url.starts_with("https://") || url.starts_with("http://127.0.0.1:") || url.starts_with("http://localhost:")
}

fn http_client(current: &str, timeout: Option<Duration>) -> Result<reqwest::Client, String> {
    let mut builder = reqwest::Client::builder()
        .user_agent(format!("Orion/{current}"))
        .connect_timeout(Duration::from_secs(15));
    if let Some(t) = timeout {
        builder = builder.timeout(t);
    }
    builder.build().map_err(|e| e.to_string())
}

fn current_version(app: &AppHandle) -> String {
    app.package_info().version.to_string()
}

/// The newer release, if there is one. No release yet (404) is not an error.
pub async fn fetch_manifest(current: &str) -> Result<Option<UpdateManifest>, String> {
    let client = http_client(current, Some(Duration::from_secs(30)))?;
    let resp = client
        .get(manifest_url())
        .send()
        .await
        .map_err(|e| format!("Could not reach the update server: {e}"))?;
    if resp.status() == reqwest::StatusCode::NOT_FOUND {
        return Ok(None);
    }
    if !resp.status().is_success() {
        return Err(format!("The update server returned {}", resp.status()));
    }
    let text = resp.text().await.map_err(|e| e.to_string())?;
    let manifest: UpdateManifest = serde_json::from_str(text.trim_start_matches('\u{feff}'))
        .map_err(|e| format!("The update information could not be read: {e}"))?;
    Ok(version_newer(&manifest.version, current).then_some(manifest))
}

/// Check now and remember the result.
pub async fn check_now(app: &AppHandle, state: &SharedUpdate) -> Result<Option<AppUpdate>, String> {
    let current = current_version(app);
    let found = fetch_manifest(&current).await?;
    let mut s = state.lock().await;
    s.available = found.clone();
    Ok(found.map(|m| AppUpdate { version: m.version, current, notes: m.notes }))
}

pub async fn cached(app: &AppHandle, state: &SharedUpdate) -> Option<AppUpdate> {
    let current = current_version(app);
    state
        .lock()
        .await
        .available
        .clone()
        .map(|m| AppUpdate { version: m.version, current, notes: m.notes })
}

/// Tell the user, once per version: a system notification (seen even when
/// Orion sits in the tray) and an event the window shows as "Update now".
pub async fn announce(app: &AppHandle, state: &SharedUpdate, update: &AppUpdate) {
    let _ = app.emit("app-update-available", update.clone());
    let mut s = state.lock().await;
    if s.notified.as_deref() == Some(update.version.as_str()) {
        return;
    }
    s.notified = Some(update.version.clone());
    use tauri_plugin_notification::NotificationExt;
    let _ = app
        .notification()
        .builder()
        .title(format!("Orion {} is available", update.version))
        .body("Open Orion or its tray menu and choose Update now. Your settings and memories are kept.")
        .show();
}

#[derive(Clone, serde::Serialize)]
struct Progress {
    stage: &'static str,
    downloaded: u64,
    total: u64,
}

/// Download, verify and start the update, then quit so it can replace Orion.
pub async fn install(app: &AppHandle, state: &SharedUpdate) -> Result<(), String> {
    let manifest = {
        let mut s = state.lock().await;
        if s.installing {
            return Err("An update is already being installed.".into());
        }
        s.installing = true;
        s.available.clone()
    };
    let result = install_inner(app, manifest).await;
    if result.is_err() {
        state.lock().await.installing = false;
    }
    result
}

async fn install_inner(app: &AppHandle, manifest: Option<UpdateManifest>) -> Result<(), String> {
    let current = current_version(app);
    let manifest = match manifest {
        Some(m) => m,
        None => fetch_manifest(&current).await?.ok_or("Orion is already up to date.")?,
    };
    if !allowed_url(&manifest.url) {
        return Err("The update link is not a secure download link.".into());
    }
    let pubkey = app
        .config()
        .plugins
        .0
        .get("updater")
        .and_then(|u| u.get("pubkey"))
        .and_then(|k| k.as_str())
        .map(str::to_string)
        .ok_or("This build of Orion has no update key, so updates cannot be verified.")?;

    let client = http_client(&current, None)?;
    let mut resp = client
        .get(&manifest.url)
        .send()
        .await
        .map_err(|e| format!("The download could not start: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("The download failed ({}).", resp.status()));
    }
    let total = resp.content_length().unwrap_or(0);
    let mut data: Vec<u8> = Vec::with_capacity(total as usize);
    let mut reported = 0usize;
    while let Some(chunk) = resp.chunk().await.map_err(|e| format!("The download was interrupted: {e}"))? {
        data.extend_from_slice(&chunk);
        if data.len() - reported >= 512 * 1024 {
            reported = data.len();
            let _ = app.emit("app-update-progress", Progress { stage: "downloading", downloaded: data.len() as u64, total });
        }
    }
    let _ = app.emit("app-update-progress", Progress { stage: "verifying", downloaded: data.len() as u64, total });

    verify_signature(&data, &manifest.signature, &pubkey)?;

    let safe_version: String = manifest
        .version
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '.' || *c == '-')
        .collect();
    let path = std::env::temp_dir().join(format!("OrionSetup-{safe_version}.exe"));
    std::fs::write(&path, &data).map_err(|e| format!("The update could not be saved: {e}"))?;

    let _ = app.emit("app-update-progress", Progress { stage: "installing", downloaded: data.len() as u64, total });
    std::process::Command::new(&path)
        .args(["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE=1"])
        .spawn()
        .map_err(|e| format!("The installer could not start: {e}"))?;

    // Give the installer a moment to open, then quit: it cannot replace the
    // app while it runs. Exiting stops the backend (RunEvent::ExitRequested).
    tokio::time::sleep(Duration::from_millis(1500)).await;
    app.exit(0);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newer_versions() {
        assert!(version_newer("1.0.2", "1.0.1"));
        assert!(version_newer("v1.0.10", "1.0.9"));
        assert!(version_newer("1.1", "1.0.9"));
        assert!(!version_newer("1.0.1", "1.0.1"));
        assert!(!version_newer("1.0.0", "1.0.1"));
        assert!(!version_newer("1.0.1-beta", "1.0.1"));
    }

    #[test]
    fn only_secure_links() {
        assert!(allowed_url("https://github.com/x/y.exe"));
        assert!(allowed_url("http://127.0.0.1:8765/y.exe"));
        assert!(!allowed_url("http://example.com/y.exe"));
        assert!(!allowed_url("file:///C:/y.exe"));
    }

    #[test]
    fn rejects_bad_signatures() {
        // Well-formed key, garbage signature: must never pass.
        let key = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDRDRkNCNUUxMzk5REI0ODgKUldTSXRKMDU0Ylg4VFBPMi91cmFETTgxMGkvczVMdDdzTkJ4dkRHWURNRCtMcWMrWno4ZTZNRzAK";
        assert!(verify_signature(b"data", "bm90IGEgc2lnbmF0dXJl", key).is_err());
        assert!(verify_signature(b"data", "%%%", key).is_err());
    }
}
