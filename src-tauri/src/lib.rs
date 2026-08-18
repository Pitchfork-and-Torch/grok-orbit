mod acp;
mod bot;
mod clock;
mod cook;
mod focus;
mod git;
mod handoff;
mod license;
mod model;
mod paths;
mod pr;
mod projects;
mod pulse;
mod redact;
mod sample;
mod setup;
mod snapshot;
mod web;

use acp::{AcpHub, AcpState};
use snapshot::{
    open_cwd, open_session_dir, resume_in_grok, search_sessions, session_detail,
};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};
use tauri_plugin_global_shortcut::GlobalShortcutExt;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
static CURSOR_API_IN_FLIGHT: AtomicBool = AtomicBool::new(false);

fn json_probed_at(path: &std::path::Path) -> String {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
        .and_then(|v| v.get("probed_at")?.as_str().map(|s| s.to_string()))
        .unwrap_or_default()
}

fn cursor_cache_probed() -> String {
    let cache = paths::orbit_web_home().join("cache").join("cursor_web.json");
    let pulse = paths::orbit_web_home().join("cache").join("cursor_web.pulse.json");
    format!("{}|{}", json_probed_at(&cache), json_probed_at(&pulse))
}

fn hide_console(cmd: &mut std::process::Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
}

fn spawn_hidden_py(script: &std::path::Path, args: &[&str]) -> Result<(), String> {
    if !script.exists() {
        return Err(format!("missing {}", script.display()));
    }
    let mut cmd = std::process::Command::new("py");
    cmd.arg("-3").arg(script).args(args);
    cmd.stdin(std::process::Stdio::null());
    cmd.stdout(std::process::Stdio::null());
    cmd.stderr(std::process::Stdio::null());
    hide_console(&mut cmd);
    cmd.spawn().map_err(|e| e.to_string())?;
    Ok(())
}

fn run_brave_cli(args: &[&str]) -> Result<String, String> {
    let script = paths::orbit_tree().join("scripts").join("brave_grok.py");
    if !script.exists() {
        return Err(format!("missing {}", script.display()));
    }
    let mut cmd = std::process::Command::new("py");
    cmd.arg("-3").arg(&script).args(args);
    hide_console(&mut cmd);
    let out = cmd.output().map_err(|e| e.to_string())?;
    let text = String::from_utf8_lossy(&out.stdout).to_string();
    let err = String::from_utf8_lossy(&out.stderr).to_string();
    if !out.status.success() {
        return Err(if err.trim().is_empty() {
            text.trim().to_string()
        } else {
            err.trim().to_string()
        });
    }
    Ok(text)
}

#[tauri::command]
fn get_snapshot(app: tauri::AppHandle, full: Option<bool>) -> model::Snapshot {
    let snap = snapshot::collect_snapshot_ex(full.unwrap_or(false));
    pulse::apply(&app, &snap);
    snap
}

#[tauri::command]
fn search_sessions_cmd(query: String) -> Result<Vec<model::SearchHit>, String> {
    search_sessions(&query)
}

#[tauri::command]
fn get_session_detail(id: String) -> Result<model::SessionDetail, String> {
    session_detail(&id)
}

fn require_unlocked() -> Result<(), String> {
    crate::license::require_unlocked()
}

#[tauri::command]
fn resume_session(id: String) -> Result<String, String> {
    require_unlocked()?;
    if crate::sample::is_sample_id(&id) {
        return Err("Sample cards cannot resume. Connect a real Grok CLI session.".into());
    }
    resume_in_grok(&id)
}

#[tauri::command]
fn open_session_cwd(id: String) -> Result<(), String> {
    open_cwd(&id)
}

#[tauri::command]
fn reveal_session_dir(id: String) -> Result<(), String> {
    open_session_dir(&id)
}

#[tauri::command]
fn acp_state(hub: tauri::State<AcpHub>) -> AcpState {
    hub.state()
}

#[tauri::command]
fn acp_ensure(hub: tauri::State<AcpHub>) -> Result<AcpState, String> {
    require_unlocked()?;
    hub.ensure()
}

#[tauri::command]
fn acp_new_session(hub: tauri::State<AcpHub>, cwd: String) -> Result<String, String> {
    require_unlocked()?;
    hub.new_session(&cwd)
}

#[tauri::command]
fn acp_attach(hub: tauri::State<AcpHub>, id: String, cwd: String) -> Result<String, String> {
    require_unlocked()?;
    hub.attach_session(&id, &cwd)
}

