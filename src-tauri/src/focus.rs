//! Bring a live Grok pager's window forward. Never injects into the TUI.

use crate::model::FocusHit;
use crate::snapshot::{session_detail, tui_live_ids};

#[derive(Debug, Clone)]
pub(crate) struct Resolved {
    pid: u32,
    hwnd: isize,
    title: String,
    via: String,
}

pub fn focus_session(id: &str, apply: bool) -> Result<FocusHit, String> {
    if !crate::redact::is_session_id(id) {
        return Err("invalid session id".into());
    }
    let live = tui_live_ids();
    if !live.contains(id) {
        return Err("not a live TUI pager; use Resume in Grok".into());
    }
    let detail = session_detail(id)?;
    let pid = detail
        .session
        .pid
        .ok_or_else(|| "live session has no pid".to_string())?;
    let resolved = resolve_pid(pid).ok_or_else(|| format!("no visible window for pid {pid}"))?;
    let mut applied = false;
    if apply {
        applied = foreground(resolved.hwnd);
        if !applied {
            return Err(format!(
                "found hwnd {} ({}) but Windows refused foreground",
                resolved.hwnd, resolved.title
            ));
        }
    }
    Ok(FocusHit {
        session_id: id.to_string(),
        pid: resolved.pid,
        hwnd: resolved.hwnd as i64,
        title: resolved.title,
        via: resolved.via,
        applied,
    })
}

pub fn resolve_pid(start_pid: u32) -> Option<Resolved> {
    if start_pid == 0 {
        return None;
    }
    let mut pid = start_pid;
    let mut via = format!("pid {start_pid}");
    for hop in 0..7 {
        if let Some((hwnd, title)) = first_visible(pid) {
            if hop > 0 {
                via = format!("ancestor pid {pid} of {start_pid}");
            }
            return Some(Resolved {
                pid,
                hwnd,
                title,
                via,
            });
        }
        let parent = parent_pid(pid)?;
        if parent == 0 || parent == pid || parent == 4 {
            break;
        }
        pid = parent;
    }
    None
}

fn first_visible(pid: u32) -> Option<(isize, String)> {
    let mut hits: Vec<(isize, String)> = Vec::new();
    let mut state = EnumState {
        pid,
        hits: &mut hits,
    };
    unsafe {
        EnumWindows(enum_cb, &mut state as *mut EnumState as isize);
    }
    let grok = hits.iter().find(|(_, t)| t.to_ascii_lowercase().contains("grok"));
    if let Some((h, t)) = grok {
        return Some((*h, t.clone()));
    }
    hits.into_iter().next()
}

struct EnumState<'a> {
    pid: u32,
    hits: &'a mut Vec<(isize, String)>,
}

unsafe extern "system" fn enum_cb(hwnd: isize, lparam: isize) -> i32 {
    let state = &mut *(lparam as *mut EnumState);
    let mut pid = 0u32;
    GetWindowThreadProcessId(hwnd, &mut pid);
    if pid != state.pid {
        return 1;
    }
    if IsWindowVisible(hwnd) == 0 {
        return 1;
    }
    if GetWindow(hwnd, GW_OWNER) != 0 {
        return 1;
    }
    let title = window_title(hwnd);
    state.hits.push((hwnd, title));
    1
}

fn window_title(hwnd: isize) -> String {
    let mut buf = [0u16; 512];
    let n = unsafe { GetWindowTextW(hwnd, buf.as_mut_ptr(), buf.len() as i32) };
    if n <= 0 {
        return String::new();
    }
    String::from_utf16_lossy(&buf[..n as usize])
}

