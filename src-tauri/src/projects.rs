//! Phase 7 Gravity linker. Deterministic. No LLM. No network.

use crate::model::{Project, Session};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Mutex, OnceLock};
use std::time::UNIX_EPOCH;

static GIT_MEMO: OnceLock<Mutex<HashMap<String, (u64, String)>>> = OnceLock::new();

pub const LOOSE: &str = "loose";
pub const GROK_WEB: &str = "grok.com";
pub const CURSOR_WEB: &str = "cursor.com";

struct Spec {
    id: &'static str,
    name: &'static str,
    rel_paths: &'static [&'static str],
    keywords: &'static [&'static str],
    remotes: &'static [&'static str],
}

const CATALOG: &[Spec] = &[
    Spec {
        id: "vela",
        name: "VELA",
        rel_paths: &["vela"],
        keywords: &["vela", "interval n", "compose cuts"],
        remotes: &["github.com/pitchfork-and-torch/vela"],
    },
    Spec {
        id: "leoaware",
        name: "LeoAware",
        rel_paths: &[
            "Projects/leo-aware-transport",
            "leo-aware-transport",
            "LeoAware",
        ],
        keywords: &["leoaware", "leo-aware", "leocc", "leocc_v1", "dual-gate"],
        remotes: &[],
    },
    Spec {
        id: "instar",
        name: "INSTAR",
        rel_paths: &["instar", "INSTAR"],
        keywords: &["instar", "page 56", "liber primus"],
        remotes: &["github.com/pitchfork-and-torch/instar"],
    },
    Spec {
        id: "ghost",
        name: "Ghost",
        rel_paths: &["ghost-continuum", ".ghost-continuum", ".ghost-lan"],
        keywords: &["ghost continuum", "ghost-lan"],
        remotes: &["github.com/pitchfork-and-torch/ghost-continuum"],
    },
    Spec {
        id: "grok-orbit",
        name: "Grok Orbit",
        rel_paths: &["grok-orbit"],
        keywords: &["grok orbit", "grok-orbit"],
        remotes: &[],
    },
    Spec {
        id: "orbitstack",
        name: "orbitstack",
        rel_paths: &["orbitstack"],
        keywords: &["orbitstack"],
        remotes: &[],
    },
];

#[derive(Clone)]
struct Well {
    id: String,
    name: String,
    paths: Vec<String>,
    remotes: Vec<String>,
    keywords: Vec<String>,
}

#[derive(serde::Deserialize)]
struct ExtraFile {
    #[serde(default)]
    wells: Vec<ExtraSpec>,
}

#[derive(serde::Deserialize)]
struct ExtraSpec {
    id: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    rel_paths: Vec<String>,
    #[serde(default)]
    keywords: Vec<String>,
    #[serde(default)]
    remotes: Vec<String>,
}

fn extra_wells_path(home: &Path) -> PathBuf {
    if let Ok(p) = std::env::var("GROK_ORBIT_WELLS") {
        let t = p.trim();
        if !t.is_empty() {
            return PathBuf::from(t);
        }
    }
    home.join(".grok-orbit").join("wells.json")
}

fn load_extra_specs(home: &Path) -> Vec<ExtraSpec> {
    let path = extra_wells_path(home);
    let raw = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };
    serde_json::from_str::<ExtraFile>(&raw)
        .map(|f| {
            f.wells
                .into_iter()
                .filter(|w| !w.id.trim().is_empty())
                .collect()
        })
        .unwrap_or_default()
}

fn user_home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

pub fn normalize_remote(url: &str) -> String {
    let mut raw = url.trim().replace('\\', "/");
    if raw.is_empty() {
        return String::new();
    }
    if let Some(rest) = raw.strip_prefix("git@") {
        if let Some((host, path)) = rest.split_once(':') {
            raw = format!("https://{host}/{path}");
        }
    }
    if let Some(rest) = raw.strip_prefix("ssh://git@") {
        raw = format!("https://{rest}");
    }
    let raw = raw
        .replacen("https://", "", 1)
        .replacen("http://", "", 1);
    let raw = raw.split('?').next().unwrap_or(&raw);
    let raw = raw.split('#').next().unwrap_or(raw);
    let raw = raw.trim_end_matches('/');
    let raw = raw.strip_suffix(".git").unwrap_or(raw);
    raw.to_ascii_lowercase()
}

