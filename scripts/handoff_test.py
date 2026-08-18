"""Unattended handoff pack tests. Never starts ACP. Never injects."""

from __future__ import annotations

import json
from pathlib import Path

import handoff
from snapshot import grok_home, redact


def main() -> int:
    dirty = redact("token ghp_exampleplaceholder000000 x")
    assert dirty == "token [redacted] x", dirty

    path = grok_home() / "active_sessions.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    live = [r for r in rows if isinstance(r, dict) and r.get("session_id")]
    if live:
        pack = handoff.build_handoff(str(live[0]["session_id"]))
        assert "error" not in pack, pack
        assert pack["live"] is True, pack
        assert pack["inject_ok"] is False, pack
        assert "ORBIT HANDOFF" in pack["text"], pack["text"]
        assert "Do not inject" in pack["text"], pack["text"]
        assert "ghp_" not in pack["text"]
        print("OK handoff live refuse", pack["session_id"][:8], pack.get("reason"))
    else:
        print("OK handoff skipped (no live pager)")

    # Package a disk session if the snapshot has one that is not live.
    from snapshot import build

    snap = build()
    disk = next((s for s in snap.get("sessions") or [] if not s.get("live") and not str(s.get("id")).startswith("web:")), None)
    if disk:
        pack = handoff.build_handoff(disk["id"])
        assert "error" not in pack, pack
        assert pack["live"] is False, pack
        assert "ORBIT HANDOFF" in pack["text"]
        print("OK handoff disk pack", disk["id"][:8], "inject", pack["inject_ok"])

    web = next(
        (
            s
            for s in snap.get("sessions") or []
            if str(s.get("id") or "").startswith("web:cursor:") and s.get("agent_name") == "running"
        ),
        None,
    )
    if web:
        pack = handoff.build_handoff(web["id"])
        assert "error" not in pack, pack
        assert pack["live"] is False, pack
        assert "project:" in pack["text"], pack["text"]
        clone = pack.get("acp_cwd") or ""
        if clone:
            assert "cursor.com" not in clone.lower(), clone
            assert pack["inject_ok"] is True, pack
            print("OK handoff cursor clone", pack.get("acp_cwd"), pack.get("reason"))
        else:
            assert pack["inject_ok"] is False, pack
            print("OK handoff cursor no-clone", pack.get("reason"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
