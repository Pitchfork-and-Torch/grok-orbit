use crate::model::*;
use crate::bot::{local_exec_alive, steward_pack_version};
use crate::paths::{grok_bin, grok_home, grokbot_dir, session_dir};
use crate::redact::{is_session_id, redact};
use crate::paths::orbit_web_home;
use crate::projects;
use crate::web::{find_web_session, is_web_id, load_web};
use rusqlite::Connection;
use serde_json::Value;
use std::collections::HashMap;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

struct SnapMemo {
    fp: String,
    last_full: Instant,
    snap: Snapshot,
}

static SNAP_MEMO: Mutex<Option<SnapMemo>> = Mutex::new(None);
static PROC_MEMO: Mutex<Option<(Instant, u32, u32, u32, bool, Option<String>)>> = Mutex::new(None);

struct TailMemo {
    mtime: u64,
    events: Vec<SessionEvent>,
}

static TAIL_MEMO: Mutex<Option<HashMap<String, TailMemo>>> = Mutex::new(None);

pub fn tui_live_ids() -> std::collections::HashSet<String> {
    let home = grok_home();
    let (live, _) = live_sessions(&home);
    live.into_iter()
        .filter(|s| s.live)
        .map(|s| s.id)
        .collect()
}

fn file_mtime_ms(path: &Path) -> u64 {
    path.metadata()
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn dir_mtime_ms(path: &Path) -> u64 {
    let mut best = file_mtime_ms(path);
    if let Ok(rd) = std::fs::read_dir(path) {
        for ent in rd.flatten() {
            best = best.max(file_mtime_ms(&ent.path()));
        }
    }
    best
}

fn live_pid_sig(home: &Path) -> String {
    let raw = std::fs::read_to_string(home.join("active_sessions.json")).unwrap_or_default();
    let rows: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
    let mut bits: Vec<String> = rows
        .iter()
        .filter_map(|r| {
            let id = r.get("session_id")?.as_str()?;
            let pid = r.get("pid")?.as_u64()?;
            Some(format!("{id}:{pid}"))
        })
        .collect();
    bits.sort();
    bits.join(",")
}

fn snapshot_fingerprint(home: &Path) -> String {
    let web = orbit_web_home();
    format!(
        "a{}|d{}|g{}|c{}|n{}|p{}|u{}|r{}",
        file_mtime_ms(&home.join("active_sessions.json")),
        dir_mtime_ms(&home.join("desk").join("claims")),
        file_mtime_ms(&web.join("cache").join("grok_web.json")),
        file_mtime_ms(&web.join("cache").join("cursor_web.json")),
        file_mtime_ms(&web.join("consent.json")),
        live_pid_sig(home),
        file_mtime_ms(&web.join("cache").join("cursor_web.pulse.json")),
        file_mtime_ms(&web.join("cache").join("pr_state.json"))
    )
}

pub fn collect_snapshot() -> Snapshot {
    collect_snapshot_ex(false)
}

pub fn collect_snapshot_ex(force_full: bool) -> Snapshot {
    let home = grok_home();
    let fp = snapshot_fingerprint(&home);
    if !force_full {
        if let Ok(guard) = SNAP_MEMO.lock() {
            if let Some(memo) = guard.as_ref() {
                if memo.fp == fp && memo.last_full.elapsed() < Duration::from_secs(15) {
                    let mut snap = memo.snap.clone();
                    snap.elapsed_ms = 0;
                    snap.generated_at = now_rfc3339();
                    snap.snap_profile = Some("cache".into());
                    return snap;
                }
            }
        }
    }
    let t0 = InstantLike::now();
    let home = grok_home();
    let mut last = InstantLike::now();
    let (mut live, a_live) = live_sessions(&home);
    let ms_live = last.elapsed_ms();
    last = InstantLike::now();
    let (indexed, a_idx) = index_sessions(&home, 80);
    let ms_idx = last.elapsed_ms();
    last = InstantLike::now();
    let (mut attention, a_desk) = desk_attention(&home);
    let ms_desk = last.elapsed_ms();
    last = InstantLike::now();
    let (mut surfaces, a_proc) = process_scan(&live);
    let ms_proc = last.elapsed_ms();
    last = InstantLike::now();
    let web = load_web();
    let ms_web = last.elapsed_ms();
    last = InstantLike::now();
    let mut sessions = merge_sessions(&mut live, indexed);
    sessions.extend(web.sessions.clone());
    crate::pr::apply_to_sessions(&mut sessions);
    attention.extend(web.attention.clone());
    surfaces.web_consent = web.consent;
    surfaces.grok_web = web.grok_status.clone();
    surfaces.grok_web_detail = Some(web.grok_detail.clone());
    surfaces.cursor_web = web.cursor_status.clone();
    surfaces.cursor_web_detail = Some(web.cursor_detail.clone());
    surfaces.cursor_web_probed_at = web.cursor_probed_at.clone();
    surfaces.cursor_pulse = crate::pulse::cursor_pulse_enabled();
    let cook = crate::cook::status();
    surfaces.cook_armed = cook.armed;
    surfaces.cook_detail = cook.last_detail.clone();
    surfaces.cook_summary = cook.last_summary.clone();
    surfaces.cook_staff = cook.staff_now;
    for s in &sessions {
        if s.has_plan && s.live {
            attention.push(Attention {
                id: format!("plan-{}", s.id),
                session_id: Some(s.id.clone()),
                source: "grok_build".into(),
                kind: "plan".into(),
                title: format!("Plan file present: {}", s.title),
                created_at: s.updated_at.clone(),
                severity: "warn".into(),
            });
        }
        if crate::clock::is_stale_live(s) {
            let age = crate::clock::session_when(s)
                .and_then(crate::clock::age_secs_now)
                .map(crate::clock::format_age_seconds)
                .unwrap_or_else(|| "30m+".into());
            attention.push(Attention {
                id: format!("stale-{}", s.id),
                session_id: Some(s.id.clone()),
                source: s.source.clone(),
                kind: "stale".into(),
                title: format!("Live pager quiet {age}: {}", s.title),
                created_at: s.updated_at.clone(),
                severity: "warn".into(),
            });
        }
    }
    let adapters = vec![a_live, a_idx, a_desk, a_proc, web.adapter];
    let projects = projects::link_sessions(&mut sessions);
    let ms_merge = last.elapsed_ms();
    last = InstantLike::now();
    let situation = situation_text(&sessions, &projects, &adapters, &surfaces, &attention);
    let ms_sit = last.elapsed_ms();
    last = InstantLike::now();
    let activity = collect_activity(&sessions);
    let ms_act = last.elapsed_ms();
    crate::pr::maybe_spawn_refresh(&sessions);
    let profile = format!(
        "live={ms_live} index={ms_idx} desk={ms_desk} proc={ms_proc} web={ms_web} merge={ms_merge} sit={ms_sit} act={ms_act}"
    );
    if std::env::var("ORBIT_SNAP_PROFILE").ok().as_deref() == Some("1") {
        eprintln!("[orbit-snap] {}ms {profile}", t0.elapsed_ms());
    }
    let snap = Snapshot {
        generated_at: now_rfc3339(),
        elapsed_ms: t0.elapsed_ms(),
        situation,
        adapters,
        projects,
        sessions,
        attention,
        activity,
        surfaces,
        grok_home: home.display().to_string(),
        snap_profile: Some(profile),
    };
    if let Ok(mut guard) = SNAP_MEMO.lock() {
        *guard = Some(SnapMemo {
            fp,
            last_full: Instant::now(),
            snap: snap.clone(),
        });
    }
    snap
}

pub fn search_sessions(query: &str) -> Result<Vec<SearchHit>, String> {
    let q = query.trim();
    if q.is_empty() {
        return Ok(Vec::new());
    }
    let home = grok_home();
    let db = home.join("sessions").join("session_search.sqlite");
    if !db.exists() {
        return Err("session index missing".into());
    }
    let con = Connection::open_with_flags(
        &db,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|e| e.to_string())?;
    let fts = sanitize_fts(q);
    let mut stmt = con
        .prepare(
            "SELECT d.session_id, d.cwd, d.updated_at, d.title,
                    snippet(session_docs_fts, 1, '', '', ' ... ', 16)
             FROM session_docs_fts f
             JOIN session_docs d ON d.rowid = f.rowid
             WHERE session_docs_fts MATCH ?
             ORDER BY d.updated_at DESC
             LIMIT 40",
        )
        .map_err(|e| e.to_string())?;
    let mut rows = stmt.query([&fts]).map_err(|e| e.to_string())?;
    let live = tui_live_ids();
    let mut out = Vec::new();
    while let Some(row) = rows.next().map_err(|e| e.to_string())? {
        let id: String = row.get(0).map_err(|e| e.to_string())?;
        if !is_session_id(&id) {
            continue;
        }
        let cwd: String = row.get(1).unwrap_or_default();
        let updated: i64 = row.get(2).unwrap_or(0);
        let title: String = row.get(3).unwrap_or_default();
        let snippet: String = row.get(4).unwrap_or_default();
        let title = truncate(&redact(&title), 180);
        let snippet = {
            let s = redact(snippet.trim());
            if s.is_empty() {
                title.clone()
            } else {
                truncate(&s, 220)
            }
        };
        out.push(SearchHit {
            id: id.clone(),
            title,
            cwd,
            updated_at: unix_to_rfc3339(updated),
            snippet,
            live: live.contains(&id),
        });
    }
    Ok(out)
}

fn collect_activity(sessions: &[Session]) -> Vec<ActivityItem> {
    let mut picks: Vec<&Session> = Vec::new();
    for s in sessions.iter().filter(|s| s.live) {
        picks.push(s);
    }
    for s in sessions.iter().filter(|s| !s.live).take(8) {
        picks.push(s);
    }
    let home = grok_home();
    let mut out = Vec::new();
    for s in sessions.iter().filter(|s| {
        s.source == "cursor_web" && s.agent_name.as_deref() == Some("running")
    }) {
        out.push(ActivityItem {
            id: format!("{}:cursor_running", s.id),
            session_id: s.id.clone(),
            title: s.title.clone(),
            kind: "cursor_running".into(),
            text: "Cloud agent running on cursor.com".into(),
            live: false,
        });
    }
    for s in picks {
        if is_web_id(&s.id) {
            continue;
        }
        let disk = resolve_disk(&home, s);
        let events = disk
            .as_ref()
            .map(|d| tail_events_memo(&d.join("updates.jsonl"), 24_000, 6))
            .unwrap_or_default();
        for ev in events.into_iter().rev() {
            out.push(ActivityItem {
                id: format!("{}:{}:{}", s.id, ev.kind, out.len()),
                session_id: s.id.clone(),
                title: s.title.clone(),
                kind: ev.kind,
                text: ev.text,
                live: s.live,
            });
            if out.len() >= 24 {
                return out;
            }
        }
    }
    out
}

pub fn session_detail(id: &str) -> Result<SessionDetail, String> {
    if is_web_id(id) {
        let mut session = find_web_session(id).ok_or_else(|| "web session not in cache".to_string())?;
        crate::pr::apply_to_sessions(std::slice::from_mut(&mut session));
        projects::apply_link(&mut session);
        return Ok(SessionDetail {
            session,
            plan_excerpt: None,
            events: vec![],
        });
    }
    if !is_session_id(id) {
        return Err("invalid session id".into());
    }
    let snap = collect_snapshot();
    let mut session = snap
        .sessions
        .into_iter()
        .find(|s| s.id == id)
        .ok_or_else(|| "session not in snapshot".to_string())?;
    let home = grok_home();
    let disk = resolve_disk(&home, &session);
    if let Some(dir) = disk.as_ref() {
        session.disk_path = Some(dir.display().to_string());
        if let Some(sum) = read_json::<SummaryFile>(&dir.join("summary.json")) {
            apply_summary(&mut session, &sum);
        }
        session.has_plan = dir.join("plan.md").exists() || dir.join("plan.json").exists();
    }
    let plan_excerpt = disk.as_ref().and_then(|d| read_plan_excerpt(d));
    let events = disk
        .as_ref()
        .map(|d| tail_events_memo(&d.join("updates.jsonl"), 48_000, 40))
        .unwrap_or_default();
    Ok(SessionDetail {
        session,
        plan_excerpt,
        events,
    })
}

pub fn resume_blocked_reason(
    id: &str,
    live: &std::collections::HashSet<String>,
) -> Option<&'static str> {
    if is_web_id(id) {
        return Some("web session; use Open in browser");
    }
    if !is_session_id(id) {
        return Some("invalid session id");
    }
    if live.contains(id) {
        return Some("refusing resume inject: live TUI pager. Use the native Grok window.");
    }
    None
}

