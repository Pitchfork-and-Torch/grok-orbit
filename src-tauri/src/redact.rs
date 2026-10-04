use regex::Regex;
use std::sync::OnceLock;

static SECRET_RE: OnceLock<Regex> = OnceLock::new();

fn secret_re() -> &'static Regex {
    SECRET_RE.get_or_init(|| {
        Regex::new(
            r"(?i)(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xai-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})",
        )
        .expect("secret regex")
    })
}

pub fn redact(text: &str) -> String {
    secret_re().replace_all(text, "[redacted]").into_owned()
}

pub fn is_star_id(id: &str) -> bool {
    is_session_id(id) || crate::web::is_web_id(id)
}

pub fn is_session_id(id: &str) -> bool {
    let b = id.as_bytes();
    if b.len() != 36 {
        return false;
    }
    for (i, c) in b.iter().copied().enumerate() {
        if i == 8 || i == 13 || i == 18 || i == 23 {
            if c != b'-' {
                return false;
            }
        } else if !c.is_ascii_hexdigit() {
            return false;
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_tokens() {
        assert_eq!(
            redact("key ghp_exampleplaceholder000000 hide"),
            "key [redacted] hide"
        );
    }

    #[test]
    fn accepts_uuid() {
        assert!(is_session_id("01a00022-b643-7b40-9d7e-dc185c67e3c2"));
        assert!(!is_session_id("../auth.json"));
        assert!(is_star_id("web:cursor:bc-00000000-0000-0000-0000-000000000001"));
        assert!(is_star_id("web:grok:abc123conversation"));
        assert!(!is_star_id("javascript:alert(1)"));
    }
}
