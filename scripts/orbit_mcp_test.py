"""Unattended MCP handshake for Orbit. No GUI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts" / "orbit_mcp.py"


def send(proc: subprocess.Popen, msg: dict) -> dict | None:
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if msg.get("method", "").startswith("notifications/"):
        return None
    line = proc.stdout.readline()
    return json.loads(line)


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
    )
    try:
        init = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "orbit-mcp-test", "version": "0.6.0"},
                },
            },
        )
        assert init and init.get("result", {}).get("serverInfo", {}).get("name") == "grok-orbit", init
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        listed = send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {t["name"] for t in listed["result"]["tools"]}
        assert names == {
            "orbit_snapshot",
            "orbit_search",
            "orbit_session_detail",
            "orbit_resume",
            "orbit_focus",
            "orbit_web_status",
            "orbit_handoff",
            "orbit_next",
            "orbit_well",
            "orbit_relay_pack",
        }, names
        called = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "orbit_snapshot", "arguments": {}},
            },
        )
        text = called["result"]["content"][0]["text"]
        body = json.loads(text)
        assert "situation" in body, body
        assert "surfaces" in body, body
        assert "web" in body, body
        assert "grok_chats" in (body.get("web") or {}), body.get("web")
        assert "activity" in body, body
        searched = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "orbit_search", "arguments": {"query": "orbit", "limit": 5}},
            },
        )
        hits = json.loads(searched["result"]["content"][0]["text"]).get("hits") or []
        assert isinstance(hits, list), hits
        live = body.get("live") or []
        if live:
            focused = send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "orbit_focus",
                        "arguments": {"id": live[0]["id"], "apply": False},
                    },
                },
            )
            focus_body = json.loads(focused["result"]["content"][0]["text"])
            assert focus_body.get("hwnd") or focus_body.get("error"), focus_body
            print("OK orbit focus resolve", focus_body.get("via") or focus_body.get("error"))
        web = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "orbit_web_status", "arguments": {}},
            },
        )
        web_body = json.loads(web["result"]["content"][0]["text"])
        assert web_body.get("copies_browser_profile") is False, web_body
        assert "surfaces" in web_body, web_body
        nxt = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "orbit_next", "arguments": {}},
            },
        )
        nxt_body = json.loads(nxt["result"]["content"][0]["text"])
        assert "suggested_hop" in nxt_body, nxt_body
        assert nxt_body.get("cheap") is True, nxt_body
        well = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "orbit_well", "arguments": {"project": "vela"}},
            },
        )
        well_body = json.loads(well["result"]["content"][0]["text"])
        assert "members" in well_body, well_body
        assert well_body.get("cheap") is True, well_body
        leo = send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "orbit_well", "arguments": {"project": "leoaware"}},
            },
        )
        leo_body = json.loads(leo["result"]["content"][0]["text"])
        assert "members" in leo_body, leo_body
        print("OK orbit mcp", body.get("elapsed_ms"), "ms", (body.get("situation") or "")[:140], "hits", len(hits))
        print("OK orbit next", nxt_body.get("suggested_hop"), "well", well_body.get("count"))
        print("OK orbit web status", web_body.get("surfaces", {}).get("grok_web", {}).get("status"))
        if live:
            handed = send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {"name": "orbit_handoff", "arguments": {"id": live[0]["id"]}},
                },
            )
            pack = json.loads(handed["result"]["content"][0]["text"])
            assert pack.get("inject_ok") is False, pack
            assert "ORBIT HANDOFF" in (pack.get("text") or ""), pack
            print("OK orbit handoff refuse", pack.get("reason"))
        return 0
    except Exception as e:
        err = ""
        if proc.stderr:
            try:
                err = proc.stderr.read()
            except Exception:
                pass
        print("FAIL", type(e).__name__, e, err[-400:])
        return 1
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