pub fn resume_in_grok(id: &str) -> Result<String, String> {
    if let Some(reason) = resume_blocked_reason(id, &tui_live_ids()) {
        return Err(reason.into());
    }
    let detail = session_detail(id)?;
    let home = grok_home();
    let bin = grok_bin(&home);
    if !bin.exists() {
        return Err(format!("grok binary missing: {}", bin.display()));
    }
    let mut cmd = std::process::Command::new(&bin);
    cmd.arg("--resume").arg(id);
    if !detail.session.cwd.is_empty() {
        cmd.current_dir(&detail.session.cwd);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x00000010);
    }
    cmd.spawn()
        .map_err(|e| e.to_string())
        .map(|_| format!("resumed {} in new grok window", id))
}

pub fn open_path(path: &str) -> Result<(), String> {
    let p = PathBuf::from(path);
    if !p.exists() {
        return Err(format!("missing path: {path}"));
    }
    #[cfg(windows)]
    {
        std::process::Command::new("explorer")
            .arg(p.as_os_str())
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(());
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&p)
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(());
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        std::process::Command::new("xdg-open")
            .arg(&p)
            .spawn()
            .map_err(|e| e.to_string())?;
        return Ok(());
    }
    #[allow(unreachable_code)]
    Err("open_path unsupported on this OS".into())
}