#[tauri::command]
fn acp_prompt(hub: tauri::State<AcpHub>, id: String, text: String) -> Result<String, String> {
    require_unlocked()?;
    hub.prompt(&id, &text)
}

#[tauri::command]
fn acp_respond(
    hub: tauri::State<AcpHub>,
    request_id: String,
    option_id: String,
) -> Result<String, String> {
    require_unlocked()?;
    hub.respond(&request_id, &option_id)
}

#[tauri::command]
fn acp_cancel(hub: tauri::State<AcpHub>, id: String) -> Result<String, String> {
    hub.cancel(&id)
}

#[tauri::command]
fn web_status() -> Result<String, String> {
    web::run_web_cli(&["status"])
}

#[tauri::command]
fn web_grant_consent() -> Result<String, String> {
    web::run_web_cli(&["grant"])
}

#[tauri::command]
fn license_status() -> license::LicenseStatus {
    license::status()
}

#[tauri::command]
fn license_save(raw: String) -> Result<license::LicenseStatus, String> {
    license::save_license_json(raw)
}

#[tauri::command]
fn license_machine_id() -> String {
    license::machine_id()
}

#[tauri::command]
fn setup_probe() -> setup::SetupProbe {
    setup::probe()
}

#[tauri::command]
fn setup_save_connectors(raw: String) -> Result<setup::Connectors, String> {
    setup::save_connectors(raw)
}

#[tauri::command]
fn setup_complete() -> Result<license::LicenseStatus, String> {
    license::mark_setup_complete()
}

#[tauri::command]
fn open_setup_url(url: String) -> Result<String, String> {
    web::open_license_url(&url)
}

#[tauri::command]
fn web_revoke_consent() -> Result<String, String> {
    web::run_web_cli(&["revoke"])
}

#[tauri::command]
fn web_sync_brave() -> Result<String, String> {
    let script = paths::orbit_tree().join("scripts").join("brave_grok.py");
    spawn_hidden_py(&script, &["sync"])?;
    Ok("Brave grok.com + cursor.com sync started. Brave will bounce once. Then refresh Galaxy.".into())
}

#[tauri::command]
fn web_sync_cursor_api() -> Result<String, String> {
    if CURSOR_API_IN_FLIGHT.swap(true, Ordering::SeqCst) {
        return Err("Cursor refresh already running".into());
    }
    let before = cursor_cache_probed();
    let script = paths::orbit_tree().join("scripts").join("brave_grok.py");
    if let Err(e) = spawn_hidden_py(&script, &["cursor-api"]) {
        CURSOR_API_IN_FLIGHT.store(false, Ordering::SeqCst);
        return Err(e);
    }
    std::thread::spawn(move || {
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(45) {
            if cursor_cache_probed() != before {
                break;
            }
            std::thread::sleep(Duration::from_millis(200));
        }
        CURSOR_API_IN_FLIGHT.store(false, Ordering::SeqCst);
    });
    Ok("Cursor official API refresh started. Brave will not bounce.".into())
}

#[tauri::command]
fn set_cursor_pulse(on: bool) -> Result<String, String> {
    pulse::set_cursor_pulse(on)
}

#[tauri::command]
fn cook_status() -> cook::CookState {
    cook::status()
}

#[tauri::command]
fn cook_arm() -> Result<String, String> {
    require_unlocked()?;
    cook::arm()
}

#[tauri::command]
fn cook_disarm() -> Result<String, String> {
    cook::disarm()
}

#[tauri::command]
fn cursor_followup(id: String, text: String) -> Result<String, String> {
    require_unlocked()?;
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Err("empty follow-up".into());
    }
    if !id.starts_with("web:cursor:") && !id.starts_with("bc-") {
        return Err("follow-up is only for cursor.com agents".into());
    }
    run_brave_cli(&["follow-up", &id, trimmed])
}

#[tauri::command]
fn web_open_daily(surface: String) -> Result<String, String> {
    if surface != "grok_web" && surface != "cursor_web" {
        return Err("unknown surface".into());
    }
    web::run_web_cli(&["daily", &surface])
}

#[tauri::command]
fn web_open_login(surface: String) -> Result<String, String> {
    if surface != "grok_web" && surface != "cursor_web" {
        return Err("unknown surface".into());
    }
    // Detached headed login; do not block the UI thread on the 3-minute wait.
    let script = paths::orbit_tree().join("scripts").join("web_adapters.py");
    spawn_hidden_py(&script, &["login", &surface, "--browser", "msedge"])?;
    Ok(format!("opened isolated {surface} login"))
}