fn file_mtime_ms(path: &Path) -> u64 {
    path.metadata()
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn git_sig(path: &Path) -> u64 {
    let git = path.join(".git");
    file_mtime_ms(&git.join("HEAD")).max(file_mtime_ms(&git.join("config")))
}

fn git_remote(path: &Path) -> String {
    if !path.join(".git").exists() {
        return String::new();
    }
    let key = path.to_string_lossy().to_string();
    let sig = git_sig(path);
    let memo = GIT_MEMO.get_or_init(|| Mutex::new(HashMap::new()));
    if let Ok(map) = memo.lock() {
        if let Some((old, remote)) = map.get(&key) {
            if *old == sig {
                return remote.clone();
            }
        }
    }
    let out = Command::new("git")
        .args(["-C", &path.to_string_lossy(), "remote", "get-url", "origin"])
        .output();
    let remote = match out {
        Ok(o) if o.status.success() => {
            normalize_remote(&String::from_utf8_lossy(&o.stdout))
        }
        _ => String::new(),
    };
    if let Ok(mut map) = memo.lock() {
        map.insert(key, (sig, remote.clone()));
    }
    remote
}

fn looks_like_path(cwd: &str) -> bool {
    if cwd.is_empty() {
        return false;
    }
    let p = Path::new(cwd);
    if p.is_absolute() {
        return true;
    }
    let b = cwd.as_bytes();
    b.len() >= 3 && b[1] == b':' && b[0].is_ascii_alphabetic()
}

fn norm_path(path: &str) -> String {
    Path::new(path)
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(path))
        .to_string_lossy()
        .replace('\\', "/")
        .to_ascii_lowercase()
}

fn path_under(cwd: &str, root: &str) -> bool {
    if !looks_like_path(cwd) || root.is_empty() {
        return false;
    }
    let c = norm_path(cwd);
    let r = norm_path(root);
    c == r || c.starts_with(&(r.trim_end_matches('/').to_string() + "/"))
}

pub fn contains_kw(text: &str, kw: &str) -> bool {
    if kw.is_empty() {
        return false;
    }
    let hay = format!(
        " {} ",
        text.to_ascii_lowercase()
            .replace('_', " ")
            .replace('-', " ")
    );
    let needle = format!(
        " {} ",
        kw.to_ascii_lowercase()
            .replace('_', " ")
            .replace('-', " ")
    );
    hay.contains(&needle)
}

fn build_catalog(home: &Path) -> Vec<Well> {
    let mut out = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for spec in CATALOG {
        if !seen.insert(spec.id.to_string()) {
            continue;
        }
        out.push(well_from_parts(
            home,
            spec.id,
            spec.name,
            spec.rel_paths,
            spec.keywords,
            spec.remotes,
        ));
    }
    for spec in load_extra_specs(home) {
        if !seen.insert(spec.id.clone()) {
            continue;
        }
        let name = if spec.name.trim().is_empty() {
            spec.id.clone()
        } else {
            spec.name.clone()
        };
        let rel: Vec<&str> = spec.rel_paths.iter().map(|s| s.as_str()).collect();
        let kws: Vec<&str> = spec.keywords.iter().map(|s| s.as_str()).collect();
        let rems: Vec<&str> = spec.remotes.iter().map(|s| s.as_str()).collect();
        out.push(well_from_parts(
            home,
            &spec.id,
            &name,
            &rel,
            &kws,
            &rems,
        ));
    }
    out
}

fn well_from_parts(
    home: &Path,
    id: &str,
    name: &str,
    rel_paths: &[&str],
    keywords: &[&str],
    remotes_in: &[&str],
) -> Well {
    let mut paths = Vec::new();
    let mut remotes: Vec<String> = remotes_in
        .iter()
        .map(|r| normalize_remote(r))
        .filter(|r| !r.is_empty())
        .collect();
    for rel in rel_paths {
        let p = home.join(rel);
        if p.is_dir() {
            let s = p.to_string_lossy().to_string();
            let remote = git_remote(&p);
            if !remote.is_empty() && !remotes.contains(&remote) {
                remotes.push(remote);
            }
            paths.push(s);
        }
    }
    remotes.sort();
    remotes.dedup();
    Well {
        id: id.to_string(),
        name: name.to_string(),
        paths,
        remotes,
        keywords: keywords.iter().map(|s| s.to_string()).collect(),
    }
}

