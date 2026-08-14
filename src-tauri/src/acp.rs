use crate::paths::{grok_bin, grok_home};
use crate::redact::{is_session_id, redact};
use crate::snapshot::tui_live_ids;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Emitter};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PermOption {
    pub option_id: String,
    pub name: String,
    pub kind: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PendingPermission {
    pub request_id: String,
    pub session_id: String,
    pub title: String,
    pub kind: String,
    pub options: Vec<PermOption>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AcpEvent {
    pub session_id: String,
    pub kind: String,
    pub text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AcpSessionInfo {
    pub id: String,
    pub cwd: String,
    pub busy: bool,
    pub origin: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AcpState {
    pub running: bool,
    pub initialized: bool,
    pub can_resume: bool,
    pub can_load: bool,
    pub grok_permission_mode: String,
    pub last_error: Option<String>,
    pub attached: Vec<AcpSessionInfo>,
    pub permissions: Vec<PendingPermission>,
    pub events: Vec<AcpEvent>,
}

struct AcpSession {
    id: String,
    cwd: String,
    origin: String,
    busy: bool,
    events: Vec<AcpEvent>,
}

struct Inner {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    next_id: u64,
    waiters: HashMap<u64, Sender<Value>>,
    permissions: Vec<PendingPermission>,
    sessions: HashMap<String, AcpSession>,
    initialized: bool,
    can_resume: bool,
    can_load: bool,
    last_error: Option<String>,
    app: Option<AppHandle>,
}

impl Inner {
    fn new() -> Self {
        Self {
            child: None,
            stdin: None,
            next_id: 1,
            waiters: HashMap::new(),
            permissions: Vec::new(),
            sessions: HashMap::new(),
            initialized: false,
            can_resume: false,
            can_load: false,
            last_error: None,
            app: None,
        }
    }

    fn emit(&self, event: &str, payload: Value) {
        if let Some(app) = &self.app {
            let _ = app.emit(event, payload);
        }
    }
}

#[derive(Clone)]
pub struct AcpHub {
    inner: Arc<Mutex<Inner>>,
}

impl AcpHub {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(Inner::new())),
        }
    }

    pub fn set_app(&self, app: AppHandle) {
        if let Ok(mut g) = self.inner.lock() {
            g.app = Some(app);
        }
    }

    pub fn state(&self) -> AcpState {
        let g = self.inner.lock().unwrap();
        let mut events = Vec::new();
        for s in g.sessions.values() {
            events.extend(s.events.iter().cloned());
        }
        if events.len() > 80 {
            events = events.split_off(events.len() - 80);
        }
        AcpState {
            running: g.child.is_some(),
            initialized: g.initialized,
            can_resume: g.can_resume,
            can_load: g.can_load,
            grok_permission_mode: grok_permission_mode(),
            last_error: g.last_error.clone(),
            attached: g
                .sessions
                .values()
                .map(|s| AcpSessionInfo {
                    id: s.id.clone(),
                    cwd: s.cwd.clone(),
                    busy: s.busy,
                    origin: s.origin.clone(),
                })
                .collect(),
            permissions: g.permissions.clone(),
            events,
        }
    }

    pub fn ensure(&self) -> Result<AcpState, String> {
        if self.state().initialized {
            return Ok(self.state());
        }
        self.start_and_init()?;
        Ok(self.state())
    }

    pub fn new_session(&self, cwd: &str) -> Result<String, String> {
        self.ensure()?;
        let cwd = cwd.trim();
        if cwd.is_empty() {
            return Err("cwd required".into());
        }
        let result = self.rpc(
            "session/new",
            json!({
                "cwd": cwd,
                "mcpServers": [],
                "_meta": { "yoloMode": false }
            }),
            Duration::from_secs(45),
        )?;
        let id = result
            .get("sessionId")
            .and_then(|v| v.as_str())
            .ok_or_else(|| format!("session/new missing id: {result}"))?
            .to_string();
        if !is_session_id(&id) {
            return Err(format!("unexpected session id {id}"));
        }
        let mut g = self.inner.lock().unwrap();
        g.sessions.insert(
            id.clone(),
            AcpSession {
                id: id.clone(),
                cwd: cwd.to_string(),
                origin: "new".into(),
                busy: false,
                events: vec![],
            },
        );
        Ok(id)
    }

    pub fn attach_session(&self, id: &str, cwd: &str) -> Result<String, String> {
        if !is_session_id(id) {
            return Err("invalid session id".into());
        }
        if refuse_live_tui(id, &tui_live_ids()) {
            return Err(
                "refusing ACP attach: that session is a live Grok TUI pager. Use Resume in Grok."
                    .into(),
            );
        }
        self.ensure()?;
        let st = self.state();
        if st.attached.iter().any(|s| s.id == id) {
            return Ok(id.to_string());
        }
        let params = json!({
            "sessionId": id,
            "cwd": cwd,
            "mcpServers": [],
            "_meta": { "yoloMode": false }
        });
        let method = if st.can_resume {
            "session/resume"
        } else if st.can_load {
            "session/load"
        } else {
            return Err("agent does not advertise resume or load".into());
        };
        self.rpc(method, params, Duration::from_secs(45))?;
        let mut g = self.inner.lock().unwrap();
        g.sessions.insert(
            id.to_string(),
            AcpSession {
                id: id.to_string(),
                cwd: cwd.to_string(),
                origin: "resume".into(),
                busy: false,
                events: vec![],
            },
        );
        Ok(format!("attached via {method}"))
    }

    pub fn prompt(&self, id: &str, text: &str) -> Result<String, String> {
        if !is_session_id(id) {
            return Err("invalid session id".into());
        }
        let text = text.trim();
        if text.is_empty() {
            return Err("empty prompt".into());
        }
        if refuse_live_tui(id, &tui_live_ids()) {
            return Err("refusing prompt: live TUI session".into());
        }
        self.ensure()?;
        if !self.state().attached.iter().any(|s| s.id == id) {
            return Err("session is not attached. Attach in Orbit first.".into());
        }
        {
            let mut g = self.inner.lock().unwrap();
            if let Some(s) = g.sessions.get_mut(id) {
                s.busy = true;
                s.events.push(AcpEvent {
                    session_id: id.to_string(),
                    kind: "user".into(),
                    text: redact(text),
                });
            }
        }
        let hub = self.clone();
        let sid = id.to_string();
        let body = text.to_string();
        std::thread::spawn(move || {
            let _ = hub.rpc(
                "session/prompt",
                json!({
                    "sessionId": sid,
                    "prompt": [{ "type": "text", "text": body }]
                }),
                Duration::from_secs(600),
            );
            if let Ok(mut g) = hub.inner.lock() {
                if let Some(s) = g.sessions.get_mut(&sid) {
                    s.busy = false;
                }
                g.emit("acp://turn", json!({ "sessionId": sid, "done": true }));
            }
        });
        Ok("turn started".into())
    }

    pub fn respond(&self, request_id: &str, option_id: &str) -> Result<String, String> {
        let mut g = self.inner.lock().unwrap();
        let idx = g
            .permissions
            .iter()
            .position(|p| p.request_id == request_id)
            .ok_or_else(|| "no such permission request".to_string())?;
        let pending = g.permissions.remove(idx);
        let rpc_id: Value = serde_json::from_str(request_id)
            .unwrap_or_else(|_| Value::String(request_id.to_string()));
        let result = if option_id == "cancelled" {
            json!({ "outcome": { "outcome": "cancelled" } })
        } else {
            json!({ "outcome": { "outcome": "selected", "optionId": option_id } })
        };
        let msg = json!({ "jsonrpc": "2.0", "id": rpc_id, "result": result });
        write_line(g.stdin.as_mut(), &msg)?;
        g.emit(
            "acp://permission",
            json!({ "resolved": true, "requestId": request_id, "optionId": option_id, "sessionId": pending.session_id }),
        );
        Ok(format!("answered {option_id}"))
    }

    pub fn cancel(&self, id: &str) -> Result<String, String> {
        self.ensure()?;
        let mut g = self.inner.lock().unwrap();
        let msg = json!({
            "jsonrpc": "2.0",
            "method": "session/cancel",
            "params": { "sessionId": id }
        });
        write_line(g.stdin.as_mut(), &msg)?;
        let pending: Vec<String> = g
            .permissions
            .iter()
            .filter(|p| p.session_id == id)
            .map(|p| p.request_id.clone())
            .collect();
        drop(g);
        for rid in pending {
            let _ = self.respond(&rid, "cancelled");
        }
        Ok("cancelled".into())
    }

    fn start_and_init(&self) -> Result<(), String> {
        let home = grok_home();
        let bin = grok_bin(&home);
        if !bin.exists() {
            return Err(format!("grok missing: {}", bin.display()));
        }
        let mut cmd = Command::new(&bin);
        cmd.args(["agent", "--no-leader", "stdio"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("GROK_DISABLE_AUTOUPDATER", "1");
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000);
        }
        let mut child = cmd.spawn().map_err(|e| e.to_string())?;
        let stdin = child.stdin.take().ok_or("no stdin")?;
        let stdout = child.stdout.take().ok_or("no stdout")?;
        let stderr = child.stderr.take();
        {
            let mut g = self.inner.lock().unwrap();
            g.child = Some(child);
            g.stdin = Some(stdin);
            g.initialized = false;
            g.last_error = None;
        }
        let hub = self.clone();
        std::thread::Builder::new()
            .name("orbit-acp-stdout".into())
            .spawn(move || hub.read_loop(stdout))
            .map_err(|e| e.to_string())?;
        if let Some(err) = stderr {
            std::thread::spawn(move || {
                for line in BufReader::new(err).lines().flatten() {
                    let _ = line;
                }
            });
        }
        let result = self.rpc(
            "initialize",
            json!({
                "protocolVersion": 1,
                "clientInfo": { "name": "grok-orbit", "version": "0.2.0" },
                "clientCapabilities": {
                    "fs": { "readTextFile": false, "writeTextFile": false },
                    "terminal": false
                }
            }),
            Duration::from_secs(25),
        )?;
        let caps = result.get("agentCapabilities").cloned().unwrap_or(json!({}));
        let mut g = self.inner.lock().unwrap();
        g.initialized = true;
        g.can_load = caps.get("loadSession").and_then(|v| v.as_bool()).unwrap_or(false);
        g.can_resume = caps
            .pointer("/sessionCapabilities/resume")
            .is_some();
        Ok(())
    }

    fn rpc(&self, method: &str, params: Value, timeout: Duration) -> Result<Value, String> {
        let (tx, rx) = mpsc::channel();
        {
            let mut g = self.inner.lock().unwrap();
            if g.stdin.is_none() {
                return Err("ACP agent not running".into());
            }
            let id = g.next_id;
            g.next_id += 1;
            g.waiters.insert(id, tx);
            let msg = json!({
                "jsonrpc": "2.0",
                "id": id,
                "method": method,
                "params": params
            });
            write_line(g.stdin.as_mut(), &msg)?;
        }
        match rx.recv_timeout(timeout) {
            Ok(Value::Object(map)) if map.contains_key("error") => {
                Err(map.get("error").cloned().unwrap_or(json!("error")).to_string())
            }
            Ok(v) => Ok(v),
            Err(RecvTimeoutError::Timeout) => Err(format!("{method} timed out")),
            Err(e) => Err(e.to_string()),
        }
    }

    fn read_loop(&self, stdout: std::process::ChildStdout) {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let Ok(line) = line else { break };
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let Ok(msg) = serde_json::from_str::<Value>(line) else {
                continue;
            };
            self.dispatch(msg);
        }
        if let Ok(mut g) = self.inner.lock() {
            g.initialized = false;
            g.child = None;
            g.stdin = None;
            g.last_error = Some("ACP agent stdout closed".into());
        }
    }

    fn dispatch(&self, msg: Value) {
        let method = msg.get("method").and_then(|v| v.as_str()).unwrap_or("");
        let id = msg.get("id").cloned();
        if method == "session/request_permission" {
            if let Some(id) = id {
                self.on_permission(id, msg.get("params").cloned().unwrap_or(json!({})));
            }
            return;
        }
        if method == "session/update" {
            self.on_update(msg.get("params").cloned().unwrap_or(json!({})));
            return;
        }
        if !method.is_empty() && id.is_some() {
            let mut g = self.inner.lock().unwrap();
            let err = json!({
                "jsonrpc": "2.0",
                "id": id,
                "error": { "code": -32601, "message": format!("Method not found: {method}") }
            });
            let _ = write_line(g.stdin.as_mut(), &err);
            return;
        }
        if let Some(idv) = id {
            if let Some(n) = idv.as_u64().or_else(|| idv.as_i64().map(|i| i as u64)) {
                let mut g = self.inner.lock().unwrap();
                if let Some(tx) = g.waiters.remove(&n) {
                    let payload = if let Some(err) = msg.get("error") {
                        json!({ "error": err })
                    } else {
                        msg.get("result").cloned().unwrap_or(Value::Null)
                    };
                    let _ = tx.send(payload);
                }
            }
        }
    }

    fn on_permission(&self, id: Value, params: Value) {
        let session_id = params
            .get("sessionId")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let tool = params.get("toolCall").cloned().unwrap_or(json!({}));
        let title = tool
            .get("title")
            .and_then(|v| v.as_str())
            .or_else(|| tool.get("toolCallId").and_then(|v| v.as_str()))
            .unwrap_or("tool call")
            .to_string();
        let kind = tool
            .get("kind")
            .and_then(|v| v.as_str())
            .unwrap_or("other")
            .to_string();
        let mut options = Vec::new();
        if let Some(arr) = params.get("options").and_then(|v| v.as_array()) {
            for o in arr {
                options.push(PermOption {
                    option_id: o
                        .get("optionId")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    name: o
                        .get("name")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    kind: o
                        .get("kind")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                });
            }
        }
        let pending = PendingPermission {
            request_id: id.to_string(),
            session_id: session_id.clone(),
            title: redact(&title),
            kind,
            options,
        };
        let mut g = self.inner.lock().unwrap();
        g.permissions.push(pending.clone());
        g.emit("acp://permission", json!(pending));
    }

    fn on_update(&self, params: Value) {
        let session_id = params
            .get("sessionId")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let update = params.get("update").cloned().unwrap_or(json!({}));
        let kind = update
            .get("sessionUpdate")
            .and_then(|v| v.as_str())
            .unwrap_or("update")
            .to_string();
        let text = match kind.as_str() {
            "user_message_chunk" | "agent_message_chunk" | "agent_thought_chunk" => update
                .pointer("/content/text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            "tool_call" | "tool_call_update" => update
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or(kind.as_str())
                .to_string(),
            "plan" => "plan update".into(),
            _ => kind.clone(),
        };
        let text = redact(text.trim());
        if text.is_empty() {
            return;
        }
        let ev = AcpEvent {
            session_id: session_id.clone(),
            kind,
            text,
        };
        let mut g = self.inner.lock().unwrap();
        if let Some(s) = g.sessions.get_mut(&session_id) {
            s.events.push(ev.clone());
            if s.events.len() > 80 {
                s.events.remove(0);
            }
        }
        g.emit("acp://update", json!(ev));
    }
}

pub fn refuse_live_tui(id: &str, live: &std::collections::HashSet<String>) -> bool {
    live.contains(id)
}

fn grok_permission_mode() -> String {
    let path = grok_home().join("config.toml");
    let Ok(text) = std::fs::read_to_string(path) else {
        return "unknown".into();
    };
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('#') || !line.starts_with("permission_mode") {
            continue;
        }
        if let Some((_, rhs)) = line.split_once('=') {
            return rhs.trim().trim_matches('"').to_string();
        }
    }
    "unknown".into()
}

