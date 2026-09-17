//! Session age helpers. No chrono crate.

use crate::model::Session;
use std::time::{SystemTime, UNIX_EPOCH};

pub const STALE_SECS: u64 = 30 * 60;

pub fn parse_rfc3339_unix(iso: &str) -> Option<i64> {
    let s = iso.trim();
    let s = s.strip_suffix('Z').unwrap_or(s);
    if s.len() < 19 || s.as_bytes().get(10).copied() != Some(b'T') {
        return None;
    }
    let y: i32 = s[0..4].parse().ok()?;
    let mo: u32 = s[5..7].parse().ok()?;
    let d: u32 = s[8..10].parse().ok()?;
    let h: u32 = s[11..13].parse().ok()?;
    let mi: u32 = s[14..16].parse().ok()?;
    let se: u32 = s[17..19].parse().ok()?;
    if !(1..=12).contains(&mo) || !(1..=31).contains(&d) || h > 23 || mi > 59 || se > 60 {
        return None;
    }
    let days = days_from_civil(y, mo, d);
    Some(days * 86400 + i64::from(h) * 3600 + i64::from(mi) * 60 + i64::from(se))
}

fn days_from_civil(y: i32, m: u32, d: u32) -> i64 {
    let mut y = i64::from(y);
    let m = i64::from(m);
    let d = i64::from(d);
    y -= i64::from(m <= 2);
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

pub fn age_secs_now(iso: &str) -> Option<u64> {
    let then = parse_rfc3339_unix(iso)?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs() as i64;
    Some(now.saturating_sub(then).max(0) as u64)
}

pub fn session_when(session: &Session) -> Option<&str> {
    session
        .last_active_at
        .as_deref()
        .or(session.updated_at.as_deref())
        .or(session.created_at.as_deref())
}

pub fn is_stale_live(session: &Session) -> bool {
    session.live
        && session_when(session)
            .and_then(age_secs_now)
            .map(|a| a >= STALE_SECS)
            .unwrap_or(false)
}

pub fn format_age_seconds(sec: u64) -> String {
    if sec < 60 {
        format!("{sec}s")
    } else if sec < 3600 {
        format!("{}m", sec / 60)
    } else if sec < 86400 {
        format!("{}h", sec / 3600)
    } else {
        format!("{}d", sec / 86400)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unix_epoch_day_two() {
        assert_eq!(parse_rfc3339_unix("1970-01-02T00:00:00Z"), Some(86400));
        assert_eq!(
            parse_rfc3339_unix("2026-08-14T14:57:23.416Z"),
            parse_rfc3339_unix("2026-08-14T14:57:23Z")
        );
        assert!(parse_rfc3339_unix("nope").is_none());
        assert_eq!(format_age_seconds(90), "1m");
        assert_eq!(format_age_seconds(7200), "2h");
    }
}
