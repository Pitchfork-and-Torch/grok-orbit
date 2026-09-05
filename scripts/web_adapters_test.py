"""Unattended web-adapter tests. Never launches a browser."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "scripts" / "fixtures"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="orbit-web-"))
    os.environ["ORBIT_WEB_HOME"] = str(tmp)
    from web_adapters import (  # noqa: E402
        grant_consent,
        native_login_cmd,
        parse_surface,
        resolve_browser,
        revoke_consent,
        status,
        web_id,
        normalize_cursor_status,
    )

    grok_login = parse_surface(
        "grok_web",
        (FIX / "grok_web_login.html").read_text(encoding="utf-8"),
        "https://accounts.x.ai/sign-in",
    )
    assert grok_login["logged_in"] is False, grok_login
    assert grok_login["sessions"] == [], grok_login

    grok_ok = parse_surface(
        "grok_web",
        (FIX / "grok_web_logged_in.html").read_text(encoding="utf-8"),
        "https://grok.com/",
    )
    assert grok_ok["logged_in"] is True, grok_ok
    ids = {s["id"] for s in grok_ok["sessions"]}
    assert "web:grok:abc123conversation" in ids, grok_ok
    assert "web:grok:def456chat" in ids, grok_ok
    assert all(s["url"].startswith("https://grok.com/") for s in grok_ok["sessions"]), grok_ok

    cur_login = parse_surface(
        "cursor_web",
        (FIX / "cursor_web_login.html").read_text(encoding="utf-8"),
        "https://cursor.com/api/auth/login?redirect_uri=https://cursor.com/agents",
    )
    assert cur_login["logged_in"] is False, cur_login

    cur_ok = parse_surface(
        "cursor_web",
        (FIX / "cursor_web_logged_in.html").read_text(encoding="utf-8"),
        "https://cursor.com/agents",
    )
    assert cur_ok["logged_in"] is True, cur_ok
    assert {s["id"] for s in cur_ok["sessions"]} >= {
        "web:cursor:ag_hello",
        "web:cursor:ag_world",
    }, cur_ok

    assert web_id("cursor_web", "https://cursor.com/agents?id=bc-00000000-0000-0000-0000-000000000001").endswith(
        "bc-00000000-0000-0000-0000-000000000001"
    )
    assert web_id("cursor_web", "https://cursor.com/agents") != "web:cursor:agents"

    title, st = normalize_cursor_status(
        "v3.14 reclaim [BACKGROUND_COMPOSER_STATUS_RUNNING]", None
    )
    assert title == "v3.14 reclaim", title
    assert st == "running", st
    title, st = normalize_cursor_status("VELA \u2014 land", "FINISHED")
    assert " - " in title, title
    assert st == "finished", st

    browser = resolve_browser()
    assert browser.get("kind") in {"system", "bundled", "missing"}, browser
    if browser.get("kind") != "missing":
        assert browser.get("executable"), browser
        assert browser.get("name") in {"brave", "msedge", "chrome", "chromium"}, browser
        cmd = native_login_cmd("grok_web")
        assert cmd[0] == browser["executable"], cmd
        assert any(a.startswith("--user-data-dir=") for a in cmd), cmd
        assert "--new-window" in cmd, cmd
        assert any("grok.com" in a or "x.ai" in a for a in cmd), cmd
        assert all("enable-automation" not in a for a in cmd), cmd

    st = status()
    assert st["consent"]["granted"] is False, st
    assert st["copies_browser_profile"] is False, st
    assert "browser" in st, st
    assert "daily" in st, st
    assert st["daily"].get("note")
    assert st["surfaces"]["grok_web"]["status"] == "needs_consent", st
    assert st["surfaces"]["cursor_web"]["status"] == "needs_consent", st

    grant_consent()
    st2 = status()
    assert st2["consent"]["granted"] is True, st2
    assert st2["surfaces"]["grok_web"]["status"] == "unauth", st2
    assert "isolated" in (st2["surfaces"]["grok_web"]["detail"] or "").lower() or "login" in (
        st2["surfaces"]["grok_web"]["detail"] or ""
    ).lower(), st2

    revoke_consent()
    st3 = status()
    assert st3["consent"]["granted"] is False, st3
    assert not (tmp / "consent.json").exists()

    print("OK web adapters fixtures", json.dumps({"grok": len(grok_ok["sessions"]), "cursor": len(cur_ok["sessions"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
