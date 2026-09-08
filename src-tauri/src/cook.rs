//! In-app COOK loop. No Task Scheduler. Stop is manual.

use crate::paths::{orbit_tree, orbit_web_home};
use crate::projects;
use crate::redact::redact;
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

const BUSY_SECS: u64 = 300;
const IDLE_SECS: u64 = 90;
const HARVEST_SECS: u64 = 20;
const PROOF_SECS: u64 = 45 * 60;
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
    #[serde(default)]
    pub shipped: Option<String>,
    #[serde(default)]
    pub next: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CookShip {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub shipped: String,
    #[serde(default)]
    pub next: Option<String>,
    #[serde(default)]
    pub fresh: bool,
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
    pub last_ships: Vec<CookShip>,
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
            last_ships: Vec::new(),
            staff_now: 0,
        }
    }
}

fn state_path() -> std::path::PathBuf {
    orbit_web_home().join("cook.json")
}

pub(crate) fn load_state() -> CookState {
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

#[derive(Debug, Clone, Default)]
struct CookReceipt {
    ok: bool,
    shipped: String,
    next: Option<String>,
    age_secs: Option<u64>,
}

impl CookReceipt {
    fn fresh(&self) -> bool {
        self.ok && !self.shipped.is_empty() && self.age_secs.map(|a| a < PROOF_SECS).unwrap_or(false)
    }
}

#[derive(Debug, Clone)]
struct WellProof {
    id: String,
    name: String,
    receipt: Option<CookReceipt>,
}

fn parse_receipt_json(text: &str, age_secs: Option<u64>) -> Option<CookReceipt> {
    let v: serde_json::Value = serde_json::from_str(text).ok()?;
    if !v.is_object() {
        return None;
    }
    let shipped = redact(v.get("shipped").and_then(|x| x.as_str()).unwrap_or("").trim());
    let next = v
        .get("next")
        .and_then(|x| x.as_str())
        .map(|s| redact(s.trim()))
        .filter(|s| !s.is_empty());
    Some(CookReceipt {
        ok: v.get("ok").and_then(|x| x.as_bool()).unwrap_or(false),
        shipped,
        next,
        age_secs,
    })
}

fn read_receipt(root: &Path) -> Option<CookReceipt> {
    let path = root.join(".orbit").join("cook-receipt.json");
    let text = std::fs::read_to_string(&path).ok()?;
    let age = std::fs::metadata(&path)
        .ok()
        .and_then(|m| m.modified().ok())
        .and_then(|t| t.elapsed().ok())
        .map(|d| d.as_secs());
    parse_receipt_json(&text, age)
}

fn collect_well_proofs() -> Vec<WellProof> {
    projects::named_clone_roots()
        .into_iter()
        .map(|(id, name, path)| WellProof {
            receipt: read_receipt(&path),
            id,
            name,
        })
        .collect()
}

fn overlay_proofs(mut state: CookState, proofs: &[WellProof]) -> CookState {
    if state.last_board.is_empty() {
        state.last_board = proofs
            .iter()
            .map(|well| {
                let rec = well.receipt.as_ref();
                let shipped = rec
                    .map(|r| r.shipped.clone())
                    .filter(|s| !s.is_empty());
                CookWell {
                    id: well.id.clone(),
                    name: well.name.clone(),
                    state: "idle".into(),
                    note: shipped.as_ref().map(|s| format!("last: {}", clip(s, 80))),
                    shipped,
                    next: rec.and_then(|r| r.next.clone()),
                }
            })
            .collect();
    } else {
        for well in proofs {
            let Some(rec) = well.receipt.as_ref() else {
                continue;
            };
            let Some(row) = state.last_board.iter_mut().find(|r| r.id == well.id) else {
                continue;
            };
            if !rec.shipped.is_empty() {
                row.shipped = Some(rec.shipped.clone());
            }
            if rec.next.is_some() {
                row.next = rec.next.clone();
            }
        }
    }

    for well in proofs {
        let Some(rec) = well.receipt.as_ref() else {
            continue;
        };
        if rec.shipped.is_empty() {
            continue;
        }
        let ship = CookShip {
            id: well.id.clone(),
            name: well.name.clone(),
            shipped: rec.shipped.clone(),
            next: rec.next.clone(),
            fresh: rec.fresh(),
        };
        if let Some(row) = state.last_ships.iter_mut().find(|s| s.id == well.id) {
            *row = ship;
        } else {
            state.last_ships.push(ship);
        }
    }
    state
}

fn clip(text: &str, n: usize) -> String {
    text.chars().take(n).collect()
}

pub fn status() -> CookState {
    overlay_proofs(load_state(), &collect_well_proofs())
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
        state.last_ships = v
            .get("ships")
            .and_then(|x| serde_json::from_value::<Vec<CookShip>>(x.clone()).ok())
            .unwrap_or_default();
        state.staff_now = v.get("staff_now").and_then(|x| x.as_u64()).unwrap_or(0) as u32;
        if let Some(sec) = v.get("interval_sec").and_then(|x| x.as_u64()) {
            state.interval_sec = sec as u32;
        }
    }
    state.ticks = state.ticks.saturating_add(1);
    save_state(&state)
}

