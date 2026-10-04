//! Tray badge, unseen attention, and Cursor pulse flags. No secrets.

use crate::acp::AcpHub;
use crate::model::Snapshot;
#[cfg(test)]
use crate::model::Attention;
use crate::paths::{orbit_db_path, orbit_web_home};
use rusqlite::Connection;
use serde::Serialize;
use serde_json::{json, Value};
use std::fs;
use std::path::Path;
use tauri::{AppHandle, Emitter, Manager};

const TRAY_ID: &str = "orbit";
const TOOLTIP_MAX: usize = 120;

#[derive(Debug, Clone, Serialize)]
pub struct AttentionToast {
    pub id: String,
    pub title: String,
    pub kind: String,
}

pub fn is_hot_kind(kind: &str) -> bool {
    matches!(kind, "running" | "error" | "pr_ready" | "acp_perm" | "stale")
}

pub fn tray_tooltip(count: usize, first_title: &str) -> String {
    if count == 0 {
        return "Orbit quiet".into();
    }
    let first = first_title.trim();
    let line = if first.is_empty() {
        format!("{count} waiting")
    } else {
        format!("{count} waiting | {first}")
    };
    if line.chars().count() <= TOOLTIP_MAX {
        line
    } else {
        line.chars().take(TOOLTIP_MAX.saturating_sub(3)).collect::<String>() + "..."
    }
}

pub fn window_title(count: usize) -> String {
    if count == 0 {
        "Grok Orbit".into()
    } else {
        format!("Grok Orbit ({count})")
    }
}

pub fn cursor_pulse_enabled() -> bool {
    let path = orbit_web_home().join("consent.json");
    let Ok(text) = fs::read_to_string(path) else {
        return true;
    };
    let Ok(v) = serde_json::from_str::<Value>(&text) else {
        return true;
    };
    v.get("cursor_pulse").and_then(|x| x.as_bool()).unwrap_or(true)
}

pub fn set_cursor_pulse(on: bool) -> Result<String, String> {
    let path = orbit_web_home().join("consent.json");
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let mut v = fs::read_to_string(&path)
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .unwrap_or_else(|| json!({}));
    if !v.is_object() {
        v = json!({});
    }
    v["cursor_pulse"] = json!(on);
    fs::write(&path, serde_json::to_string_pretty(&v).map_err(|e| e.to_string())? + "\n")
        .map_err(|e| e.to_string())?;
    Ok(if on {
        "Cursor pulse on (every 60s)".into()
    } else {
        "Cursor pulse off".into()
    })
}

pub fn cursor_key_present() -> bool {
    let path = orbit_web_home().join("cursor_api_key.txt");
    fs::read_to_string(path)
        .ok()
        .map(|t| t.contains("crsr_"))
        .unwrap_or(false)
}

fn open_db(path: &Path) -> Result<Connection, String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let conn = Connection::open(path).map_err(|e| e.to_string())?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS attention_seen (
            id TEXT PRIMARY KEY,
            seen_at TEXT NOT NULL
        )",
        [],
    )
    .map_err(|e| e.to_string())?;
    Ok(conn)
}

const SEEDED: &str = "__orbit_seeded__";

pub fn take_unseen(db_path: &Path, current_ids: &[String]) -> Result<Vec<String>, String> {
    let conn = open_db(db_path)?;
    let mut stmt = conn
        .prepare("SELECT id FROM attention_seen")
        .map_err(|e| e.to_string())?;
    let existing: std::collections::HashSet<String> = stmt
        .query_map([], |row| row.get(0))
        .map_err(|e| e.to_string())?
        .filter_map(|r| r.ok())
        .collect();
    let first_run = !existing.contains(SEEDED);
    let now = chrono_like_now();
    let _ = conn.execute(
        "INSERT OR IGNORE INTO attention_seen (id, seen_at) VALUES (?1, ?2)",
        (SEEDED, &now),
    );
    let mut unseen = Vec::new();
    if !first_run {
        for id in current_ids {
            if !existing.contains(id) {
                unseen.push(id.clone());
            }
        }
    }
    for old in &existing {
        if old != SEEDED && !current_ids.iter().any(|id| id == old) {
            let _ = conn.execute("DELETE FROM attention_seen WHERE id = ?1", [old]);
        }
    }
    for id in current_ids {
        let _ = conn.execute(
            "INSERT OR IGNORE INTO attention_seen (id, seen_at) VALUES (?1, ?2)",
            (id, &now),
        );
    }
    Ok(unseen)
}