fn parent_pid(pid: u32) -> Option<u32> {
    const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
    const PROCESS_BASIC_INFORMATION: u32 = 0;
    #[repr(C)]
    struct Pbi {
        reserved1: isize,
        peb: isize,
        reserved2: [isize; 2],
        unique: usize,
        inherited: usize,
    }
    unsafe {
        let h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if h == 0 {
            return None;
        }
        let mut info = Pbi {
            reserved1: 0,
            peb: 0,
            reserved2: [0, 0],
            unique: 0,
            inherited: 0,
        };
        let mut ret = 0u32;
        let status = NtQueryInformationProcess(
            h,
            PROCESS_BASIC_INFORMATION,
            &mut info as *mut Pbi as *mut u8,
            std::mem::size_of::<Pbi>() as u32,
            &mut ret,
        );
        CloseHandle(h);
        if status != 0 {
            return None;
        }
        Some(info.inherited as u32)
    }
}

fn foreground(hwnd: isize) -> bool {
    const SW_RESTORE: i32 = 9;
    const ASFW_ANY: u32 = 0xFFFFFFFF;
    unsafe {
        let _ = AllowSetForegroundWindow(ASFW_ANY);
        let _ = ShowWindow(hwnd, SW_RESTORE);
        if SetForegroundWindow(hwnd) != 0 {
            return true;
        }
        let fg = GetForegroundWindow();
        let mut fg_pid = 0u32;
        let fg_tid = GetWindowThreadProcessId(fg, &mut fg_pid);
        let cur = GetCurrentThreadId();
        if fg_tid != 0 && fg_tid != cur {
            let _ = AttachThreadInput(cur, fg_tid, 1);
            let ok = SetForegroundWindow(hwnd) != 0;
            let _ = AttachThreadInput(cur, fg_tid, 0);
            if ok {
                return true;
            }
        }
        SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW) != 0
    }
}

const GW_OWNER: u32 = 4;
const HWND_TOP: isize = 0;
const SWP_NOMOVE: u32 = 0x0002;
const SWP_NOSIZE: u32 = 0x0001;
const SWP_SHOWWINDOW: u32 = 0x0040;

type WndEnumProc = unsafe extern "system" fn(hwnd: isize, lparam: isize) -> i32;

#[link(name = "user32")]
extern "system" {
    fn EnumWindows(cb: WndEnumProc, lparam: isize) -> i32;
    fn GetWindowThreadProcessId(hwnd: isize, pid: *mut u32) -> u32;
    fn IsWindowVisible(hwnd: isize) -> i32;
    fn GetWindow(hwnd: isize, cmd: u32) -> isize;
    fn GetWindowTextW(hwnd: isize, lp: *mut u16, n: i32) -> i32;
    fn ShowWindow(hwnd: isize, cmd: i32) -> i32;
    fn SetForegroundWindow(hwnd: isize) -> i32;
    fn AllowSetForegroundWindow(pid: u32) -> i32;
    fn AttachThreadInput(id_attach: u32, id_attach_to: u32, attach: i32) -> i32;
    fn GetForegroundWindow() -> isize;
    fn SetWindowPos(hwnd: isize, after: isize, x: i32, y: i32, cx: i32, cy: i32, flags: u32) -> i32;
}

#[link(name = "kernel32")]
extern "system" {
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> isize;
    fn CloseHandle(handle: isize) -> i32;
    fn GetCurrentThreadId() -> u32;
}

#[link(name = "ntdll")]
extern "system" {
    fn NtQueryInformationProcess(
        handle: isize,
        class: u32,
        info: *mut u8,
        len: u32,
        ret: *mut u32,
    ) -> i32;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::paths::grok_home;

    #[test]
    fn resolves_live_grok_window() {
        let path = grok_home().join("active_sessions.json");
        let Ok(raw) = std::fs::read_to_string(&path) else {
            return;
        };
        let rows: Vec<serde_json::Value> = serde_json::from_str(&raw).unwrap_or_default();
        for row in rows {
            let pid = row.get("pid").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
            if pid == 0 {
                continue;
            }
            if let Some(hit) = resolve_pid(pid) {
                assert!(hit.hwnd != 0, "{hit:?}");
                return;
            }
        }
    }
}