fn write_line(stdin: Option<&mut ChildStdin>, msg: &Value) -> Result<(), String> {
    let stdin = stdin.ok_or("ACP stdin closed")?;
    writeln!(stdin, "{msg}").map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn refuses_live_ids() {
        let mut live = std::collections::HashSet::new();
        live.insert("01a00022-b643-7b40-9d7e-dc185c67e3c2".into());
        assert!(refuse_live_tui(
            "01a00022-b643-7b40-9d7e-dc185c67e3c2",
            &live
        ));
        assert!(!refuse_live_tui(
            "01a00000-0000-7000-8000-000000000099",
            &live
        ));
    }

    #[test]
    fn parses_permission_options() {
        let raw = json!({
            "sessionId": "01a00022-b643-7b40-9d7e-dc185c67e3c2",
            "toolCall": { "toolCallId": "c1", "title": "Run tests", "kind": "execute" },
            "options": [
                { "optionId": "allow-once", "name": "Allow once", "kind": "allow_once" },
                { "optionId": "reject-once", "name": "Reject", "kind": "reject_once" }
            ]
        });
        let title = raw["toolCall"]["title"].as_str().unwrap();
        assert_eq!(title, "Run tests");
        assert_eq!(raw["options"][0]["kind"], "allow_once");
    }
}
