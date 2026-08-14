use std::path::{Path, PathBuf};

pub fn grok_home() -> PathBuf {
    if let Ok(raw) = std::env::var("GROK_HOME") {
        if !raw.is_empty() {
            return PathBuf::from(raw);
        }
    }
    dirs_home().join(".grok")
}

fn dirs_home() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

pub fn encode_cwd(cwd: &str) -> String {
    urlencoding::encode(cwd).into_owned()
}

pub fn session_dir(home: &Path, cwd: &str, id: &str) -> PathBuf {
    home.join("sessions").join(encode_cwd(cwd)).join(id)
}

pub fn grokbot_dir() -> PathBuf {
    dirs_home().join(".grokbot")
}

pub fn orbit_tree() -> PathBuf {
    dirs_home().join("grok-orbit")
}

pub fn orbit_data_home() -> PathBuf {
    if let Ok(raw) = std::env::var("ORBIT_DATA_HOME") {
        if !raw.is_empty() {
            return PathBuf::from(raw);
        }
    }
    std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(dirs_home)
        .join("com.knock.grokorbit")
}

pub fn orbit_web_home() -> PathBuf {
    if let Ok(raw) = std::env::var("ORBIT_WEB_HOME") {
        if !raw.is_empty() {
            return PathBuf::from(raw);
        }
    }
    orbit_data_home().join("web")
}

pub fn orbit_db_path() -> PathBuf {
    orbit_data_home().join("orbit.db")
}

pub fn grok_bin(home: &Path) -> PathBuf {
    if cfg!(windows) {
        home.join("bin").join("grok.exe")
    } else {
        home.join("bin").join("grok")
    }
}

#[allow(dead_code)]
pub fn find_session_dir(home: &Path, id: &str) -> Option<PathBuf> {
    let root = home.join("sessions");
    let entries = std::fs::read_dir(root).ok()?;
    for ent in entries.flatten() {
        let child = ent.path().join(id);
        if child.is_dir() {
            return Some(child);
        }
    }
    None
}