pub fn open_cwd(id: &str) -> Result<(), String> {
    let d = session_detail(id)?;
    if d.session.cwd.is_empty() {
        return Err("no cwd".into());
    }
    open_path(&d.session.cwd)
}

pub fn open_session_dir(id: &str) -> Result<(), String> {
    let d = session_detail(id)?;
    match d.session.disk_path {
        Some(p) => open_path(&p),
        None => Err("no disk path".into()),
    }
}

fn live_sessions(home: &Path) -> (Vec<Session>, AdapterStatus) {
    let path = home.join("active_sessions.json");
    let raw = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(_) => {
            return (
                vec![],
                AdapterStatus {
                    name: "grok_live".into(),
                    status: if path.exists() { "degraded" } else { "offline" }.into(),
                    detail: "active_sessions.json unreadable".into(),
                },
            );
        }
    };
    let rows: Vec<ActiveRow> = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            return (
                vec![],
                AdapterStatus {
                    name: "grok_live".into(),
                    status: "degraded".into(),
                    detail: format!("parse: {e}"),
                },
            );
        }
    };
    let mut out = Vec::new();
    for row in rows {
        if !is_session_id(&row.session_id) {
            continue;
        }
        let alive = pid_alive(row.pid);
        let disk = session_dir(home, &row.cwd, &row.session_id);
        let mut sess = Session {
            id: row.session_id.clone(),
            source: "grok_build".into(),
            project_id: Some(row.cwd.clone()),
            cwd: row.cwd.clone(),
            title: row.session_id.chars().take(8).collect(),
            summary: String::new(),
            state: if alive { "live_working" } else { "offline" }.into(),
            health: if alive { "ok" } else { "offline" }.into(),
            pid: if alive { Some(row.pid) } else { None },
            model: None,
            agent_name: None,
            created_at: row.opened_at.clone(),
            updated_at: row.opened_at.clone(),
            last_active_at: None,
            disk_path: if disk.exists() {
                Some(disk.display().to_string())
            } else {
                None
            },
            url: None,
            remote: None,
            branch: None,
            pr_url: None,
            pr_state: None,
            pr_files: Vec::new(),
            pr_file_count: None,
            live: alive,
            has_plan: disk.join("plan.md").exists() || disk.join("plan.json").exists(),
        };
        if let Some(sum) = read_json::<SummaryFile>(&disk.join("summary.json")) {
            apply_summary(&mut sess, &sum);
        }
        out.push(sess);
    }
    let n = out.len();
    (
        out,
        AdapterStatus {
            name: "grok_live".into(),
            status: "ok".into(),
            detail: format!("{n} listed"),
        },
    )
}

