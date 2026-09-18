//! Non-secret Grok Bot surface. Never open token/key files.

use serde_json::Value;
use std::path::Path;

#[allow(dead_code)]
const TOKEN_NAME_MARKERS: &[&str] = &[
    "token",
    "secret",
    "credential",
    "api-key",
    "apikey",
    "pat",
    ".env",
];

pub fn local_exec_alive(grokbot_dir: &Path) -> bool {
    let path = grokbot_dir.join("local-exec-daemon.json");
    let Ok(text) = std::fs::read_to_string(&path) else {
        return false;
    };
    let Ok(v) = serde_json::from_str::<Value>(&text) else {
        return false;
    };
    let pid = v.get("pid").and_then(|p| p.as_u64()).unwrap_or(0) as u32;
    pid_alive(pid)
}

pub fn steward_pack_version(prompt_path: &Path) -> Option<String> {
    let text = std::fs::read_to_string(prompt_path).ok()?;
    for line in text.lines().take(12) {
        let lower = line.to_ascii_lowercase();
        if lower.contains("version:") {
            if let Some((_, rhs)) = line.split_once(':') {
                let v = rhs
                    .trim()
                    .trim_start_matches('*')
                    .trim()
                    .split_whitespace()
                    .next()
                    .unwrap_or("")
                    .trim_matches('*')
                    .to_string();
                if !v.is_empty() {
                    return Some(v);
                }
            }
        }
    }
    None
}

#[allow(dead_code)]
pub fn is_forbidden_bot_path(path: &Path) -> bool {
    let name = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    TOKEN_NAME_MARKERS.iter().any(|m| name.contains(m))
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
    #[cfg(not(windows))]
    {
        let _ = pid;
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn blocks_token_filenames() {
        assert!(is_forbidden_bot_path(&PathBuf::from("vercel_token.txt")));
        assert!(is_forbidden_bot_path(&PathBuf::from("cf-api-token.line")));
        assert!(is_forbidden_bot_path(&PathBuf::from("local-exec-daemon-credential.json")));
        assert!(!is_forbidden_bot_path(&PathBuf::from(
            "local-exec-daemon.json"
        )));
        assert!(!is_forbidden_bot_path(&PathBuf::from(
            "01-knock-ops-steward-PROMPT.md"
        )));
    }

    #[test]
    fn parses_pack_version() {
        let dir = std::env::temp_dir().join("orbit-bot-pack-test");
        let _ = std::fs::create_dir_all(&dir);
        let p = dir.join("prompt.md");
        std::fs::write(&p, "# Steward\n\n**Version:** v1.4.0 (2026-08-14)\n").unwrap();
        assert_eq!(steward_pack_version(&p).as_deref(), Some("v1.4.0"));
    }
}
