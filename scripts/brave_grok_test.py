"""Unattended tests for daily-Brave grok.com / cursor.com sync. No live cookies printed."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from brave_grok import (
    CURSOR_HOSTS,
    cursor_done_payload,
    extract_crsr,
    followup_body,
    format_age_seconds,
    host_allowed,
    is_agent_busy,
    list_fingerprint,
    parse_conversations,
    parse_cursor_agents,
    pick_timestamp,
    pulse_should_skip,
    write_cursor_done,
    write_cursor_pulse,
)


def main() -> int:
    assert host_allowed(".grok.com")
    assert host_allowed("accounts.x.ai")
    assert host_allowed("grok.com")
    assert not host_allowed("google.com")
    assert not host_allowed("evil-grok.com.attacker.example")
    assert host_allowed("www.cursor.com", CURSOR_HOSTS)
    assert host_allowed(".cursor.com", CURSOR_HOSTS)
    assert not host_allowed("notcursor.com", CURSOR_HOSTS)

    sessions = parse_conversations(
        {
            "conversations": [
                {"conversation_id": "abc123conversation", "title": "Night Range"},
                {"id": "def456", "name": "Other"},
            ]
        }
    )
    assert sessions[0]["id"] == "web:grok:abc123conversation"
    assert sessions[0]["url"] == "https://grok.com/c/abc123conversation"
    assert "Night Range" in sessions[0]["title"]

    agents = parse_cursor_agents(
        {
            "items": [
                {
                    "id": "bc-00000000-0000-0000-0000-000000000001",
                    "name": "Add README",
                    "status": "ACTIVE",
                    "url": "https://cursor.com/agents/bc-00000000-0000-0000-0000-000000000001",
                },
                {
                    "id": "bc-11111111-1111-1111-1111-111111111111",
                    "name": "vela-interval",
                    "status": "RUNNING",
                    "target": {"url": "https://cursor.com/agents?id=bc-11111111-1111-1111-1111-111111111111"},
                    "updatedAt": "2026-08-14T12:00:00Z",
                    "git": {
                        "branches": [
                            {
                                "name": "cursor/vela-interval",
                                "prUrl": "https://github.com/Pitchfork-and-Torch/vela/pull/8",
                            }
                        ]
                    },
                },
            ]
        }
    )
    assert agents[0]["id"] == "web:cursor:bc-00000000-0000-0000-0000-000000000001"
    assert agents[0]["url"].startswith("https://cursor.com/agents/")
    assert agents[0]["title"] == "Add README"
    assert agents[0]["status"] == "active"
    assert agents[1]["id"].endswith("bc-11111111-1111-1111-1111-111111111111")
    assert agents[1]["status"] == "running"
    assert agents[1]["pr_url"].endswith("/pull/8")
    assert agents[1]["branch"] == "cursor/vela-interval"
    assert agents[1]["updated_at"] == "2026-08-14T12:00:00Z"
    assert extract_crsr("note\ncrsr_testkeyvalue0123456789\n") == "crsr_testkeyvalue0123456789"
    assert extract_crsr("nope") is None

    done = cursor_done_payload(
        [
            {"id": "web:cursor:a", "status": "finished"},
            {"id": "web:cursor:b", "status": "running"},
            {"id": "web:cursor:c", "status": "active"},
        ],
        1234,
        "2026-08-14T16:00:00Z",
    )
    assert done["count"] == 3
    assert done["running"] == 1
    assert done["elapsed_ms"] == 1234
    assert done["probed_at"] == "2026-08-14T16:00:00Z"

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "cursor_web.done.json"
        wrote = write_cursor_done(
            [{"status": "running"}, {"status": "finished"}],
            88,
            "2026-08-14T16:01:00Z",
            dest,
        )
        payload = json.loads(wrote.read_text(encoding="utf-8"))
        assert payload["count"] == 2
        assert payload["running"] == 1
        assert payload["elapsed_ms"] == 88

    assert pick_timestamp({"updatedAt": "2026-08-14T12:00:00Z"}) == "2026-08-14T12:00:00Z"
    assert format_age_seconds(12) == "12s"
    assert format_age_seconds(90) == "1m"
    assert format_age_seconds(7200) == "2h"
    assert format_age_seconds(200000) == "2d"

    assert followup_body("Also add tests") == {"prompt": {"text": "Also add tests"}}
    assert is_agent_busy("RUNNING")
    assert is_agent_busy("CREATING")
    assert not is_agent_busy("FINISHED")
    assert not is_agent_busy("ACTIVE")

    fp1 = list_fingerprint(
        [
            {"id": "web:cursor:a", "status": "finished", "updated_at": "2026-08-14T12:00:00Z"},
            {"id": "web:cursor:b", "status": "active", "updated_at": "2026-08-14T12:01:00Z"},
        ]
    )
    fp2 = list_fingerprint(
        [
            {"id": "web:cursor:b", "status": "active", "updated_at": "2026-08-14T12:01:00Z"},
            {"id": "web:cursor:a", "status": "finished", "updated_at": "2026-08-14T12:00:00Z"},
        ]
    )
    fp3 = list_fingerprint(
        [
            {"id": "web:cursor:a", "status": "running", "updated_at": "2026-08-14T12:00:00Z"},
            {"id": "web:cursor:b", "status": "active", "updated_at": "2026-08-14T12:01:00Z"},
        ]
    )
    assert fp1 == fp2
    assert fp1 != fp3
    assert pulse_should_skip({"fingerprint": fp1}, fp1, [{"id": "a"}])
    assert not pulse_should_skip({"fingerprint": fp1}, fp3, [{"id": "a"}])
    assert not pulse_should_skip({}, fp1, [{"id": "a"}])

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "cursor_web.pulse.json"
        wrote = write_cursor_pulse(fp1, True, 2, dest)
        pulse = json.loads(wrote.read_text(encoding="utf-8"))
        assert pulse["fingerprint"] == fp1
        assert pulse["skipped"] is True
        assert pulse["count"] == 2
        assert pulse.get("probed_at")

    print("OK brave_grok parse", len(sessions), "cursor", len(agents), "done-sidecar followup pulse-fp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