fn index_sessions(home: &Path, limit: usize) -> (Vec<Session>, AdapterStatus) {
    let db = home.join("sessions").join("session_search.sqlite");
    if !db.exists() {
        return (
            vec![],
            AdapterStatus {
                name: "grok_index".into(),
                status: "offline".into(),
                detail: "session_search.sqlite missing".into(),
            },
        );
    }
    let con = match Connection::open_with_flags(
        &db,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    ) {
        Ok(c) => c,
        Err(e) => {
            return (
                vec![],
                AdapterStatus {
                    name: "grok_index".into(),
                    status: "degraded".into(),
                    detail: e.to_string(),
                },
            );
        }
    };
    let mut stmt = match con.prepare(
        "SELECT session_id, cwd, updated_at, title FROM session_docs ORDER BY updated_at DESC LIMIT ?1",
    ) {
        Ok(s) => s,
        Err(e) => {
            return (
                vec![],
                AdapterStatus {
                    name: "grok_index".into(),
                    status: "degraded".into(),
                    detail: e.to_string(),
                },
            );
        }
    };
    let mut rows = match stmt.query([limit as i64]) {
        Ok(r) => r,
        Err(e) => {
            return (
                vec![],
                AdapterStatus {
                    name: "grok_index".into(),
                    status: "degraded".into(),
                    detail: e.to_string(),
                },
            );
        }
    };
    let mut out = Vec::new();
    loop {
        match rows.next() {
            Ok(Some(row)) => {
                let id: String = row.get(0).unwrap_or_default();
                if !is_session_id(&id) {
                    continue;
                }
                let cwd: String = row.get(1).unwrap_or_default();
                let updated: i64 = row.get(2).unwrap_or(0);
                let title: String = row.get(3).unwrap_or_default();
                out.push(index_row_to_session(id, cwd, updated, title));
            }
            Ok(None) => break,
            Err(e) => {
                return (
                    out,
                    AdapterStatus {
                        name: "grok_index".into(),
                        status: "degraded".into(),
                        detail: e.to_string(),
                    },
                );
            }
        }
    }
    let n = out.len();
    (
        out,
        AdapterStatus {
            name: "grok_index".into(),
            status: "ok".into(),
            detail: format!("{n} recent"),
        },
    )
}

fn index_row_to_session(id: String, cwd: String, updated: i64, title: String) -> Session {
    let ts = unix_to_rfc3339(updated);
    let title = truncate(&redact(&title), 180);
    Session {
        id,
        source: "grok_build".into(),
        project_id: Some(cwd.clone()),
        cwd,
        summary: title.clone(),
        title,
        state: "disk".into(),
        health: "ok".into(),
        pid: None,
        model: None,
        agent_name: None,
        created_at: ts.clone(),
        updated_at: ts.clone(),
        last_active_at: ts,
        disk_path: None,
        url: None,
        remote: None,
        branch: None,
        pr_url: None,
        pr_state: None,
        pr_files: Vec::new(),
        pr_file_count: None,
        live: false,
        has_plan: false,
    }
}

fn desk_attention(home: &Path) -> (Vec<Attention>, AdapterStatus) {
    let dir = home.join("desk").join("claims");
    if !dir.exists() {
        return (
            vec![],
            AdapterStatus {
                name: "desk".into(),
                status: "offline".into(),
                detail: "no desk/claims".into(),
            },
        );
    }
    let mut attention = Vec::new();
    let mut count = 0u32;
    if let Ok(rd) = std::fs::read_dir(&dir) {
        for ent in rd.flatten() {
            let path = ent.path();
            if path.extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&path) else {
                continue;
            };
            let Ok(v) = serde_json::from_str::<Value>(&text) else {
                continue;
            };
            if v.get("status").and_then(|s| s.as_str()) != Some("active") {
                continue;
            }
            count += 1;
            let project = v.get("project").and_then(|s| s.as_str()).unwrap_or("");
            let note = v.get("note").and_then(|s| s.as_str()).unwrap_or("");
            attention.push(Attention {
                id: format!("desk-{}", v.get("id").and_then(|s| s.as_str()).unwrap_or("x")),
                session_id: v
                    .get("session_id")
                    .and_then(|s| s.as_str())
                    .map(|s| s.to_string()),
                source: "grok_build".into(),
                kind: "desk_claim".into(),
                title: redact(&format!("desk claim {project}: {note}")),
                created_at: v
                    .get("claimed_at")
                    .and_then(|s| s.as_str())
                    .map(|s| s.to_string()),
                severity: "info".into(),
            });
        }
    }
    (
        attention,
        AdapterStatus {
            name: "desk".into(),
            status: "ok".into(),
            detail: format!("{count} claims"),
        },
    )
}