fn assign_slug(session: &Session, catalog: &[Well]) -> String {
    let cwd = session.cwd.as_str();
    let mut remote = session
        .remote
        .as_deref()
        .map(normalize_remote)
        .unwrap_or_default();
    if remote.is_empty() && looks_like_path(cwd) && Path::new(cwd).is_dir() {
        remote = git_remote(Path::new(cwd));
    }
    if !remote.is_empty() {
        for spec in catalog {
            if spec.remotes.iter().any(|r| r == &remote) {
                return spec.id.clone();
            }
        }
    }
    if !cwd.is_empty() {
        for spec in catalog {
            if spec.paths.iter().any(|root| path_under(cwd, root)) {
                return spec.id.clone();
            }
        }
    }
    let blob = format!(
        "{} {} {} {}",
        session.title,
        session.url.as_deref().unwrap_or(""),
        session.summary,
        cwd
    );
    for spec in catalog {
        if spec
            .keywords
            .iter()
            .any(|kw| contains_kw(&blob, kw))
        {
            return spec.id.clone();
        }
    }
    if session.source == "grok_web" || session.id.starts_with("web:grok:") {
        return GROK_WEB.to_string();
    }
    if session.source == "cursor_web" || session.id.starts_with("web:cursor:") {
        return CURSOR_WEB.to_string();
    }
    LOOSE.to_string()
}

pub fn clone_path_for(session: &Session) -> Option<String> {
    let cwd = session.cwd.as_str();
    if looks_like_path(cwd) && Path::new(cwd).is_dir() {
        return Some(cwd.to_string());
    }
    let catalog = build_catalog(&user_home());
    let mut slug = session.project_id.clone().unwrap_or_default();
    if slug.is_empty() || slug == LOOSE || slug == GROK_WEB || slug == CURSOR_WEB {
        slug = assign_slug(session, &catalog);
    }
    catalog.iter().find(|w| w.id == slug).and_then(|w| {
        w.paths
            .iter()
            .find(|p| Path::new(p).is_dir())
            .cloned()
    })
}

pub fn apply_link(session: &mut Session) {
    let catalog = build_catalog(&user_home());
    let slug = assign_slug(session, &catalog);
    if let Some(spec) = catalog.iter().find(|w| w.id == slug) {
        if session.remote.is_none() {
            if let Some(r) = spec.remotes.first() {
                session.remote = Some(r.clone());
            }
        }
    }
    session.project_id = Some(slug);
}

pub fn link_sessions(sessions: &mut [Session]) -> Vec<Project> {
    let catalog = build_catalog(&user_home());
    let by_id: HashMap<String, Well> = catalog
        .iter()
        .map(|w| (w.id.clone(), w.clone()))
        .collect();
    for s in sessions.iter_mut() {
        let slug = assign_slug(s, &catalog);
        if let Some(spec) = by_id.get(&slug) {
            if s.remote.is_none() {
                if let Some(r) = spec.remotes.first() {
                    s.remote = Some(r.clone());
                }
            }
        }
        s.project_id = Some(slug);
    }

    let mut groups: HashMap<String, Project> = HashMap::new();
    for s in sessions.iter() {
        let slug = s.project_id.clone().unwrap_or_else(|| LOOSE.to_string());
        let spec = by_id.get(&slug);
        let g = groups.entry(slug.clone()).or_insert_with(|| Project {
            id: slug.clone(),
            name: spec
                .map(|w| w.name.clone())
                .unwrap_or_else(|| leftover_name(&slug)),
            paths: spec.map(|w| w.paths.clone()).unwrap_or_default(),
            remotes: spec.map(|w| w.remotes.clone()).unwrap_or_default(),
            tags: vec![],
            session_ids: vec![],
            live_count: 0,
            running_count: 0,
            health: "ok".into(),
            updated_at: s.updated_at.clone(),
        });
        g.session_ids.push(s.id.clone());
        if s.live {
            g.live_count += 1;
        }
        if s.agent_name.as_deref() == Some("running") {
            g.running_count += 1;
        }
        if s.agent_name.as_deref() == Some("error") || s.state == "needs_input" {
            g.health = "error".into();
        } else if g.health != "error" && (s.live || s.agent_name.as_deref() == Some("running"))
        {
            g.health = "attention".into();
        }
    }
    let mut projects: Vec<Project> = groups.into_values().collect();
    projects.sort_by(|a, b| {
        b.running_count
            .cmp(&a.running_count)
            .then(b.live_count.cmp(&a.live_count))
            .then(leftover_rank(&a.id).cmp(&leftover_rank(&b.id)))
            .then(a.name.to_ascii_lowercase().cmp(&b.name.to_ascii_lowercase()))
    });
    projects
}

