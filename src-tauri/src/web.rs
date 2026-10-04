//! Consented grok.com / Cursor web adapters. Cache-only on the snapshot tick.

use crate::model::{AdapterStatus, Attention, Session};
use crate::paths::{orbit_tree, orbit_web_home};
use crate::redact::redact;
use serde::Deserialize;
use serde_json::Value;
use std::path::Path;
use std::process::Command;

#[derive(Debug, Clone)]
pub struct WebBundle {
    pub adapter: AdapterStatus,
    pub sessions: Vec<Session>,
    pub attention: Vec<Attention>,
    pub consent: bool,
    pub grok_status: String,
    pub grok_detail: String,
    pub cursor_status: String,
    pub cursor_detail: String,
    pub cursor_probed_at: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CacheFile {
    status: Option<String>,
    detail: Option<String>,
    probed_at: Option<String>,
    sessions: Option<Vec<CacheSession>>,
}

#[derive(Debug, Deserialize)]
struct CacheSession {
    id: String,
    title: String,
    url: String,
    status: Option<String>,
    remote: Option<String>,
    branch: Option<String>,
    pr_url: Option<String>,
    updated_at: Option<String>,
}

pub fn is_web_id(id: &str) -> bool {
    id.starts_with("web:grok:") || id.starts_with("web:cursor:")
}

fn ascii_hyphens(text: &str) -> String {
    text.replace('\u{2014}', " - ")
        .replace('\u{2013}', " - ")
        .replace('\u{2212}', "-")
}

pub fn normalize_cursor_status(title: &str, status: Option<&str>) -> (String, String) {
    let mut raw = status.unwrap_or("").trim().to_string();
    let tail = regex_lite_status_tail(title);
    let mut clean = title.to_string();
    if let Some((stripped, found)) = tail {
        if raw.is_empty() {
            raw = found;
        }
        clean = stripped;
    }
    clean = ascii_hyphens(clean.trim());
    if clean.is_empty() {
        clean = "untitled".into();
    }
    let key = raw
        .to_uppercase()
        .replace("BACKGROUND_COMPOSER_STATUS_", "");
    let mapped = match key.as_str() {
        "RUNNING" | "CREATING" => "running",
        "ACTIVE" => "active",
        "FINISHED" | "COMPLETED" => "finished",
        "ERROR" | "FAILED" | "EXPIRED" => "error",
        "CANCELLED" | "CANCELED" => "cancelled",
        "ARCHIVED" => "archived",
        "" => "unknown",
        other => {
            let lower = other.to_lowercase();
            return (clean.chars().take(180).collect(), lower.chars().take(24).collect());
        }
    };
    (clean.chars().take(180).collect(), mapped.into())
}

fn regex_lite_status_tail(title: &str) -> Option<(String, String)> {
    let start = title.rfind('[')?;
    if !title.ends_with(']') {
        return None;
    }
    let inner = &title[start + 1..title.len() - 1];
    if inner.is_empty() || !inner.bytes().all(|b| b.is_ascii_uppercase() || b == b'_') {
        return None;
    }
    let stripped = title[..start].trim().to_string();
    Some((stripped, inner.to_string()))
}

pub fn cursor_session_fields(status: &str) -> (String, String, String) {
    match status {
        "running" => ("live_working".into(), "ok".into(), "running".into()),
        "error" => ("needs_input".into(), "degraded".into(), "error".into()),
        "finished" | "cancelled" | "archived" | "active" | "unknown" => {
            ("disk".into(), "ok".into(), status.into())
        }
        other => ("disk".into(), "ok".into(), other.to_string()),
    }
}

pub fn load_web() -> WebBundle {
    let home = orbit_web_home();
    let consent = read_consent(&home);
    let grok = load_surface(&home, "grok_web", consent);
    let cursor = load_surface(&home, "cursor_web", consent);
    let mut sessions = Vec::new();
    sessions.extend(grok.1);
    sessions.extend(cursor.1);
    crate::pr::apply_to_sessions(&mut sessions);
    let mut attention = cursor_attention_list(&sessions);
    if !consent {
        attention.push(Attention {
            id: "web-consent".into(),
            session_id: None,
            source: "grok_web".into(),
            kind: "consent".into(),
            title: "Grant isolated browser consent for grok.com and Cursor web".into(),
            created_at: None,
            severity: "info".into(),
        });
    } else if grok.0.status == "unauth" || cursor.0.status == "unauth" {
        attention.push(Attention {
            id: "web-login".into(),
            session_id: None,
            source: "grok_web".into(),
            kind: "login".into(),
            title: "Open isolated login for grok.com / Cursor (never copies Chrome)".into(),
            created_at: None,
            severity: "info".into(),
        });
    }
    let adapter = AdapterStatus {
        name: "web".into(),
        status: if !consent {
            "unauth".into()
        } else if grok.0.status == "ok" || cursor.0.status == "ok" {
            "ok".into()
        } else if grok.0.status == "degraded" || cursor.0.status == "degraded" {
            "degraded".into()
        } else {
            "unauth".into()
        },
        detail: format!(
            "consent={} grok={} cursor={}",
            if consent { "yes" } else { "no" },
            grok.0.status,
            cursor.0.status
        ),
    };
    WebBundle {
        adapter,
        sessions,
        attention,
        consent,
        grok_status: grok.0.status,
        grok_detail: grok.0.detail,
        cursor_status: cursor.0.status,
        cursor_detail: cursor.0.detail,
        cursor_probed_at: pulse_probed_at().or(cursor.0.probed_at),
    }
}

fn pulse_probed_at() -> Option<String> {
    let path = crate::paths::orbit_web_home()
        .join("cache")
        .join("cursor_web.pulse.json");
    let text = std::fs::read_to_string(path).ok()?;
    let v: Value = serde_json::from_str(&text).ok()?;
    v.get("probed_at")?.as_str().map(|s| s.to_string())
}

fn read_consent(home: &Path) -> bool {
    let raw = std::fs::read_to_string(home.join("consent.json")).ok();
    let Some(text) = raw else {
        return false;
    };
    let Ok(v) = serde_json::from_str::<Value>(&text) else {
        return false;
    };
    v.get("granted").and_then(|g| g.as_bool()).unwrap_or(false)
}

struct SurfaceRow {
    status: String,
    detail: String,
    probed_at: Option<String>,
}

fn load_surface(home: &Path, surface: &str, consent: bool) -> (SurfaceRow, Vec<Session>) {
    if !consent {
        return (
            SurfaceRow {
                status: "needs_consent".into(),
                detail: "isolated browser consent not granted".into(),
                probed_at: None,
            },
            vec![],
        );
    }
    let path = home.join("cache").join(format!("{surface}.json"));
    let Some(cache) = std::fs::read_to_string(&path)
        .ok()
        .and_then(|t| serde_json::from_str::<CacheFile>(&t).ok())
    else {
        return (
            SurfaceRow {
                status: "unauth".into(),
                detail: "consent granted; no probe yet".into(),
                probed_at: None,
            },
            vec![],
        );
    };
    let cwd = if surface == "grok_web" {
        "grok.com"
    } else {
        "cursor.com"
    };
    let sessions = cache
        .sessions
        .unwrap_or_default()
        .into_iter()
        .filter(|s| is_web_id(&s.id))
        .map(|s| {
            let (title, agent_name, state, health) = if surface == "cursor_web" {
                let (clean, st) = normalize_cursor_status(&s.title, s.status.as_deref());
                let (state, health, name) = cursor_session_fields(&st);
                (redact(&clean), Some(name), state, health)
            } else {
                (redact(&s.title), None, "disk".into(), "ok".into())
            };
            Session {
                id: s.id,
                source: surface.to_string(),
                project_id: Some(cwd.to_string()),
                cwd: cwd.to_string(),
                title,
                summary: redact(&s.url),
                state,
                health,
                pid: None,
                model: None,
                agent_name,
                created_at: s.updated_at.clone(),
                updated_at: s.updated_at.clone(),
                last_active_at: s.updated_at.clone(),
                disk_path: None,
                url: Some(s.url),
                remote: s.remote,
                branch: s.branch,
                pr_url: s.pr_url,
                pr_state: None,
                pr_files: Vec::new(),
                pr_file_count: None,
                live: false,
                has_plan: false,
            }
        })
        .collect();
    (
        SurfaceRow {
            status: cache.status.unwrap_or_else(|| "degraded".into()),
            detail: cache.detail.unwrap_or_default(),
            probed_at: cache.probed_at,
        },
        sessions,
    )
}

pub fn normalize_pr_url(url: &str) -> String {
    let mut s = url.trim().to_ascii_lowercase();
    if let Some(i) = s.find('#') {
        s.truncate(i);
    }
    if let Some(i) = s.find('?') {
        s.truncate(i);
    }
    while s.ends_with('/') {
        s.pop();
    }
    s = s.replacen("https://www.github.com/", "https://github.com/", 1);
    s = s.replacen("https://www.gitlab.com/", "https://gitlab.com/", 1);
    s
}

pub fn pr_attention_id(url: &str) -> String {
    let key = normalize_pr_url(url)
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .replace('\\', "/");
    format!("cursor-pr-{key}")
}

fn pr_pick_rank(s: &Session) -> u8 {
    match s.agent_name.as_deref() {
        Some("running") => 0,
        Some("error") => 1,
        _ => 2,
    }
}

pub fn cursor_attention_list(sessions: &[Session]) -> Vec<Attention> {
    let mut out = Vec::new();
    for s in sessions {
        if s.source != "cursor_web" {
            continue;
        }
        if s.agent_name.as_deref() == Some("running") || s.agent_name.as_deref() == Some("error") {
            out.extend(cursor_attention_for(s));
        }
    }
    let mut groups: std::collections::BTreeMap<String, Vec<&Session>> =
        std::collections::BTreeMap::new();
    for s in sessions {
        if s.source != "cursor_web" {
            continue;
        }
        if s.agent_name.as_deref() == Some("running") || s.agent_name.as_deref() == Some("error") {
            continue;
        }
        if !crate::pr::needs_clearance(s.pr_state.as_deref()) {
            continue;
        }
        if let Some(pr) = s.pr_url.as_deref().filter(|u| !u.is_empty()) {
            groups.entry(normalize_pr_url(pr)).or_default().push(s);
        }
    }
    for (key, mut rows) in groups {
        rows.sort_by(|a, b| {
            pr_pick_rank(a)
                .cmp(&pr_pick_rank(b))
                .then_with(|| a.title.cmp(&b.title))
                .then_with(|| a.id.cmp(&b.id))
        });
        let winner = rows[0];
        let extra = rows.len().saturating_sub(1);
        let short = pr_short(winner.pr_url.as_deref().unwrap_or(&key));
        let mut title = format!("Cursor PR ready: {} ({})", winner.title, short);
        if extra > 0 {
            title.push_str(&format!(
                " +{} agent{}",
                extra,
                if extra == 1 { "" } else { "s" }
            ));
        }
        out.push(Attention {
            id: pr_attention_id(winner.pr_url.as_deref().unwrap_or(&key)),
            session_id: Some(winner.id.clone()),
            source: "cursor_web".into(),
            kind: "pr_ready".into(),
            title,
            created_at: winner.updated_at.clone(),
            severity: "warn".into(),
        });
    }
    out
}

pub fn cursor_attention_for(s: &Session) -> Vec<Attention> {
    if s.source != "cursor_web" {
        return vec![];
    }
    if s.agent_name.as_deref() == Some("running") {
        return vec![Attention {
            id: format!("cursor-run-{}", s.id),
            session_id: Some(s.id.clone()),
            source: "cursor_web".into(),
            kind: "running".into(),
            title: format!("Cursor agent running: {}", s.title),
            created_at: s.updated_at.clone(),
            severity: "warn".into(),
        }];
    }
    if s.agent_name.as_deref() == Some("error") {
        return vec![Attention {
            id: format!("cursor-err-{}", s.id),
            session_id: Some(s.id.clone()),
            source: "cursor_web".into(),
            kind: "error".into(),
            title: format!("Cursor agent error: {}", s.title),
            created_at: s.updated_at.clone(),
            severity: "error".into(),
        }];
    }
    if let Some(pr) = s.pr_url.as_deref().filter(|u| !u.is_empty()) {
        if !crate::pr::needs_clearance(s.pr_state.as_deref()) {
            return vec![];
        }
        return vec![Attention {
            id: format!("cursor-pr-{}", s.id),
            session_id: Some(s.id.clone()),
            source: "cursor_web".into(),
            kind: "pr_ready".into(),
            title: format!("Cursor PR ready: {} ({})", s.title, pr_short(pr)),
            created_at: s.updated_at.clone(),
            severity: "warn".into(),
        }];
    }
    vec![]
}

pub fn pr_url_allowed(url: &str) -> bool {
    let lower = url.to_ascii_lowercase();
    if lower.contains('@') || lower.contains(' ') {
        return false;
    }
    let ok_host = lower.starts_with("https://github.com/")
        || lower.starts_with("https://www.github.com/")
        || lower.starts_with("https://gitlab.com/")
        || lower.starts_with("https://www.gitlab.com/");
    ok_host && (lower.contains("/pull/") || lower.contains("/merge_requests/"))
}

pub fn pr_short(url: &str) -> String {
    if let Some(idx) = url.rfind("/pull/") {
        let n = url[idx + 6..].split(|c: char| !c.is_ascii_digit()).next().unwrap_or("");
        if !n.is_empty() {
            return format!("#{n}");
        }
    }
    if let Some(idx) = url.rfind("/merge_requests/") {
        let n = url[idx + 16..].split(|c: char| !c.is_ascii_digit()).next().unwrap_or("");
        if !n.is_empty() {
            return format!("!{n}");
        }
    }
    "PR".into()
}

pub fn find_web_session(id: &str) -> Option<Session> {
    load_web().sessions.into_iter().find(|s| s.id == id)
}

pub fn run_web_cli(args: &[&str]) -> Result<String, String> {
    let script = orbit_tree().join("scripts").join("web_adapters.py");
    if !script.exists() {
        return Err(format!("missing {}", script.display()));
    }
    let mut cmd = Command::new("py");
    cmd.arg("-3").arg(&script).args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }
    let out = cmd.output().map_err(|e| e.to_string())?;
    let text = String::from_utf8_lossy(&out.stdout).to_string();
    let err = String::from_utf8_lossy(&out.stderr).to_string();
    if !out.status.success() {
        return Err(if err.trim().is_empty() { text } else { err });
    }
    Ok(text)
}