fn process_scan(live: &[Session]) -> (Surfaces, AdapterStatus) {
    let mut grok = 0u32;
    let mut bot = 0u32;
    let mut cursor = 0u32;
    let mut cached = false;
    if let Ok(guard) = PROC_MEMO.lock() {
        if let Some((when, g, b, c, _, _)) = guard.as_ref() {
            if when.elapsed() < Duration::from_secs(5) {
                grok = *g;
                bot = *b;
                cursor = *c;
                cached = true;
            }
        }
    }
    if !cached {
        if let Ok(out) = std::process::Command::new("tasklist")
            .args(["/FO", "CSV", "/NH"])
            .output()
        {
            let text = String::from_utf8_lossy(&out.stdout).to_lowercase();
            for line in text.lines() {
                if line.contains("grok bot") {
                    bot += 1;
                } else if line.contains("grok.exe") || line.starts_with("\"grok\"") {
                    grok += 1;
                } else if line.contains("cursor.exe") {
                    cursor += 1;
                }
            }
        }
        if let Ok(mut g) = PROC_MEMO.lock() {
            *g = Some((Instant::now(), grok, bot, cursor, false, None));
        }
    }
    let home = grok_home();
    let exec_alive = local_exec_alive(&grokbot_dir());
    let pack = steward_pack_version(
        &home
            .join("grok-bot")
            .join("01-knock-ops-steward-PROMPT.md"),
    );
    let surfaces = Surfaces {
        grok_bot: bot > 0,
        grok_bot_procs: bot,
        local_exec_alive: exec_alive,
        steward_pack: pack.clone(),
        cursor: cursor > 0,
        live_grok_pids: live.iter().filter_map(|s| s.pid).collect(),
        web_consent: false,
        grok_web: "needs_consent".into(),
        grok_web_detail: None,
        cursor_web: "needs_consent".into(),
        cursor_web_detail: None,
        cursor_web_probed_at: None,
        cursor_pulse: crate::pulse::cursor_pulse_enabled(),
        cook_armed: crate::cook::status().armed,
        cook_detail: crate::cook::status().last_detail,
        cook_summary: crate::cook::status().last_summary,
        cook_staff: crate::cook::status().staff_now,
    };
    let status = if grok > 0 || bot > 0 { "ok" } else { "degraded" };
    (
        surfaces,
        AdapterStatus {
            name: "process".into(),
            status: status.into(),
            detail: format!(
                "grok={grok} bot={bot} cursor={cursor} local-exec={} pack={}",
                if exec_alive { "alive" } else { "dead" },
                pack.as_deref().unwrap_or("?")
            ),
        },
    )
}

fn merge_sessions(live: &mut [Session], indexed: Vec<Session>) -> Vec<Session> {
    let mut by_id: HashMap<String, Session> = HashMap::new();
    for s in indexed {
        by_id.insert(s.id.clone(), s);
    }
    for s in live.iter() {
        if let Some(prev) = by_id.get_mut(&s.id) {
            if prev.title.len() < s.title.len() || s.live {
                prev.title = s.title.clone();
                prev.summary = s.summary.clone();
            }
            prev.live = s.live;
            prev.state = s.state.clone();
            prev.health = s.health.clone();
            prev.pid = s.pid;
            prev.model = s.model.clone();
            prev.agent_name = s.agent_name.clone();
            prev.disk_path = s.disk_path.clone();
            prev.has_plan = s.has_plan || prev.has_plan;
            if s.updated_at.is_some() {
                prev.updated_at = s.updated_at.clone();
            }
        } else {
            by_id.insert(s.id.clone(), s.clone());
        }
    }
    let mut sessions: Vec<Session> = by_id.into_values().collect();
    sessions.sort_by(|a, b| match (a.live, b.live) {
        (true, false) => std::cmp::Ordering::Less,
        (false, true) => std::cmp::Ordering::Greater,
        _ => b.updated_at.cmp(&a.updated_at),
    });
    sessions
}

fn project_name(projects: &[Project], slug: Option<&str>) -> String {
    let id = slug.unwrap_or("");
    projects
        .iter()
        .find(|p| p.id == id)
        .map(|p| p.name.clone())
        .filter(|n| !n.is_empty())
        .unwrap_or_else(|| {
            if id.is_empty() {
                "unknown".into()
            } else {
                id.to_string()
            }
        })
}

pub fn next_hop_clause(sessions: &[Session], attention: &[Attention]) -> Option<String> {
    if let Some(a) = attention.iter().find(|a| a.kind == "stale") {
        return Some(format!("Next: {}", truncate(&a.title, 72)));
    }
    if sessions
        .iter()
        .any(|s| crate::clock::is_stale_live(s))
    {
        let s = sessions.iter().find(|s| crate::clock::is_stale_live(s))?;
        return Some(format!("Next: focus stale pager {}", truncate(&s.title, 56)));
    }
    if let Some(a) = attention.iter().find(|a| a.kind == "running") {
        return Some(format!("Next: {}", truncate(&a.title, 72)));
    }
    if let Some(a) = attention.iter().find(|a| a.kind == "pr_ready") {
        return Some(format!("Next: {}", truncate(&a.title, 72)));
    }
    if let Some(a) = attention.iter().find(|a| a.kind == "desk_claim") {
        return Some(format!("Next: {}", truncate(&a.title, 72)));
    }
    None
}