#[tauri::command]
fn web_refresh(surface: String) -> Result<String, String> {
    if surface != "grok_web" && surface != "cursor_web" && surface != "all" {
        return Err("unknown surface".into());
    }
    if surface == "all" {
        let a = web::run_web_cli(&["probe", "grok_web"])?;
        let b = web::run_web_cli(&["probe", "cursor_web"])?;
        return Ok(format!("{a}\n{b}"));
    }
    web::run_web_cli(&["probe", &surface])
}

#[tauri::command]
fn get_handoff(id: String) -> Result<model::HandoffPack, String> {
    handoff::build_handoff(&id)
}

#[tauri::command]
fn handoff_to_acp(hub: tauri::State<AcpHub>, id: String) -> Result<String, String> {
    require_unlocked()?;
    let pack = handoff::build_handoff(&id)?;
    if !pack.inject_ok {
        return Err(pack
            .reason
            .unwrap_or_else(|| "handoff inject refused".into()));
    }
    let new_id = hub.new_session(&pack.acp_cwd)?;
    let _ = hub.prompt(&new_id, &pack.text)?;
    Ok(new_id)
}

#[tauri::command]
fn session_clone_path(id: String) -> Result<String, String> {
    let mut session = if web::is_web_id(&id) {
        web::find_web_session(&id).ok_or_else(|| "web session not in cache".to_string())?
    } else {
        snapshot::collect_snapshot()
            .sessions
            .into_iter()
            .find(|s| s.id == id)
            .ok_or_else(|| "session not in snapshot".to_string())?
    };
    projects::apply_link(&mut session);
    projects::clone_path_for(&session).ok_or_else(|| "no clone path".into())
}

#[tauri::command]
fn relay_focus_copy(id: String) -> Result<String, String> {
    let pack = handoff::build_handoff(&id)?;
    let snap = snapshot::collect_snapshot();
    let src = snap
        .sessions
        .iter()
        .find(|s| s.id == id)
        .ok_or_else(|| "session not in snapshot".to_string())?;
    let pid = src.project_id.clone().unwrap_or_default();
    if !projects::is_named_well(&pid) {
        return Err("no named well to relay".into());
    }
    let live = snap
        .sessions
        .iter()
        .find(|s| s.live && s.id != id && s.project_id.as_deref() == Some(pid.as_str()))
        .ok_or_else(|| "no live pager on this well".to_string())?;
    let _ = focus::focus_session(&live.id, true);
    Ok(pack.text)
}

#[tauri::command]
fn star_git_status(id: String) -> Result<git::GitPulse, String> {
    git::star_git_status(&id)
}

#[tauri::command]
fn desk_announce(note: String) -> Result<String, String> {
    let text = note.trim();
    if text.is_empty() {
        return Err("announce needs a note".into());
    }
    let script = paths::grok_home().join("desk").join("desk.py");
    if !script.exists() {
        return Err(format!("missing {}", script.display()));
    }
    let mut cmd = std::process::Command::new("py");
    cmd.arg("-3").arg(&script).arg("announce").arg("--note").arg(text);
    hide_console(&mut cmd);
    let out = cmd.output().map_err(|e| e.to_string())?;
    let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
    if !out.status.success() {
        return Err(if stderr.is_empty() { stdout } else { stderr });
    }
    Ok(if stdout.is_empty() {
        "Announced on desk".into()
    } else {
        stdout
    })
}

#[tauri::command]
fn open_session_url(id: String) -> Result<String, String> {
    if let Some(s) = web::find_web_session(&id) {
        if let Some(url) = s.url {
            return web::open_url(&url);
        }
    }
    Err("no web url for session".into())
}

#[tauri::command]
fn open_session_pr(id: String) -> Result<String, String> {
    if let Some(s) = web::find_web_session(&id) {
        if let Some(url) = s.pr_url {
            return web::open_pr_url(&url);
        }
    }
    Err("no pull request url for session".into())
}

#[tauri::command]
fn focus_session(id: String, apply: Option<bool>) -> Result<model::FocusHit, String> {
    focus::focus_session(&id, apply.unwrap_or(true))
}

#[tauri::command]
fn star_session(star: tauri::State<StarHub>) -> Option<String> {
    star.0.lock().ok().and_then(|g| g.clone())
}