pub fn is_named_well(id: &str) -> bool {
    !id.is_empty() && id != LOOSE && id != GROK_WEB && id != CURSOR_WEB
}

/// Named well clones only. No git remote. Cheap enough for the 2s cook poll.
pub fn named_clone_roots() -> Vec<(String, String, PathBuf)> {
    let home = user_home();
    let mut out = Vec::new();
    for spec in CATALOG {
        if !is_named_well(spec.id) {
            continue;
        }
        for rel in spec.rel_paths {
            let p = home.join(rel);
            if p.is_dir() {
                out.push((spec.id.to_string(), spec.name.to_string(), p));
                break;
            }
        }
    }
    out
}

pub fn member_kind(session: &Session) -> &'static str {
    if session.live {
        "live pager"
    } else if session.source == "cursor_web" || session.id.starts_with("web:cursor:") {
        match session.pr_state.as_deref() {
            Some("draft") => "Cursor draft",
            Some("open") => "Cursor PR",
            _ => "Cursor",
        }
    } else if session.source == "grok_web" || session.id.starts_with("web:grok:") {
        "grok.com"
    } else {
        "Grok disk"
    }
}

pub fn thread_clause(
    sessions: &[Session],
    projects: &[Project],
    attention: &[crate::model::Attention],
) -> Option<String> {
    for project in projects {
        if !is_named_well(&project.id) {
            continue;
        }
        let mut kinds: Vec<&str> = Vec::new();
        for session in sessions
            .iter()
            .filter(|s| s.project_id.as_deref() == Some(project.id.as_str()))
        {
            let kind = member_kind(session);
            if !kinds.contains(&kind) {
                kinds.push(kind);
            }
        }
        let desk_hit = attention.iter().any(|a| {
            a.kind == "desk_claim"
                && a.title
                    .to_ascii_lowercase()
                    .contains(&format!("claim {}", project.id))
        });
        if desk_hit && !kinds.contains(&"desk") {
            kinds.push("desk");
        }
        if kinds.len() >= 2 {
            return Some(format!("{} spans {}", project.name, kinds.join(" + ")));
        }
    }
    None
}

fn leftover_name(id: &str) -> String {
    match id {
        GROK_WEB => "grok.com".into(),
        CURSOR_WEB => "cursor.com".into(),
        LOOSE => "(loose)".into(),
        other => other.to_string(),
    }
}