fn situation_text(
    sessions: &[Session],
    projects: &[Project],
    adapters: &[AdapterStatus],
    surfaces: &Surfaces,
    attention: &[Attention],
) -> String {
    let live: Vec<&Session> = sessions.iter().filter(|s| s.live).collect();
    let mut bits = Vec::new();
    if let Some(hop) = next_hop_clause(sessions, attention) {
        bits.push(hop);
    }
    let cursor_running: Vec<&Session> = sessions
        .iter()
        .filter(|s| {
            (s.source == "cursor_web" || s.id.starts_with("web:cursor:"))
                && s.agent_name.as_deref() == Some("running")
        })
        .collect();
    let stale_live: Vec<&Session> = sessions.iter().filter(|s| crate::clock::is_stale_live(s)).collect();
    if !stale_live.is_empty() {
        bits.push(format!(
            "{} live pager{} quiet >30m ({})",
            stale_live.len(),
            if stale_live.len() == 1 { "" } else { "s" },
            truncate(&stale_live[0].title, 48)
        ));
    }
    if !cursor_running.is_empty() {
        let first = cursor_running[0];
        let well = project_name(projects, first.project_id.as_deref());
        bits.push(format!(
            "{} Cursor agent{} running on {} ({})",
            cursor_running.len(),
            if cursor_running.len() == 1 { "" } else { "s" },
            well,
            truncate(&first.title, 48)
        ));
    }
    let mut pr_keys: Vec<String> = sessions
        .iter()
        .filter(|s| {
            s.source == "cursor_web"
                && s.pr_url.as_deref().map(|u| !u.is_empty()).unwrap_or(false)
                && s.agent_name.as_deref() != Some("running")
                && crate::pr::needs_clearance(s.pr_state.as_deref())
        })
        .map(|s| crate::web::normalize_pr_url(s.pr_url.as_deref().unwrap_or("")))
        .collect();
    pr_keys.sort();
    pr_keys.dedup();
    if !pr_keys.is_empty() {
        let first = sessions
            .iter()
            .find(|s| {
                s.pr_url
                    .as_deref()
                    .map(|u| crate::web::normalize_pr_url(u) == pr_keys[0])
                    .unwrap_or(false)
            })
            .map(|s| s.title.as_str())
            .unwrap_or("untitled");
        bits.push(format!(
            "{} open PR{} ({})",
            pr_keys.len(),
            if pr_keys.len() == 1 { "" } else { "s" },
            truncate(first, 48)
        ));
    }
    if let Some(thread) = projects::thread_clause(sessions, projects, attention) {
        bits.push(thread);
    }
    if live.is_empty() {
        bits.push("No live Grok Build pagers".into());
    } else {
        let mut cwds: Vec<&str> = live.iter().map(|s| s.cwd.as_str()).collect();
        cwds.sort();
        cwds.dedup();
        let titles: Vec<String> = live
            .iter()
            .take(3)
            .map(|s| truncate(&s.title, 48))
            .collect();
        bits.push(format!(
            "{} Grok Build pager{} live on {} ({})",
            live.len(),
            if live.len() == 1 { "" } else { "s" },
            cwds.join(", "),
            titles.join("; ")
        ));
    }
    bits.push(if surfaces.grok_bot {
        format!(
            "Grok Bot desktop is running ({} proc{}, local-exec {}, pack {})",
            surfaces.grok_bot_procs,
            if surfaces.grok_bot_procs == 1 { "" } else { "s" },
            if surfaces.local_exec_alive {
                "alive"
            } else {
                "dead"
            },
            surfaces.steward_pack.as_deref().unwrap_or("?")
        )
    } else {
        "Grok Bot desktop is not running".into()
    });
    bits.push(if surfaces.cursor {
        "Cursor desktop is running".into()
    } else {
        "Cursor desktop is not installed or not running".into()
    });
    let grok_web_n = sessions
        .iter()
        .filter(|s| s.source == "grok_web" || s.id.starts_with("web:grok:"))
        .count();
    bits.push(if grok_web_n > 0 {
        format!("Grok web ok ({grok_web_n} chats in Galaxy)")
    } else {
        format!(
            "Grok web {}{}",
            surfaces.grok_web,
            surfaces
                .grok_web_detail
                .as_deref()
                .filter(|d| !d.is_empty())
                .map(|d| format!(" ({d})"))
                .unwrap_or_default()
        )
    });
    let cursor_web_n = sessions
        .iter()
        .filter(|s| s.source == "cursor_web" || s.id.starts_with("web:cursor:"))
        .count();
    bits.push(if cursor_running.is_empty() && cursor_web_n > 0 {
        format!("Cursor web ok ({cursor_web_n} agents, none running)")
    } else if !cursor_running.is_empty() {
        format!("{cursor_web_n} cursor.com agents listed")
    } else {
        format!(
            "Cursor web {}{}",
            surfaces.cursor_web,
            surfaces
                .cursor_web_detail
                .as_deref()
                .filter(|d| !d.is_empty())
                .map(|d| format!(" ({d})"))
                .unwrap_or_default()
        )
    });
    if let Some(desk) = adapters.iter().find(|a| a.name == "desk") {
        bits.push(format!("Desk: {}", desk.detail));
    }
    bits.push(format!(
        "{} clearance item{}",
        attention.len(),
        if attention.len() == 1 { "" } else { "s" }
    ));
    let down: Vec<&str> = adapters
        .iter()
        .filter(|a| a.status != "ok")
        .map(|a| a.name.as_str())
        .collect();
    if !down.is_empty() {
        bits.push(format!("degraded: {}", down.join(", ")));
    }
    format!("{}.", bits.join(". "))
}

