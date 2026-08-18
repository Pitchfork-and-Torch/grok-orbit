//! Cached GitHub/GitLab PR state from local `gh pr view`. No tokens printed.

use crate::model::Session;
use crate::paths::{orbit_tree, orbit_web_home};
use crate::web::normalize_pr_url;
use serde::Deserialize;
use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

pub const TTL_SECS: u64 = 300;
static PR_REFRESH_IN_FLIGHT: AtomicBool = AtomicBool::new(false);

#[derive(Debug, Clone, Default, Deserialize)]
pub struct PrRow {
    pub state: Option<String>,
    pub files: Option<Vec<String>>,
    pub file_count: Option<u32>,
}

#[derive(Debug, Deserialize)]
struct PrCacheFile {
    updated_at: Option<u64>,
    prs: Option<HashMap<String, PrRow>>,
}

#[allow(dead_code)]
pub fn classify(state: Option<&str>, is_draft: bool) -> &'static str {
    let key = state.unwrap_or("").trim().to_ascii_uppercase();
    match key.as_str() {
        "OPEN" if is_draft => "draft",
        "OPEN" => "open",
        "MERGED" => "merged",
        "CLOSED" => "closed",
        _ => "unknown",
    }
}

pub fn needs_clearance(pr_state: Option<&str>) -> bool {
    matches!(
        pr_state.unwrap_or("unknown").trim().to_ascii_lowercase().as_str(),
        "open" | "unknown" | ""
    )
}

#[allow(dead_code)]
pub fn is_done(pr_state: Option<&str>) -> bool {
    matches!(
        pr_state.unwrap_or("").trim().to_ascii_lowercase().as_str(),
        "merged" | "closed"
    )
}

pub fn cache_path() -> std::path::PathBuf {
    orbit_web_home().join("cache").join("pr_state.json")
}

pub fn load_cache(path: &Path) -> HashMap<String, PrRow> {
    let Ok(text) = std::fs::read_to_string(path) else {
        return HashMap::new();
    };
    let Ok(file) = serde_json::from_str::<PrCacheFile>(&text) else {
        return HashMap::new();
    };
    file.prs.unwrap_or_default()
}

fn cache_updated_at(path: &Path) -> u64 {
    let Ok(text) = std::fs::read_to_string(path) else {
        return 0;
    };
    serde_json::from_str::<PrCacheFile>(&text)
        .ok()
        .and_then(|f| f.updated_at)
        .unwrap_or(0)
}

fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

pub fn cache_is_fresh(path: &Path, urls: &[String]) -> bool {
    if !path.exists() {
        return urls.is_empty();
    }
    let updated = cache_updated_at(path);
    if now_unix().saturating_sub(updated) > TTL_SECS {
        return false;
    }
    let prs = load_cache(path);
    for url in urls {
        let key = normalize_pr_url(url);
        if !key.is_empty() && !prs.contains_key(&key) {
            return false;
        }
    }
    true
}

pub fn apply_to_sessions(sessions: &mut [Session]) {
    apply_to_sessions_from(sessions, &cache_path());
}

pub fn apply_to_sessions_from(sessions: &mut [Session], path: &Path) {
    let prs = load_cache(path);
    if prs.is_empty() {
        return;
    }
    for session in sessions.iter_mut() {
        let Some(url) = session.pr_url.as_deref().filter(|u| !u.is_empty()) else {
            continue;
        };
        let Some(row) = prs.get(&normalize_pr_url(url)) else {
            continue;
        };
        session.pr_state = Some(row.state.clone().unwrap_or_else(|| "unknown".into()));
        let files = row.files.clone().unwrap_or_default();
        session.pr_file_count = Some(row.file_count.unwrap_or(files.len() as u32));
        session.pr_files = files.into_iter().take(8).collect();
    }
}

pub fn unique_pr_urls(sessions: &[Session]) -> Vec<String> {
    let mut out = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    for session in sessions {
        let Some(url) = session.pr_url.as_deref().filter(|u| !u.is_empty()) else {
            continue;
        };
        let key = normalize_pr_url(url);
        if key.is_empty() || !seen.insert(key) {
            continue;
        }
        out.push(url.to_string());
    }
    out
}

pub fn maybe_spawn_refresh(sessions: &[Session]) {
    if cfg!(test) {
        return;
    }
    if std::env::var("ORBIT_PR_REFRESH").ok().as_deref() == Some("0") {
        return;
    }
    let urls = unique_pr_urls(sessions);
    if urls.is_empty() {
        return;
    }
    if cache_is_fresh(&cache_path(), &urls) {
        return;
    }
    if PR_REFRESH_IN_FLIGHT.swap(true, Ordering::SeqCst) {
        return;
    }
    let script = orbit_tree().join("scripts").join("pr_state.py");
    if !script.exists() {
        PR_REFRESH_IN_FLIGHT.store(false, Ordering::SeqCst);
        return;
    }
    std::thread::spawn(move || {
        let mut cmd = std::process::Command::new("py");
        cmd.arg("-3").arg(&script).arg("refresh");
        cmd.stdin(std::process::Stdio::null());
        cmd.stdout(std::process::Stdio::null());
        cmd.stderr(std::process::Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000);
        }
        let _ = cmd.spawn();
        PR_REFRESH_IN_FLIGHT.store(false, Ordering::SeqCst);
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classify_maps_gh_states() {
        assert_eq!(classify(Some("OPEN"), false), "open");
        assert_eq!(classify(Some("OPEN"), true), "draft");
        assert_eq!(classify(Some("MERGED"), false), "merged");
        assert_eq!(classify(Some("CLOSED"), false), "closed");
        assert_eq!(classify(Some(""), false), "unknown");
        assert!(needs_clearance(Some("open")));
        assert!(needs_clearance(None));
        assert!(!needs_clearance(Some("draft")));
        assert!(!needs_clearance(Some("merged")));
        assert!(is_done(Some("closed")));
    }

    #[test]
    fn apply_overlay_sets_session_fields() {
        let dir = std::env::temp_dir().join(format!("orbit-pr-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("pr_state.json");
        std::fs::write(
            &path,
            r#"{
  "updated_at": 1,
  "prs": {
    "https://github.com/pitchfork-and-torch/vela/pull/8": {
      "state": "merged",
      "files": ["src/a.rs", "src/b.rs"],
      "file_count": 2
    }
  }
}
"#,
        )
        .unwrap();
        let mut sessions = vec![Session {
            id: "web:cursor:a".into(),
            source: "cursor_web".into(),
            pr_url: Some("https://www.github.com/Pitchfork-and-Torch/vela/pull/8/".into()),
            ..Default::default()
        }];
        apply_to_sessions_from(&mut sessions, &path);
        assert_eq!(sessions[0].pr_state.as_deref(), Some("merged"));
        assert_eq!(sessions[0].pr_file_count, Some(2));
        assert_eq!(sessions[0].pr_files.len(), 2);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
