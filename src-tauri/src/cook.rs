//! In-app COOK loop. No Task Scheduler. Stop is manual.

use crate::paths::{orbit_tree, orbit_web_home};
use serde::{Deserialize, Serialize};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

const INTERVAL_SECS: u64 = 300;
static LOOP_ON: AtomicBool = AtomicBool::new(false);

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CookWell {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub state: String,
    #[serde(default)]
    pub note: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CookState {
    #[serde(default)]
    pub armed: bool,
    #[serde(default)]
    pub started_at: Option<String>,
    #[serde(default)]
    pub last_tick: Option<String>,
    #[serde(default)]
    pub last_detail: Option<String>,
    #[serde(default)]
    pub ticks: u32,
    #[serde(default = "default_interval")]
    pub interval_sec: u32,
    #[serde(default)]
    pub last_summary: Option<String>,
    #[serde(default)]
    pub last_sent: Vec<String>,
    #[serde(default)]
    pub last_waiting: Vec<String>,
    #[serde(default)]
    pub last_board: Vec<CookWell>,
    #[serde(default)]
    pub last_next: Vec<String>,
    #[serde(default)]
    pub staff_now: u32,
}

fn default_interval() -> u32 {
    300
}

impl Default for CookState {
    fn default() -> Self {
        Self {
            armed: false,
            started_at: None,
            last_tick: None,
            last_detail: None,
            ticks: 0,
            interval_sec: 300,
            last_summary: None,
            last_sent: Vec::new(),
            last_waiting: Vec::new(),
            last_board: Vec::new(),
            last_next: Vec::new(),
            staff_now: 0,
        }
    }
}

fn state_path() -> std::path::PathBuf {
    orbit_web_home().join("cook.json")
}

pub fn load_state() -> CookState {
    let Ok(text) = std::fs::read_to_string(state_path()) else {
        return CookState::default();
    };
    serde_json::from_str(&text).unwrap_or_default()
}

fn save_state(state: &CookState) -> Result<(), String> {
    if let Some(parent) = state_path().parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let body = serde_json::to_string_pretty(state).map_err(|e| e.to_string())?;
    std::fs::write(state_path(), body + "\n").map_err(|e| e.to_string())
}

pub fn status() -> CookState {
    load_state()
}

pub fn arm() -> Result<String, String> {
    let mut state = load_state();
    if state.armed {
        return Ok("COOK already armed".into());
    }
    state.armed = true;
    state.started_at = Some(now_rfc());
    state.last_detail = Some("armed; first tick starting".into());
    save_state(&state)?;
    LOOP_ON.store(true, Ordering::SeqCst);
    std::thread::spawn(|| {
        let _ = run_tick();
    });
    Ok("COOK armed. Staff deploy on named wells. STOP COOK to halt new dispatches.".into())
}

pub fn disarm() -> Result<String, String> {
    let mut state = load_state();
    state.armed = false;
    state.last_detail = Some("stopped; running consoles were left up".into());
    save_state(&state)?;
    LOOP_ON.store(false, Ordering::SeqCst);
    Ok("COOK stopped. Already-running staff consoles were not killed.".into())
}

fn now_rfc() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{secs}")
}

fn run_tick() -> Result<(), String> {
    let script = orbit_tree().join("scripts").join("cook.py");
    if !script.exists() {
        return Err(format!("missing {}", script.display()));
    }
    let mut cmd = Command::new("py");
    cmd.arg("-3").arg(&script).arg("tick");
    cmd.stdin(std::process::Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }
    let out = cmd.output().map_err(|e| e.to_string())?;
    let text = String::from_utf8_lossy(&out.stdout);
    let parsed = serde_json::from_str::<serde_json::Value>(&text).ok();
    let detail = parsed
        .as_ref()
        .and_then(|v| v.get("detail")?.as_str().map(|s| s.to_string()))
        .unwrap_or_else(|| text.trim().chars().take(180).collect());
    let mut state = load_state();
    if !state.armed {
        return Ok(());
    }
    state.last_tick = Some(now_rfc());
    state.last_detail = Some(detail);
    if let Some(v) = parsed.as_ref() {
        state.last_summary = v
            .get("summary")
            .and_then(|x| x.as_str())
            .map(|s| s.to_string());
        state.last_sent = v
            .get("sent")
            .and_then(|x| x.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();
        state.last_waiting = v
            .get("waiting")
            .and_then(|x| x.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();
        state.last_board = v
            .get("board")
            .and_then(|x| serde_json::from_value::<Vec<CookWell>>(x.clone()).ok())
            .unwrap_or_default();
        state.last_next = v
            .get("next_wave")
            .and_then(|x| x.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();
        state.staff_now = v.get("staff_now").and_then(|x| x.as_u64()).unwrap_or(0) as u32;
    }
    state.ticks = state.ticks.saturating_add(1);
    save_state(&state)
}

pub fn start_loop() {
    let armed = load_state().armed;
    LOOP_ON.store(armed, Ordering::SeqCst);
    std::thread::spawn(|| {
        let mut last = Instant::now();
        loop {
            std::thread::sleep(Duration::from_secs(2));
            if !LOOP_ON.load(Ordering::SeqCst) || !load_state().armed {
                continue;
            }
            if last.elapsed() < Duration::from_secs(INTERVAL_SECS) {
                continue;
            }
            last = Instant::now();
            let _ = run_tick();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_is_disarmed() {
        let s = CookState::default();
        assert!(!s.armed);
        assert_eq!(s.interval_sec, 300);
    }
}
