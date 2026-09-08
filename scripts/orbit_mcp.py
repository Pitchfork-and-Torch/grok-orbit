"""Grok Orbit MCP (stdio). Read-local fleet tools. No token files. No live-TUI inject."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from snapshot import (  # noqa: E402
    UUID_RE,
    build,
    encode_cwd,
    grok_home,
    pid_alive,
    redact,
)
from focus import focus_pid  # noqa: E402
from handoff import build_handoff  # noqa: E402
from projects import is_named_well, member_kind  # noqa: E402


def session_dir(home, cwd: str, sid: str):
    return home / "sessions" / encode_cwd(cwd) / sid

PROTOCOL = "2024-11-05"
HOME = Path(os.environ.get("USERPROFILE") or Path.home())
GROK = HOME / ".grok" / "bin" / "grok.exe"


def compact(snap: dict) -> dict:
    lives = [s for s in snap.get("sessions") or [] if s.get("live")]
    return {
        "situation": snap.get("situation"),
        "elapsed_ms": snap.get("elapsed_ms"),
        "adapters": snap.get("adapters"),
        "surfaces": snap.get("surfaces"),
        "attention": snap.get("attention"),
        "activity": (snap.get("activity") or [])[:12],
        "web": {
            "consent": (snap.get("surfaces") or {}).get("web_consent"),
            "grok": (snap.get("surfaces") or {}).get("grok_web"),
            "cursor": (snap.get("surfaces") or {}).get("cursor_web"),
            "grok_chats": [
                {"id": s.get("id"), "title": s.get("title"), "url": s.get("url")}
                for s in (snap.get("sessions") or [])
                if str(s.get("id") or "").startswith("web:grok:")
            ][:20],
            "cursor_chats": [
                {"id": s.get("id"), "title": s.get("title"), "url": s.get("url")}
                for s in (snap.get("sessions") or [])
                if str(s.get("id") or "").startswith("web:cursor:")
            ][:20],
            "cursor_running": [
                {"id": s.get("id"), "title": s.get("title"), "url": s.get("url")}
                for s in (snap.get("sessions") or [])
                if str(s.get("id") or "").startswith("web:cursor:")
                and s.get("agent_name") == "running"
            ],
            "projects": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "health": p.get("health"),
                    "running": p.get("running_count") or 0,
                    "live": p.get("live_count") or 0,
                }
                for p in (snap.get("projects") or [])[:16]
            ],
        },
        "project_count": len(snap.get("projects") or []),
        "session_count": len(snap.get("sessions") or []),
        "live": [
            {
                "id": s.get("id"),
                "title": s.get("title"),
                "cwd": s.get("cwd"),
                "pid": s.get("pid"),
                "model": s.get("model"),
                "agent_name": s.get("agent_name"),
            }
            for s in lives
        ],
    }


def search_sessions(query: str, limit: int = 20) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    db = grok_home() / "sessions" / "session_search.sqlite"
    if not db.exists():
        return []
    cleaned = "".join(ch if ch.isalnum() or ch == " " else " " for ch in q)
    parts = [f"{w}*" for w in cleaned.split() if w]
    if not parts:
        return []
    fts = " ".join(parts)
    con = sqlite3.connect(str(db), timeout=1.0)
    try:
        cur = con.execute(
            """
            SELECT d.session_id, d.cwd, d.updated_at, d.title,
                   snippet(session_docs_fts, 1, '', '', ' ... ', 16)
            FROM session_docs_fts f
            JOIN session_docs d ON d.rowid = f.rowid
            WHERE session_docs_fts MATCH ?
            ORDER BY d.updated_at DESC
            LIMIT ?
            """,
            (fts, limit),
        )
        live = live_ids()
        out = []
        for sid, cwd, updated, title, snippet in cur.fetchall():
            if not UUID_RE.match(str(sid)):
                continue
            snip = redact((snippet or "").strip())[:220] or redact(title)[:180]
            out.append(
                {
                    "id": sid,
                    "cwd": cwd,
                    "updated_at": updated,
                    "title": redact(title)[:180],
                    "snippet": snip,
                    "live": sid in live,
                }
            )
        return out
    finally:
        con.close()


def session_detail(sid: str) -> dict:
    if str(sid).startswith("web:"):
        from web_adapters import status as web_status

        st = web_status()
        hit = next((s for s in st.get("sessions") or [] if s.get("id") == sid), None)
        if not hit:
            return {"error": "web session not in cache", "id": sid}
        return {"session": hit, "events": []}
    if not UUID_RE.match(sid):
        return {"error": "invalid session id"}
    snap = build()
    hit = next((s for s in snap.get("sessions") or [] if s.get("id") == sid), None)
    if not hit:
        return {"error": "not in snapshot", "id": sid}
    home = grok_home()
    disk = Path(hit["disk_path"]) if hit.get("disk_path") else session_dir(home, hit.get("cwd") or "", sid)
    events = []
    updates = disk / "updates.jsonl"
    if updates.exists():
        data = updates.read_bytes()
        tail = data[-48000:]
        text = tail.decode("utf-8", errors="replace")
        if len(data) > 48000:
            text = text.split("\n", 1)[-1]
        for line in text.splitlines()[-40:]:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            upd = ((obj.get("params") or {}).get("update")) or {}
            kind = upd.get("sessionUpdate") or "update"
            if kind in ("user_message_chunk", "agent_message_chunk", "agent_thought_chunk"):
                body = ((upd.get("content") or {}).get("text")) or ""
            else:
                body = upd.get("title") or kind
            body = redact(body.strip())
            if body:
                events.append({"kind": kind, "text": body[:400]})
    return {"session": hit, "events": events[-40:]}


def live_ids() -> set[str]:
    path = grok_home() / "active_sessions.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return set()
    out = set()
    for row in rows if isinstance(rows, list) else []:
        sid = str(row.get("session_id") or "")
        pid = int(row.get("pid") or 0)
        if UUID_RE.match(sid) and pid_alive(pid):
            out.add(sid)
    return out


def focus_session(sid: str, apply: bool = True) -> dict:
    if not UUID_RE.match(sid):
        return {"error": "invalid session id"}
    if sid not in live_ids():
        return {"error": "not a live TUI pager; use orbit_resume"}
    snap = build()
    hit = next((s for s in snap.get("sessions") or [] if s.get("id") == sid), None)
    pid = int((hit or {}).get("pid") or 0)
    if pid <= 0:
        return {"error": "live session has no pid"}
    out = focus_pid(pid, apply=apply)
    out["session_id"] = sid
    return out


def orbit_next() -> dict:
    from snapshot import build_next

    return build_next()


def orbit_well(project: str) -> dict:
    from snapshot import live_sessions, desk_attention, grok_home
    from projects import assign_slug, build_catalog

    slug = (project or "").strip().lower()
    if not slug:
        return {"error": "project required"}
    cat = build_catalog()
    live, _ = live_sessions(grok_home())
    desk_rows, _ = desk_attention(grok_home())
    pool = list(live)
    try:
        from web_adapters import cache_path, read_json
        from pr_state import apply_to_sessions

        cache = read_json(cache_path("cursor_web")) or {}
        extra = []
        for item in cache.get("sessions") or []:
            if not isinstance(item, dict):
                continue
            extra.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "source": "cursor_web",
                    "cwd": "cursor.com",
                    "agent_name": item.get("status") or item.get("agent_name"),
                    "pr_url": item.get("pr_url"),
                    "live": False,
                }
            )
        apply_to_sessions(extra)
        pool.extend(extra)
    except Exception:
        pass
    members = []
    for s in pool:
        if not s.get("project_id"):
            s["project_id"] = assign_slug(s, cat)
        pid = str(s.get("project_id") or "").lower()
        if pid != slug and slug not in pid:
            continue
        members.append(
            {
                "id": s.get("id"),
                "title": s.get("title"),
                "source": s.get("source"),
                "kind": member_kind(s),
                "live": bool(s.get("live")),
                "pr_state": s.get("pr_state"),
                "pr_url": s.get("pr_url"),
                "pid": s.get("pid"),
            }
        )
    desk = [
        {"id": a.get("id"), "title": a.get("title"), "session_id": a.get("session_id")}
        for a in desk_rows
        if a.get("kind") == "desk_claim" and slug in str(a.get("title") or "").lower()
    ]
    return {
        "project": slug,
        "named": is_named_well(slug),
        "members": members[:24],
        "desk": desk,
        "count": len(members),
        "cheap": True,
    }


def orbit_relay_pack(sid: str = "", project: str = "") -> dict:
    if sid:
        return build_handoff(sid)
    slug = (project or "").strip().lower()
    if not slug:
        return {"error": "id or project required"}
    well = orbit_well(slug)
    rows = well.get("members") or []
    if not rows:
        return {"error": f"no sessions in well {slug}"}
    pick = next((r for r in rows if r.get("live")), None) or rows[0]
    return build_handoff(str(pick.get("id") or ""))


def resume_session(sid: str) -> dict:
    if not UUID_RE.match(sid):
        return {"error": "invalid session id"}
    if sid in live_ids():
        return {"error": "refusing resume inject: live TUI pager. Use the native Grok window."}
    if not GROK.exists():
        return {"error": f"grok missing: {GROK}"}
    snap = build()
    hit = next((s for s in snap.get("sessions") or [] if s.get("id") == sid), None)
    cwd = (hit or {}).get("cwd") or str(HOME)
    cmd = [str(GROK), "--resume", sid]
    creation = 0x00000010 if os.name == "nt" else 0
    try:
        subprocess.Popen(
            cmd,
            cwd=cwd,
            creationflags=creation,
        )
    except TypeError:
        subprocess.Popen(cmd, cwd=cwd)
    return {"ok": True, "resumed": sid, "cwd": cwd}


TOOLS = {
    "orbit_snapshot": {
        "description": "Grok Orbit fleet snapshot: situation sentence, live pagers, adapters, Grok Bot surface, desk, clearance. Local-first. No secrets.",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "run": lambda _a: compact(build()),
    },
    "orbit_search": {
        "description": "Search Grok Build session titles/content via the local FTS index.",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 40},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "run": lambda a: {"hits": search_sessions(str(a.get("query") or ""), int(a.get("limit") or 20))},
    },
    "orbit_session_detail": {
        "description": "One session: metadata plus tailed redacted updates.",
        "schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        "run": lambda a: session_detail(str(a.get("id") or "")),
    },
    "orbit_resume": {
        "description": "Open a session in a NEW Grok console. Refuses live TUI pagers. Does not yolo-inject.",
        "schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        "run": lambda a: resume_session(str(a.get("id") or "")),
    },
    "orbit_handoff": {
        "description": "Build a redacted Orbit handoff pack for a session. Never injects into a live TUI. Copy the text or start a new Orbit ACP from the desktop app.",
        "schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
        "run": lambda a: build_handoff(str(a.get("id") or "")),
    },
    "orbit_next": {
        "description": "Compact next-hop queue: stale pagers, running Cursor, open PRs, desk claims. Cache/read only. Never injects.",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "run": lambda _a: orbit_next(),
    },
    "orbit_well": {
        "description": "Members of a named project well (live pagers, Cursor, grok.com, desk). Read only.",
        "schema": {
            "type": "object",
            "properties": {"project": {"type": "string"}},
            "required": ["project"],
            "additionalProperties": False,
        },
        "run": lambda a: orbit_well(str(a.get("project") or "")),
    },
    "orbit_relay_pack": {
        "description": "Redacted relay pack for a session id or a project well. Never injects into a live TUI. No Cursor follow-up. No desk claim.",
        "schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "project": {"type": "string"}},
            "additionalProperties": False,
        },
        "run": lambda a: orbit_relay_pack(str(a.get("id") or ""), str(a.get("project") or "")),
    },
    "orbit_web_status": {
        "description": "Consented grok.com / Cursor web adapter status. Cache only. Never launches a browser. Never copies Chrome cookies.",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "run": lambda _a: __import__("web_adapters").status(),
    },
    "orbit_focus": {
        "description": "Bring a live Grok pager window to the front (Windows Terminal ancestor if needed). Does not inject keystrokes. Set apply=false to only resolve the HWND.",
        "schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "apply": {"type": "boolean"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "run": lambda a: focus_session(str(a.get("id") or ""), bool(a.get("apply") if "apply" in a else True)),
    },
}


def ok_result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def err_result(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        return ok_result(
            mid,
            {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "grok-orbit", "version": "0.6.0"},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return ok_result(mid, {})
    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["schema"],
            }
            for name, spec in TOOLS.items()
        ]
        return ok_result(mid, {"tools": tools})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        spec = TOOLS.get(name)
        if not spec:
            return err_result(mid, -32601, f"unknown tool {name}")
        try:
            payload = spec["run"](args)
            text = json.dumps(payload, ensure_ascii=True)
            return ok_result(
                mid,
                {"content": [{"type": "text", "text": text}], "isError": False},
            )
        except Exception as e:
            return ok_result(
                mid,
                {
                    "content": [{"type": "text", "text": f"error: {type(e).__name__}: {e}"}],
                    "isError": True,
                },
            )
    if mid is not None:
        return err_result(mid, -32601, f"Method not found: {method}")
    return None


def main() -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
