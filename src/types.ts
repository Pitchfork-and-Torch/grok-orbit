export type AdapterStatus = {
  name: string;
  status: string;
  detail: string;
};

export type Session = {
  id: string;
  source: string;
  project_id?: string | null;
  cwd: string;
  title: string;
  summary: string;
  state: string;
  health: string;
  pid?: number | null;
  model?: string | null;
  agent_name?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_active_at?: string | null;
  disk_path?: string | null;
  url?: string | null;
  remote?: string | null;
  branch?: string | null;
  pr_url?: string | null;
  pr_state?: string | null;
  pr_files?: string[];
  pr_file_count?: number | null;
  live: boolean;
  has_plan: boolean;
};

export type Project = {
  id: string;
  name: string;
  paths: string[];
  remotes?: string[];
  tags?: string[];
  session_ids: string[];
  live_count: number;
  running_count?: number;
  health?: string;
  updated_at?: string | null;
};

export type Attention = {
  id: string;
  session_id?: string | null;
  source: string;
  kind: string;
  title: string;
  created_at?: string | null;
  severity: string;
};

export type ActivityItem = {
  id: string;
  session_id: string;
  title: string;
  kind: string;
  text: string;
  live: boolean;
};

export type SearchHit = {
  id: string;
  title: string;
  cwd: string;
  updated_at?: string | null;
  snippet: string;
  live: boolean;
};

export type HandoffPack = {
  session_id: string;
  source: string;
  title: string;
  cwd: string;
  acp_cwd: string;
  branch?: string | null;
  url?: string | null;
  live: boolean;
  inject_ok: boolean;
  reason?: string | null;
  text: string;
};

export type FocusHit = {
  session_id: string;
  pid: number;
  hwnd: number;
  title: string;
  via: string;
  applied: boolean;
};

export type Snapshot = {
  generated_at: string;
  elapsed_ms: number;
  situation: string;
  adapters: AdapterStatus[];
  projects: Project[];
  sessions: Session[];
  attention: Attention[];
  activity: ActivityItem[];
  surfaces: {
    grok_bot: boolean;
    grok_bot_procs: number;
    local_exec_alive: boolean;
    steward_pack?: string | null;
    cursor: boolean;
    live_grok_pids: number[];
    web_consent?: boolean;
    grok_web?: string;
    grok_web_detail?: string | null;
    cursor_web?: string;
    cursor_web_detail?: string | null;
    cursor_web_probed_at?: string | null;
    cursor_pulse?: boolean;
    cook_armed?: boolean;
    cook_detail?: string | null;
    cook_summary?: string | null;
    cook_staff?: number;
  };
  grok_home: string;
  snap_profile?: string | null;
};

export type CookWell = {
  id: string;
  name: string;
  state: string;
  note?: string | null;
  shipped?: string | null;
  next?: string | null;
};

export type CookShip = {
  id: string;
  name: string;
  shipped: string;
  next?: string | null;
  fresh?: boolean;
};

export type CookState = {
  armed: boolean;
  last_summary?: string | null;
  last_detail?: string | null;
  last_sent?: string[];
  last_waiting?: string[];
  last_board?: CookWell[];
  last_next?: string[];
  last_ships?: CookShip[];
  staff_now?: number;
  ticks?: number;
  interval_sec?: number;
};

export type GitPulse = {
  cwd: string;
  branch?: string | null;
  dirty: number;
  lines: string[];
};

export type SessionDetail = {
  session: Session;
  plan_excerpt?: string | null;
  events: { kind: string; text: string }[];
};

export type PermOption = {
  option_id: string;
  name: string;
  kind: string;
};

export type PendingPermission = {
  request_id: string;
  session_id: string;
  title: string;
  kind: string;
  options: PermOption[];
};

export type AcpState = {
  running: boolean;
  initialized: boolean;
  can_resume: boolean;
  can_load: boolean;
  grok_permission_mode: string;
  last_error?: string | null;
  attached: { id: string; cwd: string; busy: boolean; origin: string }[];
  permissions: PendingPermission[];
  events: { session_id: string; kind: string; text: string }[];
};
