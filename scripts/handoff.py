"""Build an Orbit handoff pack. Never injects into a live TUI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from snapshot import UUID_RE, build, grok_home, redact  # noqa: E402
from web_adapters import status as web_status  # noqa: E402
from projects import resolve_clone  # noqa: E402


def git_head(cwd: str) -> str | None:
    if not cwd or not Path(cwd).is_dir():
        return None
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        ).strip()
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None
    if not branch:
        return None
    return f"{branch} @ {sha}"


def acp_cwd_for(session: dict) -> str:
    clone = resolve_clone(session)
    if clone:
        return clone
    sid = str(session.get("id") or "")
    src = str(session.get("source") or "")
    if sid.startswith("web:") or src in {"cursor_web", "grok_web"}:
        return ""
    cwd = session.get("cwd") or ""
    if cwd and Path(cwd).is_dir():
        return cwd
    return os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""


def live_ids() -> set[str]:
    path = grok_home() / "active_sessions.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    from snapshot import pid_alive

    out = set()
    for row in rows if isinstance(rows, list) else []:
        sid = str(row.get("session_id") or "")
        pid = int(row.get("pid") or 0)
        if UUID_RE.match(sid) and pid_alive(pid):
            out.add(sid)
    return out


def find_session(sid: str) -> dict | None:
    snap = build()
    hit = next((s for s in snap.get("sessions") or [] if s.get("id") == sid), None)
    if hit:
        return hit
    if str(sid).startswith("web:"):
        st = web_status()
        hit = next((s for s in st.get("sessions") or [] if s.get("id") == sid), None)
        if hit:
            from projects import assign_slug, build_catalog
            from pr_state import apply_to_sessions

            hit["project_id"] = assign_slug(hit, build_catalog())
            apply_to_sessions([hit])
        return hit
    return None


def tail_events(session: dict) -> list[dict]:
    disk = session.get("disk_path")
    cwd = session.get("cwd") or ""
    sid = session.get("id") or ""
    from snapshot import encode_cwd, tail_events as _tail

    path = None
    if disk:
        path = Path(disk) / "updates.jsonl"
    elif cwd and UUID_RE.match(str(sid)):
        path = grok_home() / "sessions" / encode_cwd(cwd) / sid / "updates.jsonl"
    if path is None:
        return []
    return _tail(path, 24000, 12)


def plan_excerpt(session: dict) -> str:
    disk = session.get("disk_path")
    cwd = session.get("cwd") or ""
    sid = session.get("id") or ""
    from snapshot import encode_cwd

    dirs = []
    if disk:
        dirs.append(Path(disk))
    if cwd and UUID_RE.match(str(sid)):
        dirs.append(grok_home() / "sessions" / encode_cwd(cwd) / sid)
    for d in dirs:
        for name in ("plan.md", "plan.json"):
            p = d / name
            if p.exists():
                try:
                    return redact(p.read_text(encoding="utf-8", errors="replace"))[:1200]
                except OSError:
                    return ""
    return ""


def _append_well(lines: list[str], session: dict, sid: str) -> None:
    from projects import is_named_well, member_kind

    pid = str(session.get("project_id") or "")
    if not is_named_well(pid):
        return
    try:
        snap = build()
    except Exception:
        return
    for row in snap.get("attention") or []:
        title = str(row.get("title") or "")
        if row.get("kind") == "desk_claim" and f"claim {pid}" in title.lower():
            lines.append(f"desk: {redact(title)}")
            break
    members = [
        s
        for s in snap.get("sessions") or []
        if s.get("id") != sid and str(s.get("project_id") or "") == pid
    ][:6]
    if not members:
        return
    lines.extend(["", "Well", "----"])
    for row in members:
        lines.append(f"- {redact(row.get('title') or row.get('id'))} ({member_kind(row)})")


def build_handoff(sid: str) -> dict:
    sid = (sid or "").strip()
    if not (UUID_RE.match(sid) or sid.startswith("web:")):
        return {"error": "invalid session id"}
    session = find_session(sid)
    if not session:
        return {"error": "session not in snapshot"}
    live = bool(session.get("live")) or sid in live_ids()
    cwd = session.get("cwd") or ""
    acp_cwd = acp_cwd_for(session)
    branch = git_head(acp_cwd or cwd)
    events = tail_events(session)
    plan = plan_excerpt(session)
    lines = [
        "ORBIT HANDOFF",
        f"source: {session.get('source') or 'unknown'}",
        f"id: {sid}",
        f"title: {redact(session.get('title') or sid)}",
    ]
    if session.get("project_id"):
        lines.append(f"project: {session['project_id']}")
    if cwd:
        lines.append(f"cwd: {cwd}")
    if acp_cwd and acp_cwd != cwd:
        lines.append(f"clone: {acp_cwd}")
    if session.get("remote"):
        lines.append(f"remote: {session['remote']}")
    if branch:
        lines.append(f"branch: {branch}")
    if session.get("model"):
        lines.append(f"model: {session['model']}")
    if session.get("url"):
        lines.append(f"url: {session['url']}")
    if session.get("pr_url"):
        st = session.get("pr_state") or "unknown"
        lines.append(f"pr: {st} {session['pr_url']}")
        if session.get("pr_file_count") is not None:
            lines.append(f"pr_files: {session.get('pr_file_count')}")
        for path in (session.get("pr_files") or [])[:8]:
            lines.append(f"  {path}")
    lines.append(f"live: {'yes' if live else 'no'}")
    _append_well(lines, session, sid)
    if plan.strip():
        lines.extend(["", "Plan", "-----", plan.strip()])
    if events:
        lines.extend(["", "Recent", "------"])
        for ev in events[-12:]:
            kind = str(ev.get("kind") or "update").replace("_", " ")
            body = redact(str(ev.get("text") or ""))[:280]
            if body:
                lines.append(f"[{kind}] {body}")
    lines.extend(
        [
            "",
            "Continue this work. Do not assume the previous pager is still attached.",
        ]
    )
    if live:
        lines.append("Previous session is a live TUI. Do not inject into it.")
    inject_ok = (not live) and bool(acp_cwd)
    reason = None
    if live:
        reason = "live TUI pager; copy the pack, do not inject"
    elif not acp_cwd:
        reason = "no local clone for this project; copy the pack"
    return {
        "session_id": sid,
        "source": session.get("source") or "unknown",
        "title": redact(session.get("title") or sid),
        "cwd": cwd,
        "acp_cwd": acp_cwd,
        "branch": branch,
        "url": session.get("url"),
        "live": live,
        "inject_ok": inject_ok,
        "reason": reason,
        "text": "\n".join(lines),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: handoff.py <session-id>", file=sys.stderr)
        return 2
    print(json.dumps(build_handoff(sys.argv[1]), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
