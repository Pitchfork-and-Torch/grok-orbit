//! Cross-tool handoff packs. Never inject into a live TUI pager.

use crate::model::HandoffPack;
use crate::projects;
use crate::redact::{is_session_id, redact};
use crate::snapshot::{session_detail, tui_live_ids};
use crate::web::is_web_id;
use std::path::Path;
use std::process::Command;

pub fn build_handoff(id: &str) -> Result<HandoffPack, String> {
    if !(is_session_id(id) || is_web_id(id)) {
        return Err("invalid session id".into());
    }
    let detail = session_detail(id)?;
    let live = detail.session.live || tui_live_ids().contains(id);
    let cwd = detail.session.cwd.clone();
    let clone = projects::clone_path_for(&detail.session);
    let web = is_web_id(id);
    let acp_cwd = match &clone {
        Some(p) => p.clone(),
        None if web => String::new(),
        None => acp_cwd_for(&cwd),
    };
    let branch = git_head(if acp_cwd.is_empty() { &cwd } else { &acp_cwd });
    let mut lines = Vec::new();
    lines.push("ORBIT HANDOFF".into());
    lines.push(format!("source: {}", detail.session.source));
    lines.push(format!("id: {}", detail.session.id));
    lines.push(format!("title: {}", redact(&detail.session.title)));
    if let Some(pid) = &detail.session.project_id {
        lines.push(format!("project: {pid}"));
    }
    if !cwd.is_empty() {
        lines.push(format!("cwd: {cwd}"));
    }
    if !acp_cwd.is_empty() && acp_cwd != cwd {
        lines.push(format!("clone: {acp_cwd}"));
    }
    if let Some(r) = &detail.session.remote {
        lines.push(format!("remote: {r}"));
    }
    if let Some(b) = &branch {
        lines.push(format!("branch: {b}"));
    }
    if let Some(m) = &detail.session.model {
        lines.push(format!("model: {m}"));
    }
    if let Some(u) = &detail.session.url {
        lines.push(format!("url: {u}"));
    }
    if let Some(pr) = detail.session.pr_url.as_deref().filter(|u| !u.is_empty()) {
        let st = detail.session.pr_state.as_deref().unwrap_or("unknown");
        lines.push(format!("pr: {st} {pr}"));
        if let Some(n) = detail.session.pr_file_count {
            lines.push(format!("pr_files: {n}"));
        }
        for file in detail.session.pr_files.iter().take(8) {
            lines.push(format!("  {file}"));
        }
    }
    lines.push(format!("live: {}", if live { "yes" } else { "no" }));
    append_well_lines(&mut lines, &detail.session.id, detail.session.project_id.as_deref());
    if let Some(plan) = detail.plan_excerpt.as_deref().filter(|p| !p.trim().is_empty()) {
        lines.push(String::new());
        lines.push("Plan".into());
        lines.push("-----".into());
        lines.push(truncate(&redact(plan), 1200));
    }
    if !detail.events.is_empty() {
        lines.push(String::new());
        lines.push("Recent".into());
        lines.push("------".into());
        for ev in detail.events.iter().rev().take(12).collect::<Vec<_>>().into_iter().rev()
        {
            let kind = ev.kind.replace('_', " ");
            lines.push(format!("[{kind}] {}", truncate(&redact(&ev.text), 280)));
        }
    }
    lines.push(String::new());
    lines.push(
        "Continue this work. Do not assume the previous pager is still attached.".into(),
    );
    if live {
        lines.push("Previous session is a live TUI. Do not inject into it.".into());
    }
    let inject_ok = !live && !acp_cwd.is_empty();
    let reason = if live {
        Some("live TUI pager; copy the pack, do not inject".into())
    } else if acp_cwd.is_empty() {
        Some("no local clone for this project; copy the pack".into())
    } else {
        None
    };
    Ok(HandoffPack {
        session_id: detail.session.id,
        source: detail.session.source,
        title: redact(&detail.session.title),
        cwd,
        acp_cwd,
        branch,
        url: detail.session.url,
        live,
        inject_ok,
        reason,
        text: lines.join("\n"),
    })
}

fn append_well_lines(lines: &mut Vec<String>, sid: &str, project_id: Option<&str>) {
    let Some(pid) = project_id.filter(|p| projects::is_named_well(p)) else {
        return;
    };
    let snap = crate::snapshot::collect_snapshot();
    if let Some(desk) = snap.attention.iter().find(|a| {
        a.kind == "desk_claim" && a.title.to_ascii_lowercase().contains(&format!("claim {pid}"))
    }) {
        lines.push(format!("desk: {}", redact(&desk.title)));
    }
    let members: Vec<_> = snap
        .sessions
        .iter()
        .filter(|s| s.id != sid && s.project_id.as_deref() == Some(pid))
        .take(6)
        .collect();
    if members.is_empty() {
        return;
    }
    lines.push(String::new());
    lines.push("Well".into());
    lines.push("----".into());
    for session in members {
        lines.push(format!(
            "- {} ({})",
            redact(&session.title),
            projects::member_kind(session)
        ));
    }
}

fn acp_cwd_for(cwd: &str) -> String {
    if !cwd.is_empty() && Path::new(cwd).is_dir() {
        return cwd.to_string();
    }
    std::env::var("USERPROFILE")
        .or_else(|_| std::env::var("HOME"))
        .unwrap_or_default()
}

fn git_head(cwd: &str) -> Option<String> {
    if cwd.is_empty() || !Path::new(cwd).is_dir() {
        return None;
    }
    let branch = git_out(cwd, &["rev-parse", "--abbrev-ref", "HEAD"])?;
    let sha = git_out(cwd, &["rev-parse", "--short", "HEAD"])?;
    if branch.is_empty() {
        return None;
    }
    Some(format!("{branch} @ {sha}"))
}

fn git_out(cwd: &str, args: &[&str]) -> Option<String> {
    let out = Command::new("git").args(args).current_dir(cwd).output().ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if s.is_empty() {
        None
    } else {
        Some(s)
    }
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let t: String = s.chars().take(max.saturating_sub(3)).collect();
        format!("{t}...")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::paths::grok_home;

    #[test]
    fn live_pack_refuses_inject() {
        let path = grok_home().join("active_sessions.json");
        let Ok(raw) = std::fs::read_to_string(&path) else {
            return;
        };
        let rows: Vec<serde_json::Value> = serde_json::from_str(&raw).unwrap_or_default();
        let Some(id) = rows.iter().find_map(|r| {
            let id = r.get("session_id").and_then(|v| v.as_str())?;
            let pid = r.get("pid").and_then(|v| v.as_u64())? as u32;
            if is_session_id(id) && crate::snapshot::tui_live_ids().contains(id) && pid > 0 {
                Some(id)
            } else {
                None
            }
        }) else {
            return;
        };
        let pack = build_handoff(id).expect("handoff");
        assert!(pack.text.contains("ORBIT HANDOFF"), "{}", pack.text);
        assert!(pack.text.contains("source:"));
        assert!(!pack.inject_ok, "{pack:?}");
        assert!(pack.live);
        assert!(!pack.text.contains("ghp_"));
    }

    #[test]
    fn package_redacts_tokens() {
        let dirty = redact("token ghp_exampleplaceholder000000 x");
        assert_eq!(dirty, "token [redacted] x");
    }
}
