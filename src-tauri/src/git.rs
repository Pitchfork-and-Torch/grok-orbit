//! Star-only git porcelain. Never runs on the Galaxy 2s poll.

use crate::model::Session;
use crate::projects;
use crate::redact::redact;
use crate::snapshot::collect_snapshot;
use crate::web::{find_web_session, is_web_id};
use serde::Serialize;
use std::path::Path;
use std::process::Command;
use std::sync::Mutex;
use std::time::{Duration, Instant};

const MEMO_SECS: u64 = 10;

#[derive(Debug, Clone, Serialize)]
pub struct GitPulse {
    pub cwd: String,
    pub branch: Option<String>,
    pub dirty: u32,
    pub lines: Vec<String>,
}

struct GitMemo {
    key: String,
    when: Instant,
    pulse: GitPulse,
}

static GIT_MEMO: Mutex<Option<GitMemo>> = Mutex::new(None);

pub fn parse_porcelain(raw: &str) -> (u32, Vec<String>) {
    let mut lines = Vec::new();
    for line in raw.lines() {
        let t = line.trim_end();
        if t.is_empty() {
            continue;
        }
        lines.push(redact(t));
        if lines.len() >= 12 {
            break;
        }
    }
    let dirty = raw.lines().filter(|l| !l.trim().is_empty()).count() as u32;
    (dirty, lines)
}

fn git_out(cwd: &Path, args: &[&str]) -> Option<String> {
    let mut cmd = Command::new("git");
    cmd.args(args).current_dir(cwd);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }
    let out = cmd.output().ok()?;
    if !out.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&out.stdout).to_string())
}

fn resolve_session(id: &str) -> Result<Session, String> {
    if is_web_id(id) {
        let mut s = find_web_session(id).ok_or_else(|| "web session not in cache".to_string())?;
        projects::apply_link(&mut s);
        return Ok(s);
    }
    collect_snapshot()
        .sessions
        .into_iter()
        .find(|s| s.id == id)
        .ok_or_else(|| "session not in snapshot".to_string())
}

pub fn star_git_status(id: &str) -> Result<GitPulse, String> {
    let session = resolve_session(id)?;
    let cwd = projects::clone_path_for(&session).unwrap_or_else(|| session.cwd.clone());
    if cwd.is_empty() || !Path::new(&cwd).is_dir() {
        return Err("no git cwd for this star".into());
    }
    if let Ok(guard) = GIT_MEMO.lock() {
        if let Some(memo) = guard.as_ref() {
            if memo.key == cwd && memo.when.elapsed() < Duration::from_secs(MEMO_SECS) {
                return Ok(memo.pulse.clone());
            }
        }
    }
    let branch = git_out(Path::new(&cwd), &["rev-parse", "--abbrev-ref", "HEAD"])
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    let raw = git_out(Path::new(&cwd), &["status", "--porcelain"]).unwrap_or_default();
    let (dirty, lines) = parse_porcelain(&raw);
    let pulse = GitPulse {
        cwd,
        branch,
        dirty,
        lines,
    };
    if let Ok(mut guard) = GIT_MEMO.lock() {
        *guard = Some(GitMemo {
            key: pulse.cwd.clone(),
            when: Instant::now(),
            pulse: pulse.clone(),
        });
    }
    Ok(pulse)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn porcelain_counts_and_redacts() {
        let (n, lines) = parse_porcelain(" M src/a.rs\n?? notes.txt\n\n");
        assert_eq!(n, 2);
        assert_eq!(lines.len(), 2);
        let dirty = "token ghp_exampleplaceholder000000 x";
        let (_, red) = parse_porcelain(dirty);
        assert!(!red.join(" ").contains("ghp_"));
    }
}
