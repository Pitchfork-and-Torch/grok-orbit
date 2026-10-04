//! First-run surface probe. Never read token/key file contents into logs.

use crate::paths;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Surface {
    pub id: String,
    pub label: String,
    pub status: String,
    pub detail: String,
    pub hint: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetupProbe {
    pub grok_home: String,
    pub python: bool,
    pub scripts: bool,
    pub surfaces: Vec<Surface>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Connectors {
    #[serde(default)]
    pub openai: String,
    #[serde(default)]
    pub anthropic: String,
    #[serde(default)]
    pub gemini: String,
    #[serde(default)]
    pub xai: String,
    #[serde(default)]
    pub cursor: String,
}

fn exists_file(p: &Path) -> bool {
    p.is_file()
}

fn which(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let cand = dir.join(name);
        if cand.is_file() {
            return Some(cand);
        }
        #[cfg(windows)]
        {
            let exe = dir.join(format!("{name}.exe"));
            if exe.is_file() {
                return Some(exe);
            }
            let cmd = dir.join(format!("{name}.cmd"));
            if cmd.is_file() {
                return Some(cmd);
            }
        }
    }
    None
}

fn grok_bot_exe() -> Option<PathBuf> {
    let local = std::env::var_os("LOCALAPPDATA").map(PathBuf::from)?;
    let p = local.join("Programs").join("Grok Bot").join("Grok Bot.exe");
    if p.is_file() {
        Some(p)
    } else {
        None
    }
}

fn python_ok() -> bool {
    which("py").is_some() || which("python").is_some() || which("python3").is_some()
}

fn connector_present(value: &str) -> bool {
    let t = value.trim();
    t.len() >= 8 && !t.contains("YOUR_") && !t.contains("sk-...")
}

fn mask(value: &str) -> String {
    let t = value.trim();
    if t.len() < 8 {
        return String::new();
    }
    format!("{}...{}", &t[..4], &t[t.len() - 3..])
}

pub fn connectors_path() -> PathBuf {
    paths::orbit_data_home().join("connectors.json")
}

pub fn read_connectors() -> Connectors {
    fs::read_to_string(connectors_path())
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

pub fn save_connectors(raw: String) -> Result<Connectors, String> {
    let incoming: Connectors = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
    let mut cur = read_connectors();
    if !incoming.openai.trim().is_empty() {
        cur.openai = incoming.openai.trim().to_string();
    }
    if !incoming.anthropic.trim().is_empty() {
        cur.anthropic = incoming.anthropic.trim().to_string();
    }
    if !incoming.gemini.trim().is_empty() {
        cur.gemini = incoming.gemini.trim().to_string();
    }
    if !incoming.xai.trim().is_empty() {
        cur.xai = incoming.xai.trim().to_string();
    }
    if !incoming.cursor.trim().is_empty() {
        cur.cursor = incoming.cursor.trim().to_string();
        let key_path = paths::orbit_web_home().join("cursor_api_key.txt");
        if let Some(parent) = key_path.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        fs::write(key_path, cur.cursor.trim()).map_err(|e| e.to_string())?;
    }
    if let Some(parent) = connectors_path().parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(&cur).map_err(|e| e.to_string())?;
    fs::write(connectors_path(), text).map_err(|e| e.to_string())?;
    Ok(cur)
}

pub fn probe() -> SetupProbe {
    let home = paths::grok_home();
    let grok_bin = paths::grok_bin(&home);
    let grok_on_path = which("grok");
    let grok_ok = exists_file(&grok_bin) || grok_on_path.is_some();
    let grok_detail = if exists_file(&grok_bin) {
        grok_bin.display().to_string()
    } else if let Some(p) = grok_on_path {
        p.display().to_string()
    } else {
        "grok.exe not found. Install Grok Build CLI, then Refresh.".into()
    };

    let bot = grok_bot_exe();
    let bot_ok = bot.is_some();
    let bot_detail = match &bot {
        Some(p) => p.display().to_string(),
        None => "Grok Bot desktop is not installed.".into(),
    };

    let consent = paths::orbit_web_home().join("consent.json");
    let web_ok = consent.is_file();
    let scripts = paths::orbit_tree()
        .join("scripts")
        .join("brave_grok.py")
        .is_file();
    let py = python_ok();

    let cons = read_connectors();
    let cursor_file = paths::orbit_web_home().join("cursor_api_key.txt");
    let cursor_ok = connector_present(&cons.cursor) || cursor_file.is_file();

    let surfaces = vec![
        Surface {
            id: "grok_cli".into(),
            label: "Grok CLI".into(),
            status: if grok_ok { "ok".into() } else { "missing".into() },
            detail: grok_detail,
            hint: "Install Grok Build. Orbit reads local sessions only. It never writes auth.json."
                .into(),
        },
        Surface {
            id: "grok_bot".into(),
            label: "Grok Bot".into(),
            status: if bot_ok { "ok".into() } else { "missing".into() },
            detail: bot_detail,
            hint: "Install the Grok Bot desktop app. Orbit shows process status, never token files."
                .into(),
        },
        Surface {
            id: "grok_web".into(),
            label: "grok.com".into(),
            status: if web_ok { "ok".into() } else { "needs_consent".into() },
            detail: if web_ok {
                "Web consent is on this machine.".into()
            } else if scripts && py {
                "Grant consent, then sync Brave once.".into()
            } else {
                "Optional. Needs Python plus bundled Orbit scripts.".into()
            },
            hint: "Lists grok.com chats after a consented Brave bounce. Cookies are not stored."
                .into(),
        },
        Surface {
            id: "cursor".into(),
            label: "Cursor Cloud Agents".into(),
            status: if cursor_ok { "ok".into() } else { "optional".into() },
            detail: if cursor_ok {
                "API key is on disk.".into()
            } else {
                "Paste a Cursor Dashboard key to list cloud agents.".into()
            },
            hint: "Key stays in LocalAppData. Never sent with Brave cookies.".into(),
        },
        Surface {
            id: "openai".into(),
            label: "OpenAI".into(),
            status: if connector_present(&cons.openai) {
                "ok".into()
            } else {
                "optional".into()
            },
            detail: if connector_present(&cons.openai) {
                format!("Key saved ({})", mask(&cons.openai))
            } else {
                "Optional API key. Saved locally. No ChatGPT session scrape.".into()
            },
            hint: "For later model routing. Orbit does not read the ChatGPT desktop app.".into(),
        },
        Surface {
            id: "anthropic".into(),
            label: "Anthropic".into(),
            status: if connector_present(&cons.anthropic) {
                "ok".into()
            } else {
                "optional".into()
            },
            detail: if connector_present(&cons.anthropic) {
                format!("Key saved ({})", mask(&cons.anthropic))
            } else {
                "Optional API key. Saved locally.".into()
            },
            hint: "Stored on this PC only.".into(),
        },
        Surface {
            id: "gemini".into(),
            label: "Gemini".into(),
            status: if connector_present(&cons.gemini) {
                "ok".into()
            } else {
                "optional".into()
            },
            detail: if connector_present(&cons.gemini) {
                format!("Key saved ({})", mask(&cons.gemini))
            } else {
                "Optional API key. Saved locally.".into()
            },
            hint: "Stored on this PC only.".into(),
        },
        Surface {
            id: "xai".into(),
            label: "xAI API".into(),
            status: if connector_present(&cons.xai) {
                "ok".into()
            } else {
                "optional".into()
            },
            detail: if connector_present(&cons.xai) {
                format!("Key saved ({})", mask(&cons.xai))
            } else {
                "Optional. Separate from Grok CLI login.".into()
            },
            hint: "console.x.ai key, if you want API calls besides the local CLI.".into(),
        },
    ];

    SetupProbe {
        grok_home: home.display().to_string(),
        python: py,
        scripts,
        surfaces,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn connector_gate() {
        assert!(!connector_present(""));
        assert!(!connector_present("sk-..."));
        assert!(connector_present("sk-proj-abcdefghijk"));
        assert_eq!(mask("sk-abcdefghij"), "sk-a...hij");
    }
}