pub fn open_url(url: &str) -> Result<String, String> {
    if !(url.starts_with("https://grok.com/")
        || url.starts_with("https://cursor.com/")
        || url.starts_with("https://www.grok.com/")
        || url.starts_with("https://www.cursor.com/"))
    {
        return Err("refusing to open non grok/cursor https url".into());
    }
    open_raw(url)
}

pub fn open_license_url(url: &str) -> Result<String, String> {
    if url.starts_with("https://orbit.jonbailey.xyz/")
        || url.starts_with("https://checkout.stripe.com/")
        || url.starts_with("https://buy.stripe.com/")
        || url.starts_with("https://docs.x.ai/")
        || url.starts_with("https://console.x.ai/")
        || url.starts_with("https://platform.openai.com/")
        || url.starts_with("https://console.anthropic.com/")
        || url.starts_with("https://aistudio.google.com/")
    {
        return open_raw(url);
    }
    Err("refusing to open that url from setup".into())
}

pub fn open_pr_url(url: &str) -> Result<String, String> {
    if !pr_url_allowed(url) {
        return Err("refusing to open non github/gitlab pull url".into());
    }
    open_raw(url)
}

fn open_raw(url: &str) -> Result<String, String> {
    #[cfg(windows)]
    {
        Command::new("cmd")
            .args(["/C", "start", "", url])
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(format!("opened {url}"));
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(url)
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(format!("opened {url}"));
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open")
            .arg(url)
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(format!("opened {url}"));
    }
    #[allow(unreachable_code)]
    Err("open_url unsupported".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn web_ids_are_namespaced() {
        assert!(is_web_id("web:grok:abc123conversation"));
        assert!(is_web_id("web:cursor:ag_hello"));
        assert!(!is_web_id("01a0005f-5d25-7102-8e5f-906bac9373e0"));
    }

    #[test]
    fn cursor_status_strips_composer_tail() {
        let (title, st) = normalize_cursor_status(
            "v3.14 reclaim [BACKGROUND_COMPOSER_STATUS_RUNNING]",
            None,
        );
        assert_eq!(title, "v3.14 reclaim");
        assert_eq!(st, "running");
        let (title, st) = normalize_cursor_status("Add README", Some("ACTIVE"));
        assert_eq!(title, "Add README");
        assert_eq!(st, "active");
        let (_, run) = normalize_cursor_status("Add README", Some("RUNNING"));
        assert_eq!(run, "running");
        let (title, st) = normalize_cursor_status("VELA \u{2014} land", Some("FINISHED"));
        assert_eq!(title, "VELA  -  land");
        assert_eq!(st, "finished");
    }

    #[test]
    fn pr_urls_are_gated_and_short() {
        assert!(pr_url_allowed(
            "https://github.com/Pitchfork-and-Torch/vela/pull/8"
        ));
        assert!(pr_url_allowed(
            "https://gitlab.com/group/proj/-/merge_requests/3"
        ));
        assert!(!pr_url_allowed("https://cursor.com/agents/bc-1"));
        assert!(!pr_url_allowed("https://evil.example/pull/1"));
        assert!(!pr_url_allowed("https://github.com/foo/bar"));
        assert_eq!(
            pr_short("https://github.com/Pitchfork-and-Torch/vela/pull/8"),
            "#8"
        );
    }

    #[test]
    fn pr_ready_attention_skips_running() {
        let mut s = Session {
            id: "web:cursor:bc-1".into(),
            source: "cursor_web".into(),
            title: "VELA land".into(),
            agent_name: Some("finished".into()),
            pr_url: Some("https://github.com/Pitchfork-and-Torch/vela/pull/8".into()),
            ..Default::default()
        };
        let a = cursor_attention_for(&s);
        assert_eq!(a[0].kind, "pr_ready");
        assert!(a[0].title.contains("#8"));
        s.agent_name = Some("running".into());
        assert_eq!(cursor_attention_for(&s)[0].kind, "running");
        s.agent_name = Some("finished".into());
        s.pr_state = Some("merged".into());
        assert!(cursor_attention_for(&s).is_empty());
        s.pr_state = Some("draft".into());
        assert!(cursor_attention_for(&s).is_empty());
    }

    #[test]
    fn duplicate_prs_collapse_to_one_attention() {
        let a = Session {
            id: "web:cursor:bc-1".into(),
            source: "cursor_web".into(),
            project_id: Some("vela".into()),
            title: "Rebase VELA #8".into(),
            agent_name: Some("finished".into()),
            pr_url: Some("https://github.com/Pitchfork-and-Torch/vela/pull/8".into()),
            ..Default::default()
        };
        let mut b = a.clone();
        b.id = "web:cursor:bc-2".into();
        b.title = "VELA land observe-only".into();
        b.pr_url = Some("https://www.github.com/Pitchfork-and-Torch/vela/pull/8/".into());
        let rows = cursor_attention_list(&[a.clone(), b.clone()]);
        let prs: Vec<_> = rows.iter().filter(|x| x.kind == "pr_ready").collect();
        assert_eq!(prs.len(), 1);
        assert!(prs[0].title.contains("+1 agent"));
        assert!(prs[0].id.contains("github.com/pitchfork-and-torch/vela/pull/8"));
        b.pr_state = Some("merged".into());
        let none = cursor_attention_list(&[b]);
        assert!(none.iter().all(|x| x.kind != "pr_ready"));
    }
}
