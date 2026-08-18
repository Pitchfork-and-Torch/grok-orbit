//! Local license file. Paid keys are issued by orbit.jonbailey.xyz.
//! Debug builds and existing operator data homes are grandfathered.

use crate::paths;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

pub const LICENSE_API: &str = "https://orbit.jonbailey.xyz";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LicenseFile {
    pub key: String,
    pub email: String,
    #[serde(default)]
    pub machine_id: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub activated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LicenseStatus {
    pub licensed: bool,
    pub unlocked: bool,
    #[serde(default = "default_observe")]
    pub observe: bool,
    pub setup_complete: bool,
    pub source: String,
    pub email: String,
    pub api: String,
    pub machine_id: String,
    pub debug: bool,
}

fn default_observe() -> bool {
    true
}

fn license_path() -> PathBuf {
    paths::orbit_data_home().join("license.json")
}

fn setup_flag_path() -> PathBuf {
    paths::orbit_data_home().join("setup.json")
}

pub fn machine_id() -> String {
    let raw = format!(
        "{}|{}|{}",
        std::env::var("COMPUTERNAME").unwrap_or_default(),
        std::env::var("USERNAME").unwrap_or_default(),
        std::env::var("PROCESSOR_IDENTIFIER").unwrap_or_default()
    );
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in raw.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100_0000_01b3);
    }
    format!("ORB-{h:016X}")
}

fn read_license() -> Option<LicenseFile> {
    let text = fs::read_to_string(license_path()).ok()?;
    serde_json::from_str(&text).ok()
}

fn write_json(path: &std::path::Path, value: &impl Serialize) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    fs::write(path, text).map_err(|e| e.to_string())
}

fn now_iso() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{secs}")
}

fn grandfather_ok() -> bool {
    if cfg!(debug_assertions) {
        return true;
    }
    if std::env::var("ORBIT_LICENSE_BYPASS").ok().as_deref() == Some("1") {
        return true;
    }
    paths::orbit_db_path().exists()
}

pub fn setup_complete() -> bool {
    setup_flag_path().exists()
}

pub fn mark_setup_complete() -> Result<LicenseStatus, String> {
    write_json(
        &setup_flag_path(),
        &serde_json::json!({
            "complete": true,
            "at": now_iso(),
        }),
    )?;
    Ok(status())
}

pub fn status() -> LicenseStatus {
    let mid = machine_id();
    if let Some(lic) = read_license() {
        if !lic.key.trim().is_empty() {
            let unlocked = key_looks_ok(&lic.key);
            return LicenseStatus {
                licensed: unlocked,
                unlocked,
                observe: true,
                setup_complete: setup_complete(),
                source: if lic.source.is_empty() {
                    "file".into()
                } else {
                    lic.source
                },
                email: lic.email,
                api: LICENSE_API.into(),
                machine_id: mid,
                debug: cfg!(debug_assertions),
            };
        }
    }
    if grandfather_ok() {
        let _ = save_license(LicenseFile {
            key: "ORBIT-LOCAL-GRANDFATHER".into(),
            email: String::new(),
            machine_id: mid.clone(),
            source: if cfg!(debug_assertions) {
                "dev".into()
            } else {
                "grandfather".into()
            },
            activated_at: now_iso(),
        });
        // Existing operator data: do not force the wizard again.
        if paths::orbit_db_path().exists() {
            let _ = mark_setup_complete();
        }
        return LicenseStatus {
            licensed: true,
            unlocked: true,
            observe: true,
            setup_complete: setup_complete(),
            source: if cfg!(debug_assertions) {
                "dev".into()
            } else {
                "grandfather".into()
            },
            email: String::new(),
            api: LICENSE_API.into(),
            machine_id: mid,
            debug: cfg!(debug_assertions),
        };
    }
    LicenseStatus {
        licensed: false,
        unlocked: false,
        observe: true,
        setup_complete: setup_complete(),
        source: "none".into(),
        email: String::new(),
        api: LICENSE_API.into(),
        machine_id: mid,
        debug: cfg!(debug_assertions),
    }
}

pub fn unlocked() -> bool {
    status().unlocked
}

pub fn require_unlocked() -> Result<(), String> {
    if unlocked() {
        return Ok(());
    }
    Err("Observe is free. Unlock ($19) to resume, COOK, ACP, or hand off.".into())
}

pub fn save_license(mut lic: LicenseFile) -> Result<LicenseStatus, String> {
    let key = normalize_key(&lic.key);
    if !key_looks_ok(&key) {
        return Err("That does not look like an Orbit license key.".into());
    }
    lic.key = key;
    if lic.machine_id.is_empty() {
        lic.machine_id = machine_id();
    }
    if lic.activated_at.is_empty() {
        lic.activated_at = now_iso();
    }
    if lic.source.is_empty() {
        lic.source = "paid".into();
    }
    write_json(&license_path(), &lic)?;
    Ok(status())
}

pub fn save_license_json(raw: String) -> Result<LicenseStatus, String> {
    let lic: LicenseFile = serde_json::from_str(&raw).map_err(|e| e.to_string())?;
    save_license(lic)
}

pub fn normalize_key(raw: &str) -> String {
    raw.chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-')
        .collect::<String>()
        .to_ascii_uppercase()
}

pub fn key_looks_ok(key: &str) -> bool {
    if key == "ORBIT-LOCAL-GRANDFATHER" {
        return true;
    }
    let parts: Vec<&str> = key.split('-').collect();
    parts.len() >= 4 && parts[0] == "ORBIT" && parts.iter().all(|p| !p.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_and_accepts_orbit_keys() {
        let k = normalize_key(" orbit-ab12-cd34-ef56 ");
        assert_eq!(k, "ORBIT-AB12-CD34-EF56");
        assert!(key_looks_ok(&k));
        assert!(!key_looks_ok("SPDR-AAAA-BBBB"));
        assert!(key_looks_ok("ORBIT-LOCAL-GRANDFATHER"));
    }

    #[test]
    fn observe_is_always_on() {
        let st = LicenseStatus {
            licensed: false,
            unlocked: false,
            observe: true,
            setup_complete: false,
            source: "none".into(),
            email: String::new(),
            api: LICENSE_API.into(),
            machine_id: "x".into(),
            debug: false,
        };
        assert!(st.observe);
        assert!(!st.unlocked);
    }
}
