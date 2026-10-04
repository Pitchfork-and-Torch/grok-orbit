//! Labeled demo well for empty machines. Never looks like a real project.

use crate::model::{ActivityItem, Project, Session, SessionDetail, SessionEvent};

pub const PROJECT_ID: &str = "sample";

const LIVE_ID: &str = "00000000-0000-4000-a000-000000000001";
const DONE_ID: &str = "00000000-0000-4000-a000-000000000002";
const WEB_ID: &str = "00000000-0000-4000-a000-000000000003";

pub fn is_sample_id(id: &str) -> bool {
    matches!(id, LIVE_ID | DONE_ID | WEB_ID) || id.starts_with("sample:")
}

pub fn has_real(sessions: &[Session]) -> bool {
    sessions.iter().any(|s| s.source != "sample")
}

fn sess(
    id: &str,
    title: &str,
    summary: &str,
    state: &str,
    live: bool,
    url: Option<&str>,
) -> Session {
    Session {
        id: id.into(),
        source: "sample".into(),
        project_id: Some(PROJECT_ID.into()),
        cwd: "(sample)".into(),
        title: title.into(),
        summary: summary.into(),
        state: state.into(),
        health: if live { "ok".into() } else { "idle".into() },
        pid: None,
        model: Some("sample".into()),
        agent_name: Some("sample".into()),
        created_at: None,
        updated_at: None,
        last_active_at: None,
        disk_path: None,
        url: url.map(|s| s.to_string()),
        remote: None,
        branch: None,
        pr_url: None,
        pr_state: None,
        pr_files: vec![],
        pr_file_count: None,
        live,
        has_plan: live,
    }
}

pub fn fleet() -> (Vec<Session>, Project) {
    let sessions = vec![
        sess(
            LIVE_ID,
            "Example live pager (sample)",
            "A stand-in for a live Grok CLI window. Unlock to resume real pagers.",
            "running",
            true,
            None,
        ),
        sess(
            WEB_ID,
            "Example grok.com thread (sample)",
            "A stand-in for a consented grok.com chat card.",
            "idle",
            false,
            Some("https://grok.com/"),
        ),
        sess(
            DONE_ID,
            "Example finished turn (sample)",
            "A stand-in for a closed Grok turn. Real finished cards collapse here.",
            "finished",
            false,
            None,
        ),
    ];
    let project = Project {
        id: PROJECT_ID.into(),
        name: "Sample".into(),
        paths: vec![],
        remotes: vec![],
        tags: vec!["sample".into()],
        session_ids: sessions.iter().map(|s| s.id.clone()).collect(),
        live_count: 1,
        running_count: 1,
        health: "ok".into(),
        updated_at: None,
    };
    (sessions, project)
}

pub fn attach(sessions: &mut Vec<Session>, projects: &mut Vec<Project>) {
    if has_real(sessions) {
        return;
    }
    sessions.retain(|s| s.source != "sample");
    projects.retain(|p| p.id != PROJECT_ID);
    let (ss, project) = fleet();
    sessions.extend(ss);
    projects.insert(0, project);
}

pub fn detail(id: &str) -> Option<SessionDetail> {
    let (ss, _) = fleet();
    let session = ss.into_iter().find(|s| s.id == id)?;
    Some(SessionDetail {
        session,
        plan_excerpt: Some(
            "Sample plan. Connect Grok CLI to see a real plan.md from one of your sessions.".into(),
        ),
        events: vec![SessionEvent {
            kind: "sample".into(),
            text: "This card is demo data. It is not one of your agents.".into(),
        }],
    })
}

pub fn activity() -> Vec<ActivityItem> {
    vec![ActivityItem {
        id: "sample-act-1".into(),
        session_id: LIVE_ID.into(),
        title: "Example live pager (sample)".into(),
        kind: "sample".into(),
        text: "Sample feed line. Real activity tails appear when a Grok pager is live.".into(),
        live: true,
    }]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_machine_gets_sample_only() {
        let mut sessions = vec![];
        let mut projects = vec![];
        attach(&mut sessions, &mut projects);
        assert_eq!(sessions.len(), 3);
        assert!(sessions.iter().all(|s| s.source == "sample"));
        assert_eq!(projects[0].id, PROJECT_ID);
        attach(&mut sessions, &mut projects);
        assert_eq!(sessions.len(), 3);
    }

    #[test]
    fn real_session_hides_sample() {
        let mut sessions = vec![Session {
            id: "aaaaaaaa-bbbb-4ccc-addd-eeeeeeeeeeee".into(),
            source: "grok_build".into(),
            title: "real".into(),
            ..Session::default()
        }];
        let mut projects = vec![];
        attach(&mut sessions, &mut projects);
        assert_eq!(sessions.len(), 1);
        assert_eq!(sessions[0].source, "grok_build");
    }
}