#[tauri::command]
fn open_star_window(
    app: tauri::AppHandle,
    star: tauri::State<StarHub>,
    id: String,
) -> Result<String, String> {
    if !redact::is_star_id(&id) {
        return Err("invalid session id".into());
    }
    if let Ok(mut g) = star.0.lock() {
        *g = Some(id.clone());
    }
    // Never build a webview inside the invoking window's command.
    // That deadlocks WebView2: main freezes, Star stays blank.
    let app2 = app.clone();
    let id2 = id.clone();
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(40));
        let app3 = app2.clone();
        let id3 = id2.clone();
        let _ = app2.run_on_main_thread(move || {
            let _ = show_or_create_star(&app3, &id3);
        });
    });
    Ok(format!("star opening {id}"))
}

fn show_or_create_star(app: &tauri::AppHandle, id: &str) -> Result<(), String> {
    use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};
    if let Some(win) = app.get_webview_window("star") {
        let _ = win.emit("orbit-star", id);
        place_star(app, &win);
        let _ = win.unminimize();
        let _ = win.show();
        let _ = win.set_focus();
        return Ok(());
    }
    let win = WebviewWindowBuilder::new(app, "star", WebviewUrl::App("index.html".into()))
        .title("Orbit Star")
        .inner_size(760.0, 920.0)
        .background_color(tauri::window::Color(7, 8, 11, 255))
        .visible(true)
        .focused(true)
        .build()
        .map_err(|e| e.to_string())?;
    place_star(app, &win);
    let _ = win.emit("orbit-star", id);
    Ok(())
}

fn place_star(app: &tauri::AppHandle, win: &tauri::WebviewWindow) {
    use tauri::{Manager, PhysicalPosition};
    let Ok(monitors) = app.available_monitors() else {
        return;
    };
    if monitors.is_empty() {
        return;
    }
    let main_pos = app
        .get_webview_window("main")
        .and_then(|w| w.outer_position().ok());
    let secondary = monitors.iter().find(|m| {
        let p = m.position();
        match main_pos {
            Some(mp) => (mp.x - p.x).abs() > 80 || (mp.y - p.y).abs() > 80,
            None => false,
        }
    });
    let target = secondary.or(monitors.first());
    if let Some(mon) = target {
        let p = mon.position();
        let _ = win.set_position(PhysicalPosition::new(p.x + 48, p.y + 48));
    }
}

struct StarHub(Mutex<Option<String>>);

fn show_main(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.unminimize();
        let _ = win.show();
        let _ = win.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(AcpHub::new())
        .manage(StarHub(Mutex::new(None)))
        .setup(|app| {
            let hub = app.state::<AcpHub>();
            hub.set_app(app.handle().clone());

            let show = MenuItem::with_id(app, "show", "Show Orbit", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            let mut tray = TrayIconBuilder::with_id("orbit")
                .tooltip("Orbit quiet")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

            crate::cook::start_loop();
            let pulse_handle = app.handle().clone();
            std::thread::spawn(move || loop {
                std::thread::sleep(Duration::from_secs(60));
                if !pulse::cursor_pulse_enabled() || !pulse::cursor_key_present() {
                    continue;
                }
                let _ = web_sync_cursor_api();
                let snap = snapshot::collect_snapshot_ex(false);
                pulse::apply(&pulse_handle, &snap);
            });

            use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};
            let chord = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyO);
            let handle = app.handle().clone();
            if let Err(e) = app.global_shortcut().on_shortcut(chord, move |_app, _s, ev| {
                if ev.state == ShortcutState::Pressed {
                    show_main(&handle);
                }
            }) {
                eprintln!("orbit shortcut failed: {e}");
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    let _ = window.hide();
                    api.prevent_close();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_snapshot,
            search_sessions_cmd,
            get_session_detail,
            resume_session,
            open_session_cwd,
            reveal_session_dir,
            acp_state,
            acp_ensure,
            acp_new_session,
            acp_attach,
            acp_prompt,
            acp_respond,
            acp_cancel,
            focus_session,
            star_session,
            open_star_window,
            web_status,
            web_grant_consent,
            web_revoke_consent,
            web_sync_brave,
            web_sync_cursor_api,
            set_cursor_pulse,
            cook_status,
            cook_arm,
            cook_disarm,
            cursor_followup,
            web_open_daily,
            web_open_login,
            web_refresh,
            open_session_url,
            open_session_pr,
            get_handoff,
            handoff_to_acp,
            session_clone_path,
            relay_focus_copy,
            star_git_status,
            desk_announce,
            license_status,
            license_save,
            license_machine_id,
            setup_probe,
            setup_save_connectors,
            setup_complete,
            open_setup_url
        ])
        .run(tauri::generate_context!())
        .expect("error while running Grok Orbit");
}
