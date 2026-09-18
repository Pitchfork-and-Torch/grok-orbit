use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterStatus {
    pub name: String,
    pub status: String,
    pub detail: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Session {
    pub id: String,
    pub source: String,
    pub project_id: Option<String>,
    pub cwd: String,
    pub title: String,
    pub summary: String,
    pub state: String,
    pub health: String,
    pub pid: Option<u32>,
    pub model: Option<String>,
    pub agent_name: Option<String>,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
    pub last_active_at: Option<String>,
    pub disk_path: Option<String>,
    pub url: Option<String>,
    #[serde(default)]
    pub remote: Option<String>,
    #[serde(default)]
    pub branch: Option<String>,
    #[serde(default)]
    pub pr_url: Option<String>,
    #[serde(default)]
    pub pr_state: Option<String>,
    #[serde(default)]
    pub pr_files: Vec<String>,
    #[serde(default)]
    pub pr_file_count: Option<u32>,
    pub live: bool,
    pub has_plan: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Project {
    pub id: String,
    pub name: String,
    pub paths: Vec<String>,
    #[serde(default)]
    pub remotes: Vec<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    pub session_ids: Vec<String>,
    pub live_count: u32,
    #[serde(default)]
    pub running_count: u32,
    #[serde(default)]
    pub health: String,
    pub updated_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Attention {
    pub id: String,
    pub session_id: Option<String>,
    pub source: String,
    pub kind: String,
    pub title: String,
    pub created_at: Option<String>,
    pub severity: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Surfaces {
    pub grok_bot: bool,
    pub grok_bot_procs: u32,
    pub local_exec_alive: bool,
    pub steward_pack: Option<String>,
    pub cursor: bool,
    pub live_grok_pids: Vec<u32>,
    pub web_consent: bool,
    pub grok_web: String,
    pub grok_web_detail: Option<String>,
    pub cursor_web: String,
    pub cursor_web_detail: Option<String>,
    #[serde(default)]
    pub cursor_web_probed_at: Option<String>,
    #[serde(default = "default_cursor_pulse")]
    pub cursor_pulse: bool,
    #[serde(default)]
    pub cook_armed: bool,
    #[serde(default)]
    pub cook_detail: Option<String>,
    #[serde(default)]
    pub cook_summary: Option<String>,
    #[serde(default)]
    pub cook_staff: u32,
}

fn default_cursor_pulse() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActivityItem {
    pub id: String,
    pub session_id: String,
    pub title: String,
    pub kind: String,
    pub text: String,
    pub live: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchHit {
    pub id: String,
    pub title: String,
    pub cwd: String,
    pub updated_at: Option<String>,
    pub snippet: String,
    pub live: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HandoffPack {
    pub session_id: String,
    pub source: String,
    pub title: String,
    pub cwd: String,
    pub acp_cwd: String,
    pub branch: Option<String>,
    pub url: Option<String>,
    pub live: bool,
    pub inject_ok: bool,
    pub reason: Option<String>,
    pub text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FocusHit {
    pub session_id: String,
    pub pid: u32,
    pub hwnd: i64,
    pub title: String,
    pub via: String,
    pub applied: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub generated_at: String,
    pub elapsed_ms: u64,
    pub situation: String,
    pub adapters: Vec<AdapterStatus>,
    pub projects: Vec<Project>,
    pub sessions: Vec<Session>,
    pub attention: Vec<Attention>,
    pub activity: Vec<ActivityItem>,
    pub surfaces: Surfaces,
    pub grok_home: String,
    #[serde(default)]
    pub snap_profile: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionEvent {
    pub kind: String,
    pub text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionDetail {
    pub session: Session,
    pub plan_excerpt: Option<String>,
    pub events: Vec<SessionEvent>,
}

#[derive(Debug, Deserialize)]
pub struct ActiveRow {
    pub session_id: String,
    pub pid: u32,
    pub cwd: String,
    #[allow(dead_code)]
    pub opened_at: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct SummaryFile {
    pub info: Option<SummaryInfo>,
    pub session_summary: Option<String>,
    pub generated_title: Option<String>,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
    pub last_active_at: Option<String>,
    pub current_model_id: Option<String>,
    pub agent_name: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct SummaryInfo {
    #[allow(dead_code)]
    pub id: Option<String>,
    pub cwd: Option<String>,
}
