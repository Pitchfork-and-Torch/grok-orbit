"""Grok Orbit Phase 1 snapshot. Read-only. No secrets files."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

SECRET_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xai-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})",
    re.I,
)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def grok_home() -> Path:
    raw = os.environ.get("GROK_HOME")
    return Path(raw) if raw else Path.home() / ".grok"


def redact(text: str | None) -> str:
    if not text:
        return ""
    return SECRET_RE.sub("[redacted]", text)


def encode_cwd(cwd: str) -> str:
    return urllib.parse.quote(cwd, safe="")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        # OpenProcess can fail for access; fall back to os.kill(0) is unix-only.
        return False
    except Exception:
        return False


def local_exec_alive() -> bool:
    path = Path.home() / ".grokbot" / "local-exec-daemon.json"
    data = read_json(path)
    if not isinstance(data, dict):
        return False
    pid = int(data.get("pid") or 0)
    return pid_alive(pid)


def steward_pack() -> str | None:
    path = grok_home() / "grok-bot" / "01-knock-ops-steward-PROMPT.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines()[:12]:
        if "version:" in line.lower():
            part = line.split(":", 1)[-1].strip().strip("*").split()[0].strip("*")
            return part or None
    return None


_PROC_MEMO: tuple[float, dict] | None = None


def process_counts() -> dict:
    global _PROC_MEMO
    now = time.perf_counter()
    if _PROC_MEMO and now - _PROC_MEMO[0] < 5.0:
        return dict(_PROC_MEMO[1])
    names = {"grok": 0, "grok_bot": 0, "cursor": 0}
    try:
        import subprocess

        out = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            errors="replace",
            timeout=4,
        )
        for line in out.splitlines():
            low = line.lower()
            if "grok bot" in low:
                names["grok_bot"] += 1
            elif "grok.exe" in low or ',\"grok\"' in low or low.startswith('"grok"'):
                names["grok"] += 1
            elif "cursor.exe" in low:
                names["cursor"] += 1
    except Exception:
        pass
    _PROC_MEMO = (now, dict(names))
    return names


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def live_sessions(home: Path) -> tuple[list[dict], dict]:
    adapter = {"name": "grok_live", "status": "ok", "detail": ""}
    path = home / "active_sessions.json"
    raw = read_json(path)
    if raw is None:
        adapter["status"] = "offline" if not path.exists() else "degraded"
        adapter["detail"] = "active_sessions.json unreadable"
        return [], adapter
    out = []
    for row in raw if isinstance(raw, list) else []:
        sid = str(row.get("session_id") or "")
        if not UUID_RE.match(sid):
            continue
        cwd = row.get("cwd") or ""
        pid = int(row.get("pid") or 0)
        alive = pid_alive(pid)
        encoded = encode_cwd(cwd)
        disk = home / "sessions" / encoded / sid
        summary = read_json(disk / "summary.json") or {}
        title = redact(
            summary.get("generated_title")
            or summary.get("session_summary")
            or sid[:8]
        )
        state = "live_working" if alive else "offline"
        out.append(
            {
                "id": sid,
                "source": "grok_build",
                "cwd": cwd,
                "title": title,
                "summary": redact(summary.get("session_summary") or title),
                "state": state,
                "health": "ok" if alive else "offline",
                "pid": pid if alive else None,
                "model": summary.get("current_model_id"),
                "agent_name": summary.get("agent_name"),
                "created_at": summary.get("created_at") or row.get("opened_at"),
                "updated_at": summary.get("updated_at") or row.get("opened_at"),
                "last_active_at": summary.get("last_active_at"),
                "disk_path": str(disk) if disk.exists() else None,
                "url": None,
                "live": alive,
                "has_plan": (disk / "plan.md").exists() or (disk / "plan.json").exists(),
            }
        )
    adapter["detail"] = f"{len(out)} listed"
    return out, adapter


def index_sessions(home: Path, limit: int = 80) -> tuple[list[dict], dict]:
    adapter = {"name": "grok_index", "status": "ok", "detail": ""}
    db = home / "sessions" / "session_search.sqlite"
    if not db.exists():
        adapter["status"] = "offline"
        adapter["detail"] = "session_search.sqlite missing"
        return [], adapter
    try:
        uri = db.resolve().as_posix()
        con = sqlite3.connect(f"file:{uri}?mode=ro", uri=True, timeout=1.0)
        cur = con.execute(
            "SELECT session_id, cwd, updated_at, title FROM session_docs ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = []
        for sid, cwd, updated_at, title in cur.fetchall():
            if not UUID_RE.match(str(sid)):
                continue
            ts = None
            if isinstance(updated_at, (int, float)) and updated_at > 0:
                ts = datetime.fromtimestamp(updated_at, tz=timezone.utc).isoformat()
            rows.append(
                {
                    "id": sid,
                    "source": "grok_build",
                    "cwd": cwd,
                    "title": redact(title)[:180],
                    "summary": redact(title)[:180],
                    "state": "disk",
                    "health": "ok",
                    "pid": None,
                    "model": None,
                    "agent_name": None,
                    "created_at": ts,
                    "updated_at": ts,
                    "last_active_at": ts,
                    "disk_path": None,
                    "url": None,
                    "live": False,
                    "has_plan": False,
                }
            )
        con.close()
        adapter["detail"] = f"{len(rows)} recent"
        return rows, adapter
    except Exception as e:
        adapter["status"] = "degraded"
        adapter["detail"] = str(e)[:200]
        return [], adapter


def desk_attention(home: Path) -> tuple[list[dict], dict]:
    adapter = {"name": "desk", "status": "ok", "detail": ""}
    claims_dir = home / "desk" / "claims"
    if not claims_dir.exists():
        adapter["status"] = "offline"
        adapter["detail"] = "no desk/claims"
        return [], adapter
    attention = []
    count = 0
    for p in claims_dir.glob("*.json"):
        data = read_json(p)
        if not isinstance(data, dict):
            continue
        if data.get("status") != "active":
            continue
        count += 1
        attention.append(
            {
                "id": f"desk-{data.get('id')}",
                "session_id": data.get("session_id"),
                "source": "grok_build",
                "kind": "desk_claim",
                "title": redact(
                    f"desk claim {data.get('project') or ''}: {data.get('note') or ''}".strip()
                ),
                "created_at": data.get("claimed_at"),
                "severity": "info",
            }
        )
    adapter["detail"] = f"{count} claims"
    return attention, adapter


def merge(live: list[dict], indexed: list[dict]) -> list[dict]:
    by_id = {s["id"]: s for s in indexed}
    for s in live:
        prev = by_id.get(s["id"])
        if prev:
            s = {**prev, **{k: v for k, v in s.items() if v is not None}}
            s["live"] = True
            s["state"] = "live_working"
        by_id[s["id"]] = s
    sessions = list(by_id.values())
    sessions.sort(key=lambda s: (not s.get("live"), s.get("updated_at") or ""), reverse=False)
    sessions.sort(key=lambda s: (0 if s.get("live") else 1, -(parse_ts(s.get("updated_at")))))
    return sessions


def parse_ts(value) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def projects_from(sessions: list[dict]) -> list[dict]:
    from projects import link_sessions

    return link_sessions(sessions)


_TAIL_MEMO: dict[str, tuple[int, list]] = {}


def tail_events_memo(path: Path, nbytes: int = 24000, limit: int = 6) -> list[dict]:
    try:
        mt = path.stat().st_mtime_ns
    except OSError:
        return []
    key = str(path)
    hit = _TAIL_MEMO.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    events = tail_events(path, nbytes, limit)
    if len(_TAIL_MEMO) > 64:
        _TAIL_MEMO.clear()
    _TAIL_MEMO[key] = (mt, events)
    return events


def tail_events(path: Path, nbytes: int = 24000, limit: int = 6) -> list[dict]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    tail = data[-nbytes:]
    text = tail.decode("utf-8", errors="replace")
    if len(data) > nbytes:
        text = text.split("\n", 1)[-1]
    events = []
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        upd = ((obj.get("params") or {}).get("update")) or {}
        kind = upd.get("sessionUpdate") or "update"
        if kind in ("user_message_chunk", "agent_message_chunk", "agent_thought_chunk"):
            body = ((upd.get("content") or {}).get("text")) or ""
        elif kind in ("tool_call", "tool_call_update"):
            body = upd.get("title") or kind
        elif kind == "plan":
            body = "plan update"
        else:
            body = kind
        body = redact(str(body).strip())
        if body:
            events.append({"kind": kind, "text": body[:400]})
    return events[-limit:]


def collect_activity(sessions: list[dict]) -> list[dict]:
    live = [s for s in sessions if s.get("live")]
    running = [
        s
        for s in sessions
        if s.get("source") == "cursor_web" and s.get("agent_name") == "running"
    ]
    disk = [s for s in sessions if not s.get("live")][:8]
    picks = live + running + disk
    out = []
    for s in running:
        out.append(
            {
                "id": f"{s.get('id')}:cursor_running",
                "session_id": s.get("id"),
                "title": s.get("title") or "cursor agent",
                "kind": "cursor_running",
                "text": "Cloud agent running on cursor.com",
                "live": False,
            }
        )
    for s in picks:
        if not UUID_RE.match(str(s.get("id") or "")):
            continue
        disk_path = s.get("disk_path")
        path = Path(disk_path) / "updates.jsonl" if disk_path else None
        if path is None and s.get("cwd") and s.get("id"):
            path = grok_home() / "sessions" / encode_cwd(s["cwd"]) / s["id"] / "updates.jsonl"
        if path is None:
            continue
        for ev in reversed(tail_events_memo(path)):
            out.append(
                {
                    "id": f"{s['id']}:{ev['kind']}:{len(out)}",
                    "session_id": s["id"],
                    "title": s.get("title") or s["id"][:8],
                    "kind": ev["kind"],
                    "text": ev["text"],
                    "live": bool(s.get("live")),
                }
            )
            if len(out) >= 24:
                return out
    return out


def normalize_pr_url(url: str) -> str:
    s = (url or "").strip().lower()
    if "#" in s:
        s = s.split("#", 1)[0]
    if "?" in s:
        s = s.split("?", 1)[0]
    s = s.rstrip("/")
    if s.startswith("https://www.github.com/"):
        s = "https://github.com/" + s[len("https://www.github.com/") :]
    if s.startswith("https://www.gitlab.com/"):
        s = "https://gitlab.com/" + s[len("https://www.gitlab.com/") :]
    return s


def pr_needs_clearance(session) -> bool:
    try:
        from pr_state import needs_clearance
    except Exception:
        return True
    return needs_clearance(session.get("pr_state") if isinstance(session, dict) else None)


def unique_pr_groups(sessions, clearance_only: bool = False) -> dict[str, list]:
    groups: dict[str, list] = {}
    for s in sessions:
        if s.get("agent_name") == "running":
            continue
        pr = s.get("pr_url")
        if not pr:
            continue
        if not (
            s.get("source") == "cursor_web" or str(s.get("id") or "").startswith("web:cursor:")
        ):
            continue
        if clearance_only and not pr_needs_clearance(s):
            continue
        key = normalize_pr_url(str(pr))
        groups.setdefault(key, []).append(s)
    return groups


def session_when(session) -> str | None:
    return session.get("last_active_at") or session.get("updated_at") or session.get("created_at")


def session_age_seconds(session) -> int | None:
    raw = session_when(session)
    if not raw:
        return None
    try:
        text = str(raw).strip().replace("Z", "+00:00")
        from datetime import datetime

        then = datetime.fromisoformat(text)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0, int((now - then).total_seconds()))
    except Exception:
        return None


def format_age_seconds(sec: int) -> str:
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        return f"{sec // 3600}h"
    return f"{sec // 86400}d"


def is_stale_live(session) -> bool:
    if not session.get("live"):
        return False
    age = session_age_seconds(session)
    return age is not None and age >= 30 * 60


def next_hop_clause(sessions, attention) -> str | None:
    for row in attention or []:
        if row.get("kind") == "stale":
            return f"Next: {str(row.get('title') or 'stale pager')[:72]}"
    stale = [s for s in sessions if is_stale_live(s)]
    if stale:
        return f"Next: focus stale pager {str(stale[0].get('title') or 'pager')[:56]}"
    for kind, prefix in (("running", "Next: "), ("pr_ready", "Next: "), ("desk_claim", "Next: ")):
        hit = next((a for a in (attention or []) if a.get("kind") == kind), None)
        if hit:
            return f"{prefix}{str(hit.get('title') or kind)[:72]}"
    return None


def build_next() -> dict:
    """Cheap queue. No tasklist, no sqlite walk, no activity tails."""
    t0 = time.perf_counter()
    home = grok_home()
    live, _ = live_sessions(home)
    desk, _ = desk_attention(home)
    stale = [
        {"id": s.get("id"), "title": s.get("title")}
        for s in live
        if is_stale_live(s)
    ]
    running = []
    open_prs = []
    try:
        from web_adapters import cache_path, read_json
        from pr_state import apply_to_sessions, needs_clearance

        cache = read_json(cache_path("cursor_web")) or {}
        rows = []
        for item in cache.get("sessions") or []:
            if not isinstance(item, dict):
                continue
            row = {
                "id": item.get("id"),
                "title": item.get("title"),
                "source": "cursor_web",
                "agent_name": item.get("status") or item.get("agent_name"),
                "pr_url": item.get("pr_url"),
                "pr_state": item.get("pr_state"),
            }
            rows.append(row)
        apply_to_sessions(rows)
        running = [
            {"id": s.get("id"), "title": s.get("title")}
            for s in rows
            if s.get("agent_name") == "running"
        ]
        seen = set()
        for s in rows:
            if s.get("agent_name") == "running":
                continue
            if not s.get("pr_url") or not needs_clearance(s.get("pr_state")):
                continue
            key = normalize_pr_url(str(s.get("pr_url")))
            if key in seen:
                continue
            seen.add(key)
            open_prs.append({"id": s.get("id"), "title": s.get("title"), "pr_url": s.get("pr_url")})
    except Exception:
        pass
    desk_rows = [
        {"id": a.get("id"), "title": a.get("title"), "session_id": a.get("session_id")}
        for a in desk
        if a.get("kind") == "desk_claim"
    ]
    hop = "quiet"
    if stale:
        hop = f"focus stale pager {stale[0].get('title') or stale[0].get('id')}"
    elif running:
        hop = f"watch Cursor running {running[0].get('title') or ''}"
    elif open_prs:
        hop = f"open PR {open_prs[0].get('title') or ''}"
    elif desk_rows:
        hop = f"desk {desk_rows[0].get('title') or ''}"
    return {
        "stale": stale[:8],
        "running": running[:8],
        "open_prs": open_prs[:8],
        "desk": desk_rows[:8],
        "suggested_hop": hop[:180],
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "cheap": True,
        "situation": None,
    }


def situation(sessions, adapters, surfaces, attention, projects=None) -> str:
    live = [s for s in sessions if s.get("live")]
    bits = []
    hop = next_hop_clause(sessions, attention)
    if hop:
        bits.append(hop)
    names = {p.get("id"): p.get("name") or p.get("id") for p in (projects or [])}
    stale_live = [s for s in live if is_stale_live(s)]
    if stale_live:
        bits.append(
            f"{len(stale_live)} live pager{'s' if len(stale_live) != 1 else ''} quiet >30m ({(stale_live[0].get('title') or 'untitled')[:48]})"
        )
    cursor_running = [
        s
        for s in sessions
        if (s.get("source") == "cursor_web" or str(s.get("id") or "").startswith("web:cursor:"))
        and s.get("agent_name") == "running"
    ]
    if cursor_running:
        first = cursor_running[0]
        slug = first.get("project_id") or "cursor.com"
        well = names.get(slug) or slug
        bits.append(
            f"{len(cursor_running)} Cursor agent{'s' if len(cursor_running) != 1 else ''} running on {well} ({(first.get('title') or 'untitled')[:48]})"
        )
    pr_groups = unique_pr_groups(sessions, clearance_only=True)
    if pr_groups:
        first_rows = next(iter(sorted(pr_groups.items())))[1]
        first_title = (first_rows[0].get("title") or "untitled")[:48]
        bits.append(
            f"{len(pr_groups)} open PR{'s' if len(pr_groups) != 1 else ''} ({first_title})"
        )
    try:
        from projects import thread_clause

        clause = thread_clause(sessions, projects or [], attention)
        if clause:
            bits.append(clause)
    except Exception:
        pass
    if live:
        cwds = sorted({s.get("cwd") or "?" for s in live})
        titles = "; ".join((s.get("title") or "untitled")[:48] for s in live[:3])
        bits.append(f"{len(live)} Grok Build pager{'s' if len(live) != 1 else ''} live on {', '.join(cwds)} ({titles})")
    else:
        bits.append("No live Grok Build pagers")
    if surfaces.get("grok_bot"):
        bits.append(
            "Grok Bot desktop is running ({} procs, local-exec {}, pack {})".format(
                surfaces.get("grok_bot_procs") or 0,
                "alive" if surfaces.get("local_exec_alive") else "dead",
                surfaces.get("steward_pack") or "?",
            )
        )
    else:
        bits.append("Grok Bot desktop is not running")
    if surfaces.get("cursor"):
        bits.append("Cursor desktop is running")
    else:
        bits.append("Cursor desktop is not installed or not running")
    grok_web_n = sum(
        1
        for s in sessions
        if s.get("source") == "grok_web" or str(s.get("id") or "").startswith("web:grok:")
    )
    if grok_web_n:
        bits.append(f"Grok web ok ({grok_web_n} chats in Galaxy)")
    else:
        bits.append(
            "Grok web {}{}".format(
                surfaces.get("grok_web") or "needs_consent",
                f" ({surfaces['grok_web_detail']})" if surfaces.get("grok_web_detail") else "",
            )
        )
    cursor_web_n = sum(
        1
        for s in sessions
        if s.get("source") == "cursor_web" or str(s.get("id") or "").startswith("web:cursor:")
    )
    if cursor_running:
        bits.append(f"{cursor_web_n} cursor.com agents listed")
    elif cursor_web_n:
        bits.append(f"Cursor web ok ({cursor_web_n} agents, none running)")
    else:
        bits.append(
            "Cursor web {}{}".format(
                surfaces.get("cursor_web") or "needs_consent",
                f" ({surfaces['cursor_web_detail']})" if surfaces.get("cursor_web_detail") else "",
            )
        )
    desk = next((a for a in adapters if a["name"] == "desk"), None)
    bits.append(f"Desk: {desk['detail'] if desk else 'unknown'}")
    bits.append(f"{len(attention)} clearance item{'s' if len(attention) != 1 else ''}")
    down = [a["name"] for a in adapters if a["status"] != "ok"]
    if down:
        bits.append("degraded: " + ", ".join(down))
    return ". ".join(bits) + "."


def _stage_ms(mark: float) -> int:
    return int((time.perf_counter() - mark) * 1000)


def build() -> dict:
    t0 = time.perf_counter()
    stages: dict[str, int] = {}
    home = grok_home()
    mark = time.perf_counter()
    live, a_live = live_sessions(home)
    stages["live"] = _stage_ms(mark)
    mark = time.perf_counter()
    indexed, a_idx = index_sessions(home)
    stages["index"] = _stage_ms(mark)
    mark = time.perf_counter()
    attention, a_desk = desk_attention(home)
    stages["desk"] = _stage_ms(mark)
    mark = time.perf_counter()
    counts = process_counts()
    exec_alive = local_exec_alive()
    pack = steward_pack()
    stages["proc"] = _stage_ms(mark)
    a_proc = {
        "name": "process",
        "status": "ok" if counts["grok"] or counts["grok_bot"] else "degraded",
        "detail": f"grok={counts['grok']} bot={counts['grok_bot']} cursor={counts['cursor']} local-exec={'alive' if exec_alive else 'dead'} pack={pack or '?'}",
    }
    sessions = merge(live, indexed)
    for s in sessions:
        if s.get("has_plan") and s.get("live"):
            attention.append(
                {
                    "id": f"plan-{s['id']}",
                    "session_id": s["id"],
                    "source": "grok_build",
                    "kind": "plan",
                    "title": f"Plan file present: {s.get('title')}",
                    "created_at": s.get("updated_at"),
                    "severity": "warn",
                }
            )
        if is_stale_live(s):
            age = format_age_seconds(session_age_seconds(s) or 0)
            attention.append(
                {
                    "id": f"stale-{s.get('id')}",
                    "session_id": s.get("id"),
                    "source": s.get("source") or "grok_build",
                    "kind": "stale",
                    "title": f"Live pager quiet {age}: {s.get('title')}",
                    "created_at": s.get("updated_at"),
                    "severity": "warn",
                }
            )
    adapters = [a_live, a_idx, a_desk, a_proc]
    surfaces = {
        "grok_bot": counts["grok_bot"] > 0,
        "grok_bot_procs": counts["grok_bot"],
        "local_exec_alive": exec_alive,
        "steward_pack": pack,
        "cursor": counts["cursor"] > 0,
        "live_grok_pids": [s["pid"] for s in sessions if s.get("pid")],
        "web_consent": False,
        "grok_web": "needs_consent",
        "grok_web_detail": None,
        "cursor_web": "needs_consent",
        "cursor_web_detail": None,
        "cursor_web_probed_at": None,
        "cursor_pulse": True,
        "cook_armed": False,
        "cook_detail": None,
    }
    try:
        from web_adapters import read_json, web_home

        cj = read_json(web_home() / "cook.json")
        if isinstance(cj, dict):
            surfaces["cook_armed"] = bool(cj.get("armed"))
            surfaces["cook_detail"] = cj.get("last_detail")
            surfaces["cook_summary"] = cj.get("last_summary")
            surfaces["cook_staff"] = int(cj.get("staff_now") or 0)
    except Exception:
        pass
    mark = time.perf_counter()
    try:
        from web_adapters import status as web_status

        wst = web_status()
        gw = (wst.get("surfaces") or {}).get("grok_web") or {}
        cw = (wst.get("surfaces") or {}).get("cursor_web") or {}
        surfaces["web_consent"] = bool((wst.get("consent") or {}).get("granted"))
        surfaces["grok_web"] = gw.get("status") or "needs_consent"
        surfaces["grok_web_detail"] = gw.get("detail")
        surfaces["cursor_web"] = cw.get("status") or "needs_consent"
        surfaces["cursor_web_detail"] = cw.get("detail")
        surfaces["cursor_web_probed_at"] = cw.get("probed_at")
        try:
            from web_adapters import cache_path, consent_path, read_json

            pulse = read_json(cache_path("cursor_web").with_name("cursor_web.pulse.json"))
            if isinstance(pulse, dict) and pulse.get("probed_at"):
                surfaces["cursor_web_probed_at"] = pulse.get("probed_at")
            disk = read_json(consent_path()) if consent_path().exists() else {}
            if isinstance(disk, dict) and "cursor_pulse" in disk:
                surfaces["cursor_pulse"] = bool(disk.get("cursor_pulse"))
        except Exception:
            pass
        adapters.append(
            {
                "name": "web",
                "status": "ok"
                if surfaces["grok_web"] == "ok" or surfaces["cursor_web"] == "ok"
                else ("unauth" if not surfaces["web_consent"] else "unauth"),
                "detail": f"consent={'yes' if surfaces['web_consent'] else 'no'} grok={surfaces['grok_web']} cursor={surfaces['cursor_web']}",
            }
        )
        if not surfaces["web_consent"]:
            attention.append(
                {
                    "id": "web-consent",
                    "session_id": None,
                    "source": "grok_web",
                    "kind": "consent",
                    "title": "Grant isolated browser consent for grok.com and Cursor web",
                    "created_at": None,
                    "severity": "info",
                }
            )
        for item in wst.get("sessions") or []:
            sid = item.get("id") or ""
            if not str(sid).startswith("web:"):
                continue
            src = item.get("source") or "grok_web"
            cwd = "grok.com" if src == "grok_web" else "cursor.com"
            sessions.append(
                {
                    "id": sid,
                    "source": src,
                    "project_id": cwd,
                    "cwd": cwd,
                    "title": redact(item.get("title") or sid),
                    "summary": redact(item.get("url") or ""),
                    "state": item.get("state") or "disk",
                    "health": item.get("health") or "ok",
                    "pid": None,
                    "model": None,
                    "agent_name": item.get("agent_name"),
                    "created_at": item.get("updated_at"),
                    "updated_at": item.get("updated_at"),
                    "last_active_at": item.get("updated_at"),
                    "disk_path": None,
                    "url": item.get("url"),
                    "remote": item.get("remote"),
                    "branch": item.get("branch"),
                    "pr_url": item.get("pr_url"),
                    "pr_state": item.get("pr_state"),
                    "pr_files": item.get("pr_files") or [],
                    "pr_file_count": item.get("pr_file_count"),
                    "live": False,
                    "has_plan": False,
                }
            )
            if src == "cursor_web" and item.get("agent_name") == "running":
                attention.append(
                    {
                        "id": f"cursor-run-{sid}",
                        "session_id": sid,
                        "source": "cursor_web",
                        "kind": "running",
                        "title": f"Cursor agent running: {redact(item.get('title') or sid)}",
                        "created_at": None,
                        "severity": "warn",
                    }
                )
            elif src == "cursor_web" and item.get("agent_name") == "error":
                attention.append(
                    {
                        "id": f"cursor-err-{sid}",
                        "session_id": sid,
                        "source": "cursor_web",
                        "kind": "error",
                        "title": f"Cursor agent error: {redact(item.get('title') or sid)}",
                        "created_at": None,
                        "severity": "error",
                    }
                )
        try:
            from pr_state import apply_to_sessions

            apply_to_sessions(sessions)
        except Exception:
            pass
        for key, rows in sorted(unique_pr_groups(sessions, clearance_only=True).items()):
            rows = sorted(
                rows,
                key=lambda s: (
                    0 if s.get("agent_name") == "running" else 1 if s.get("agent_name") == "error" else 2,
                    str(s.get("title") or ""),
                    str(s.get("id") or ""),
                ),
            )
            winner = rows[0]
            extra = len(rows) - 1
            pr = str(winner.get("pr_url") or key)
            short = "#" + pr.rsplit("/pull/", 1)[-1].split("/")[0] if "/pull/" in pr else "PR"
            title = f"Cursor PR ready: {redact(winner.get('title') or winner.get('id'))} ({short})"
            if extra:
                title += f" +{extra} agent{'s' if extra != 1 else ''}"
            attention.append(
                {
                    "id": f"cursor-pr-{key.replace('https://', '')}",
                    "session_id": winner.get("id"),
                    "source": "cursor_web",
                    "kind": "pr_ready",
                    "title": title,
                    "created_at": None,
                    "severity": "warn",
                }
            )
    except Exception as e:
        adapters.append({"name": "web", "status": "degraded", "detail": str(e)[:200]})
    stages["web"] = _stage_ms(mark)
    mark = time.perf_counter()
    projects = projects_from(sessions)
    stages["merge"] = _stage_ms(mark)
    mark = time.perf_counter()
    sit = situation(sessions, adapters, surfaces, attention, projects)
    stages["sit"] = _stage_ms(mark)
    mark = time.perf_counter()
    activity = collect_activity(sessions)
    stages["act"] = _stage_ms(mark)
    profile = " ".join(f"{k}={v}" for k, v in stages.items())
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if os.environ.get("ORBIT_SNAP_PROFILE") == "1":
        print(f"[orbit-snap] {elapsed_ms}ms {profile}", file=sys.stderr)
    snap = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": elapsed_ms,
        "situation": sit,
        "adapters": adapters,
        "projects": projects,
        "sessions": sessions,
        "attention": attention,
        "activity": activity,
        "surfaces": surfaces,
        "grok_home": str(home),
        "snap_profile": profile,
    }
    return snap


def main() -> int:
    snap = build()
    print(json.dumps(snap, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