fn leftover_rank(id: &str) -> u8 {
    match id {
        LOOSE | GROK_WEB | CURSOR_WEB => 1,
        _ => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sess(id: &str, cwd: &str, title: &str, source: &str) -> Session {
        Session {
            id: id.into(),
            source: source.into(),
            project_id: None,
            cwd: cwd.into(),
            title: title.into(),
            summary: String::new(),
            state: "disk".into(),
            health: "ok".into(),
            pid: None,
            model: None,
            agent_name: None,
            created_at: None,
            updated_at: None,
            last_active_at: None,
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

    #[test]
    fn remotes_normalize() {
        assert_eq!(
            normalize_remote("https://github.com/Pitchfork-and-Torch/vela.git"),
            "github.com/pitchfork-and-torch/vela"
        );
        assert_eq!(
            normalize_remote("git@github.com:Pitchfork-and-Torch/instar.git"),
            "github.com/pitchfork-and-torch/instar"
        );
    }

    #[test]
    fn keywords_group_cursor_titles() {
        let home = user_home();
        let cat = build_catalog(&home);
        let v = sess(
            "web:cursor:1",
            "cursor.com",
            "VELA interval n",
            "cursor_web",
        );
        assert_eq!(assign_slug(&v, &cat), "vela");
        let l = sess(
            "web:cursor:2",
            "cursor.com",
            "v3.14 D/600 reclaim on leocc_v1",
            "cursor_web",
        );
        assert_eq!(assign_slug(&l, &cat), "leoaware");
        let g = sess(
            "web:cursor:3",
            "cursor.com",
            "Restore Ghost continuum overlay",
            "cursor_web",
        );
        assert_eq!(assign_slug(&g, &cat), "ghost");
        let loose = sess("x", r"C:\Users\dev", "Continue Previous", "grok_build");
        assert_eq!(assign_slug(&loose, &cat), LOOSE);
    }

    #[test]
    fn extra_wells_file_appends() {
        let dir = std::env::temp_dir().join(format!("orbit-wells-{}", std::process::id()));
        let well_dir = dir.join(".grok-orbit");
        std::fs::create_dir_all(&well_dir).unwrap();
        std::fs::write(
            well_dir.join("wells.json"),
            r#"{"wells":[{"id":"localwell","name":"Local Well","rel_paths":[],"keywords":["localwell-token"]}]}"#,
        )
        .unwrap();
        let cat = build_catalog(&dir);
        assert!(cat.iter().any(|w| w.id == "localwell"));
        let s = sess(
            "t",
            "cursor.com",
            "please localwell-token now",
            "cursor_web",
        );
        assert_eq!(assign_slug(&s, &cat), "localwell");
    }

    #[test]
    fn relative_web_cwd_is_not_orbit_tree() {
        let home = user_home();
        let cat = build_catalog(&home);
        let s = sess("web:grok:abc", "grok.com", "Night Range", "grok_web");
        assert_eq!(assign_slug(&s, &cat), GROK_WEB);
    }

    #[test]
    fn cursor_title_resolves_leoaware_clone_when_present() {
        let s = sess(
            "web:cursor:run",
            "cursor.com",
            "v3.14 D/600 reclaim on leocc_v1",
            "cursor_web",
        );
        if let Some(path) = clone_path_for(&s) {
            let low = path.to_ascii_lowercase();
            assert!(low.contains("leo") || low.contains("aware"), "{path}");
        }
    }

    #[test]
    fn thread_clause_names_multi_surface_well() {
        let mut pager = sess("live-1", r"C:\Users\dev\vela", "VELA pager", "grok_build");
        pager.project_id = Some("vela".into());
        pager.live = true;
        let mut cursor = sess("web:cursor:v", "cursor.com", "VELA land", "cursor_web");
        cursor.project_id = Some("vela".into());
        cursor.pr_state = Some("draft".into());
        let projects = vec![Project {
            id: "vela".into(),
            name: "VELA".into(),
            paths: vec![],
            remotes: vec![],
            tags: vec![],
            session_ids: vec!["live-1".into(), "web:cursor:v".into()],
            live_count: 1,
            running_count: 0,
            health: "ok".into(),
            updated_at: None,
        }];
        let clause = thread_clause(&[pager, cursor], &projects, &[]);
        let text = clause.expect("thread");
        assert!(text.contains("VELA spans"), "{text}");
        assert!(text.contains("live pager"), "{text}");
        assert!(text.contains("Cursor"), "{text}");
        assert!(!is_named_well(LOOSE));
        assert!(is_named_well("vela"));
    }

    #[test]
    fn named_clone_roots_skip_leftover_wells() {
        let roots = named_clone_roots();
        assert!(roots.iter().all(|(id, _, _)| is_named_well(id)));
        assert!(roots.iter().all(|(_, _, p)| p.is_dir()));
        let ids: Vec<&str> = roots.iter().map(|(id, _, _)| id.as_str()).collect();
        assert!(!ids.contains(&LOOSE));
        assert!(!ids.contains(&GROK_WEB));
        assert!(!ids.contains(&CURSOR_WEB));
        if user_home().join("grok-orbit").is_dir() {
            assert!(ids.contains(&"grok-orbit"));
        }
    }
}