fn apply_summary(sess: &mut Session, sum: &SummaryFile) {
    let fallback = sess.title.clone();
    let title_src = sum
        .generated_title
        .as_deref()
        .or(sum.session_summary.as_deref())
        .unwrap_or(fallback.as_str());
    let summary_src = sum.session_summary.as_deref().unwrap_or(title_src);
    sess.title = truncate(&redact(title_src), 180);
    sess.summary = truncate(&redact(summary_src), 240);
    if let Some(m) = &sum.current_model_id {
        sess.model = Some(m.clone());
    }
    if let Some(a) = &sum.agent_name {
        sess.agent_name = Some(a.clone());
    }
    if sess.cwd.is_empty() {
        if let Some(c) = sum.info.as_ref().and_then(|i| i.cwd.clone()) {
            sess.cwd = c;
        }
    }
    sess.created_at = sum.created_at.clone().or(sess.created_at.clone());
    sess.updated_at = sum.updated_at.clone().or(sess.updated_at.clone());
    sess.last_active_at = sum.last_active_at.clone();
}

fn resolve_disk(home: &Path, session: &Session) -> Option<PathBuf> {
    if let Some(p) = &session.disk_path {
        let pb = PathBuf::from(p);
        if pb.is_dir() {
            return Some(pb);
        }
    }
    if !session.cwd.is_empty() {
        let p = session_dir(home, &session.cwd, &session.id);
        if p.is_dir() {
            return Some(p);
        }
    }
    // last resort: scan cwd groups only (not every session id)
    let root = home.join("sessions");
    if let Ok(rd) = std::fs::read_dir(root) {
        for ent in rd.flatten() {
            let child = ent.path().join(&session.id);
            if child.is_dir() {
                return Some(child);
            }
        }
    }
    None
}

fn read_plan_excerpt(dir: &Path) -> Option<String> {
    for name in ["plan.md", "plan.json"] {
        let p = dir.join(name);
        if let Ok(text) = std::fs::read_to_string(p) {
            return Some(truncate(&redact(&text), 4000));
        }
    }
    None
}

fn tail_events_memo(path: &Path, bytes: u64, limit: usize) -> Vec<SessionEvent> {
    let key = path.to_string_lossy().to_string();
    let mt = file_mtime_ms(path);
    if let Ok(guard) = TAIL_MEMO.lock() {
        if let Some(map) = guard.as_ref() {
            if let Some(hit) = map.get(&key) {
                if hit.mtime == mt {
                    return hit.events.clone();
                }
            }
        }
    }
    let events = tail_events(path, bytes, limit);
    if let Ok(mut guard) = TAIL_MEMO.lock() {
        let map = guard.get_or_insert_with(HashMap::new);
        if map.len() > 64 {
            map.clear();
        }
        map.insert(
            key,
            TailMemo {
                mtime: mt,
                events: events.clone(),
            },
        );
    }
    events
}

fn tail_events(path: &Path, bytes: u64, limit: usize) -> Vec<SessionEvent> {
    let mut file = match std::fs::File::open(path) {
        Ok(f) => f,
        Err(_) => return vec![],
    };
    let len = file.metadata().map(|m| m.len()).unwrap_or(0);
    let start = len.saturating_sub(bytes);
    if file.seek(SeekFrom::Start(start)).is_err() {
        return vec![];
    }
    let mut buf = String::new();
    if file.read_to_string(&mut buf).is_err() {
        return vec![];
    }
    let text = if start > 0 {
        buf.split_once('\n').map(|(_, r)| r).unwrap_or(&buf)
    } else {
        buf.as_str()
    };
    let mut events = Vec::new();
    for line in text.lines() {
        let Ok(v) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if let Some(ev) = event_from_update(&v) {
            events.push(ev);
        }
    }
    if events.len() > limit {
        events = events.split_off(events.len() - limit);
    }
    events
}

fn event_from_update(v: &Value) -> Option<SessionEvent> {
    let update = v.pointer("/params/update")?;
    let kind = update
        .get("sessionUpdate")
        .and_then(|s| s.as_str())
        .unwrap_or("update");
    let text = match kind {
        "user_message_chunk" | "agent_message_chunk" | "agent_thought_chunk" => update
            .pointer("/content/text")
            .and_then(|s| s.as_str())
            .unwrap_or("")
            .to_string(),
        "tool_call" | "tool_call_update" => update
            .get("title")
            .and_then(|s| s.as_str())
            .unwrap_or(kind)
            .to_string(),
        "plan" => "plan update".into(),
        _ => kind.to_string(),
    };
    let text = redact(text.trim());
    if text.is_empty() {
        return None;
    }
    Some(SessionEvent {
        kind: kind.to_string(),
        text: truncate(&text, 400),
    })
}

fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> Option<T> {
    let text = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

pub(crate) fn sanitize_fts(q: &str) -> String {
    let cleaned: String = q
        .chars()
        .map(|c| if c.is_alphanumeric() || c == ' ' { c } else { ' ' })
        .collect();
    let parts: Vec<String> = cleaned
        .split_whitespace()
        .map(|w| format!("{w}*"))
        .collect();
    if parts.is_empty() {
        "session".into()
    } else {
        parts.join(" ")
    }
}

fn pid_alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    #[cfg(windows)]
    {
        const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
        extern "system" {
            fn OpenProcess(access: u32, inherit: i32, pid: u32) -> isize;
            fn CloseHandle(handle: isize) -> i32;
        }
        unsafe {
            let h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if h != 0 {
                CloseHandle(h);
                return true;
            }
        }
        return false;
    }
    #[cfg(unix)]
    {
        unsafe { libc_kill(pid as i32) }
    }
    #[cfg(not(any(windows, unix)))]
    {
        let _ = pid;
        false
    }
}

#[cfg(unix)]
fn libc_kill(pid: i32) -> bool {
    extern "C" {
        fn kill(pid: i32, sig: i32) -> i32;
    }
    unsafe { kill(pid, 0) == 0 }
}

fn now_rfc3339() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    unix_to_rfc3339(secs as i64).unwrap_or_else(|| "1970-01-01T00:00:00Z".into())
}

fn unix_to_rfc3339(secs: i64) -> Option<String> {
    if secs <= 0 {
        return None;
    }
    // enough for display; avoid chrono dep
    let s = secs;
    let days = s.div_euclid(86400);
    let rem = s.rem_euclid(86400);
    let hour = rem / 3600;
    let min = (rem % 3600) / 60;
    let sec = rem % 60;
    let (y, m, d) = civil_from_days(days);
    Some(format!(
        " {y:04}-{m:02}-{d:02}T{hour:02}:{min:02}:{sec:02}Z"
    )
    .trim()
    .to_string())
}

fn civil_from_days(z: i64) -> (i32, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    (y as i32, m as u32, d as u32)
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let t: String = s.chars().take(max.saturating_sub(1)).collect();
        format!("{t}...")
    }
}

struct InstantLike {
    start: SystemTime,
}

impl InstantLike {
    fn now() -> Self {
        Self {
            start: SystemTime::now(),
        }
    }
    fn elapsed_ms(&self) -> u64 {
        SystemTime::now()
            .duration_since(self.start)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0)
    }
}

#[allow(dead_code)]
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_has_situation() {
        let snap = collect_snapshot_ex(true);
        assert!(!snap.situation.is_empty());
        assert!(snap.elapsed_ms < 10_000);
        assert!(snap.adapters.iter().any(|a| a.name == "grok_live"));
        assert!(snap.adapters.iter().any(|a| a.name == "web"));
        assert!(!snap.surfaces.grok_web.is_empty());
        let _ = &snap.activity;
        assert!(snap.snap_profile.as_deref().unwrap_or("").contains("live="));
        let cached = collect_snapshot();
        assert_eq!(cached.elapsed_ms, 0);
        assert_eq!(cached.situation, snap.situation);
        assert_eq!(cached.snap_profile.as_deref(), Some("cache"));
    }

    #[test]
    fn next_hop_prefers_stale_attention() {
        let att = vec![Attention {
            id: "stale-1".into(),
            session_id: Some("a".into()),
            source: "grok_build".into(),
            kind: "stale".into(),
            title: "Live pager quiet 45m: Night Range".into(),
            created_at: None,
            severity: "warn".into(),
        }];
        let hop = next_hop_clause(&[], &att).expect("hop");
        assert!(hop.starts_with("Next:"), "{hop}");
        assert!(hop.contains("Night Range"), "{hop}");
    }

    #[test]
    fn tail_memo_reuses_unchanged_mtime() {
        let dir = std::env::temp_dir().join(format!("orbit-tail-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("updates.jsonl");
        std::fs::write(
            &path,
            "{\"params\":{\"update\":{\"sessionUpdate\":\"plan\"}}}\n",
        )
        .unwrap();
        let first = tail_events_memo(&path, 24_000, 6);
        let second = tail_events_memo(&path, 24_000, 6);
        assert_eq!(first.len(), second.len());
        assert_eq!(first[0].kind, "plan");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn fts_query_is_prefix_tokens() {
        assert_eq!(sanitize_fts("orbit feed!"), "orbit* feed*");
        assert_eq!(sanitize_fts("   "), "session");
    }

    #[test]
    fn resume_refuses_live_tui_and_web() {
        let mut live = std::collections::HashSet::new();
        live.insert("01a00022-b643-7b40-9d7e-dc185c67e3c2".into());
        let blocked = resume_blocked_reason("01a00022-b643-7b40-9d7e-dc185c67e3c2", &live)
            .expect("live resume must refuse");
        assert!(blocked.contains("live TUI"), "{blocked}");
        let web = resume_blocked_reason(
            "web:cursor:bc-00000000-0000-0000-0000-000000000001",
            &live,
        )
        .expect("web resume must refuse");
        assert!(web.contains("web session"), "{web}");
        assert_eq!(
            resume_blocked_reason("../auth.json", &live),
            Some("invalid session id")
        );
        assert_eq!(
            resume_blocked_reason("01a00000-0000-7000-8000-000000000099", &live),
            None
        );
    }

    #[test]
    fn search_returns_hits_or_empty() {
        let hits = search_sessions("orbit").expect("search");
        for h in hits {
            assert!(is_session_id(&h.id));
            assert!(!h.title.is_empty() || !h.snippet.is_empty());
        }
    }
}