fn chrono_like_now() -> String {
    // RFC3339-ish UTC from system time without extra crate.
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{secs}")
}

fn hot_items(snap: &Snapshot, acp_n_titles: &[(String, String)]) -> Vec<AttentionToast> {
    let mut out: Vec<AttentionToast> = snap
        .attention
        .iter()
        .filter(|a| is_hot_kind(&a.kind))
        .map(|a| AttentionToast {
            id: a.id.clone(),
            title: a.title.clone(),
            kind: a.kind.clone(),
        })
        .collect();
    for (id, title) in acp_n_titles {
        out.push(AttentionToast {
            id: id.clone(),
            title: title.clone(),
            kind: "acp_perm".into(),
        });
    }
    out
}

pub fn apply(app: &AppHandle, snap: &Snapshot) {
    let acp_titles: Vec<(String, String)> = app
        .try_state::<AcpHub>()
        .map(|hub| {
            hub.state()
                .permissions
                .into_iter()
                .map(|p| (format!("acp-perm-{}", p.request_id), p.title))
                .collect()
        })
        .unwrap_or_default();
    let items = hot_items(snap, &acp_titles);
    let ids: Vec<String> = items.iter().map(|i| i.id.clone()).collect();
    let unseen = take_unseen(&orbit_db_path(), &ids).unwrap_or_default();
    let mut toasted = 0usize;
    for item in &items {
        if unseen.iter().any(|id| id == &item.id) {
            if toasted < 3 {
                let _ = app.emit("orbit-attention", item);
                toasted += 1;
            }
        }
    }
    let count = items.len();
    let first = items.first().map(|i| i.title.as_str()).unwrap_or("");
    let tip = tray_tooltip(count, first);
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let _ = tray.set_tooltip(Some(tip.as_str()));
        if count > 0 {
            let _ = tray.set_title(Some(count.to_string()));
        } else {
            let _ = tray.set_title(None::<&str>);
        }
    }
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.set_title(&window_title(count));
    }
}

/// Test helper: hot attention ids from a list (no db).
#[cfg(test)]
pub fn hot_ids(attention: &[Attention], acp_ids: &[String]) -> Vec<String> {
    let mut ids: Vec<String> = attention
        .iter()
        .filter(|a| is_hot_kind(&a.kind))
        .map(|a| a.id.clone())
        .collect();
    ids.extend(acp_ids.iter().cloned());
    ids
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::Attention;

    fn att(id: &str, kind: &str) -> Attention {
        Attention {
            id: id.into(),
            session_id: None,
            source: "cursor_web".into(),
            kind: kind.into(),
            title: format!("t-{id}"),
            created_at: None,
            severity: "warn".into(),
        }
    }

    #[test]
    fn quiet_tooltip_and_title() {
        assert_eq!(tray_tooltip(0, "x"), "Orbit quiet");
        assert_eq!(window_title(0), "Grok Orbit");
        assert_eq!(window_title(3), "Grok Orbit (3)");
        let tip = tray_tooltip(2, "Cursor agent running: VELA");
        assert!(tip.starts_with("2 waiting | "));
        assert!(tip.len() <= 120);
    }

    #[test]
    fn hot_kinds_only() {
        let rows = vec![
            att("a", "running"),
            att("b", "desk_claim"),
            att("c", "error"),
            att("d", "plan"),
        ];
        let ids = hot_ids(&rows, &["acp-perm-1".into()]);
        assert_eq!(ids, vec!["a", "c", "acp-perm-1"]);
        assert!(is_hot_kind("pr_ready"));
        assert!(is_hot_kind("stale"));
        assert!(!is_hot_kind("consent"));
    }

    #[test]
    fn unseen_seeds_first_run_then_diffs() {
        let dir = std::env::temp_dir().join(format!("orbit-pulse-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let db = dir.join("orbit.db");
        let first = take_unseen(&db, &["run-1".into(), "err-1".into()]).unwrap();
        assert!(first.is_empty());
        let second = take_unseen(&db, &["run-1".into(), "err-1".into(), "run-2".into()]).unwrap();
        assert_eq!(second, vec!["run-2".to_string()]);
        let gone = take_unseen(&db, &["run-2".into()]).unwrap();
        assert!(gone.is_empty());
        let again = take_unseen(&db, &["run-1".into(), "run-2".into()]).unwrap();
        assert_eq!(again, vec!["run-1".to_string()]);
        let _ = fs::remove_dir_all(&dir);
    }
}