fn run_harvest() -> Result<(), String> {
    let script = orbit_tree().join("scripts").join("cook.py");
    if !script.exists() {
        return Err(format!("missing {}", script.display()));
    }
    let mut cmd = Command::new("py");
    cmd.arg("-3").arg(&script).arg("harvest");
    cmd.stdin(std::process::Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }
    let out = cmd.output().map_err(|e| e.to_string())?;
    let text = String::from_utf8_lossy(&out.stdout);
    let parsed = serde_json::from_str::<serde_json::Value>(&text).ok();
    let mut state = load_state();
    if !state.armed {
        return Ok(());
    }
    if let Some(v) = parsed.as_ref() {
        if let Some(board) = v
            .get("board")
            .and_then(|x| serde_json::from_value::<Vec<CookWell>>(x.clone()).ok())
        {
            if !board.is_empty() {
                state.last_board = board;
            }
        }
        if let Some(ships) = v
            .get("ships")
            .and_then(|x| serde_json::from_value::<Vec<CookShip>>(x.clone()).ok())
        {
            state.last_ships = ships;
        }
        state.last_next = v
            .get("next_wave")
            .and_then(|x| x.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or(state.last_next);
        state.staff_now = v
            .get("staff_now")
            .and_then(|x| x.as_u64())
            .unwrap_or(state.staff_now as u64) as u32;
        if let Some(sec) = v.get("interval_sec").and_then(|x| x.as_u64()) {
            state.interval_sec = sec as u32;
        }
    }
    save_state(&state)
}

pub fn start_loop() {
    let armed = load_state().armed;
    LOOP_ON.store(armed, Ordering::SeqCst);
    std::thread::spawn(|| {
        let mut last = Instant::now();
        let mut last_harvest = Instant::now();
        loop {
            std::thread::sleep(Duration::from_secs(2));
            if !LOOP_ON.load(Ordering::SeqCst) || !load_state().armed {
                continue;
            }
            let state = load_state();
            let gap = if state.staff_now > 0 {
                BUSY_SECS
            } else {
                IDLE_SECS
            };
            if last.elapsed() >= Duration::from_secs(gap) {
                last = Instant::now();
                last_harvest = Instant::now();
                let _ = run_tick();
                continue;
            }
            if last_harvest.elapsed() >= Duration::from_secs(HARVEST_SECS) {
                last_harvest = Instant::now();
                let _ = run_harvest();
            }
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

    #[test]
    fn receipt_json_redacts_and_needs_ship() {
        let rec = parse_receipt_json(
            r#"{"ok":true,"shipped":"landed ghp_exampleplaceholder000000 x","next":"more"}"#,
            Some(12),
        )
        .expect("parse");
        assert!(rec.ok);
        assert!(rec.fresh());
        assert!(rec.shipped.contains("landed"));
        assert!(!rec.shipped.contains("ghp_"));
        assert_eq!(rec.next.as_deref(), Some("more"));
        let empty = parse_receipt_json(r#"{"ok":true,"shipped":""}"#, Some(1)).expect("empty");
        assert!(!empty.fresh());
        let stale = parse_receipt_json(r#"{"ok":true,"shipped":"old"}"#, Some(PROOF_SECS + 1)).expect("stale");
        assert!(!stale.fresh());
        assert!(parse_receipt_json("[]", None).is_none());
    }

    #[test]
    fn overlay_seeds_idle_board_and_ships() {
        let proofs = vec![
            WellProof {
                id: "vela".into(),
                name: "VELA".into(),
                receipt: Some(CookReceipt {
                    ok: true,
                    shipped: "dual-gate".into(),
                    next: Some("interval n".into()),
                    age_secs: Some(30),
                }),
            },
            WellProof {
                id: "axiom".into(),
                name: "AXIOM".into(),
                receipt: None,
            },
        ];
        let painted = overlay_proofs(CookState::default(), &proofs);
        assert_eq!(painted.last_board.len(), 2);
        assert_eq!(painted.last_board[0].state, "idle");
        assert_eq!(painted.last_board[0].shipped.as_deref(), Some("dual-gate"));
        assert_eq!(painted.last_ships.len(), 1);
        assert_eq!(painted.last_ships[0].id, "vela");
        assert!(painted.last_ships[0].fresh);
        assert_eq!(painted.last_ships[0].next.as_deref(), Some("interval n"));
    }

    #[test]
    fn overlay_keeps_cooking_state() {
        let mut state = CookState::default();
        state.last_board = vec![CookWell {
            id: "vela".into(),
            name: "VELA".into(),
            state: "cooking".into(),
            note: Some("window still open".into()),
            shipped: None,
            next: None,
        }];
        let proofs = vec![WellProof {
            id: "vela".into(),
            name: "VELA".into(),
            receipt: Some(CookReceipt {
                ok: true,
                shipped: "receipt line".into(),
                next: Some("next bit".into()),
                age_secs: Some(10),
            }),
        }];
        let painted = overlay_proofs(state, &proofs);
        assert_eq!(painted.last_board[0].state, "cooking");
        assert_eq!(
            painted.last_board[0].note.as_deref(),
            Some("window still open")
        );
        assert_eq!(painted.last_board[0].shipped.as_deref(), Some("receipt line"));
        assert_eq!(painted.last_board[0].next.as_deref(), Some("next bit"));
    }
}
