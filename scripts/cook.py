"""Orbit COOK tick. Deploys staff to named wells. Never injects a live TUI.

Arm/disarm is owned by the Orbit app. This script is one tick or one harvest.
No Windows scheduled task. No Bot tokens. No --always-approve.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
MAX_GROK = 4
MAX_CURSOR = 2
PROOF_SECS = 45 * 60
IDLE_SECS = 90
BUSY_SECS = 300
DESK = Path(os.environ.get("USERPROFILE") or Path.home()) / ".grok" / "desk" / "desk.py"
MISSION_FILES = (
    "NEXT.md",
    "BACKLOG.md",
    "lab/NEXT.md",
    "lab/BACKLOG.json",
    "lab/STATE.md",
    "lab/WORKDAY.md",
    "AGENTS.md",
)
SECRET_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xai-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})",
    re.I,
)
_GIT_DIRTY_MEMO: dict[str, tuple[float, int]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def grok_bin() -> Path:
    home = Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok"))
    return home / "bin" / "grok.exe"


def safe_text(text: str, limit: int = 160) -> str:
    raw = (text or "").replace("\u2014", " - ").replace("\u2013", " - ").replace("\u2212", "-")
    raw = SECRET_RE.sub("[redacted]", raw)
    raw = " ".join(raw.split())
    return raw[:limit]


def cook_prompt(
    name: str,
    path: str,
    proof: dict | None = None,
    mission: str = "",
    dirty: int | None = None,
) -> str:
    leftover = ""
    last = "none"
    if proof:
        last = safe_text(str(proof.get("shipped") or "none"), 100)
        leftover = safe_text(str(proof.get("next") or ""), 100)
    git_bit = "unknown"
    if dirty is None:
        git_bit = "unknown"
    elif dirty < 0:
        git_bit = "unknown"
    elif dirty == 0:
        git_bit = "clean"
    else:
        git_bit = f"{dirty} dirty"
    mission_bit = safe_text(mission, 280)
    leftover_bit = leftover or "pick the next low-risk ship from AGENTS / NEXT"
    return (
        f"Orbit COOK. You are staff on {name} at {path}. "
        f"Mission: {mission_bit or 'read AGENTS.md if present'}. "
        f"Last ship: {last}. Leftover: {leftover_bit}. Git: {git_bit}. "
        "If the tree is occupied, stop. "
        "Do the leftover if it is still open, else one low-risk ship. "
        "Test what you touch. Do not wait for approval on low-risk. "
        "Do not inject into a live TUI. Do not reboot the host. "
        "Do not print secrets. ASCII only. "
        "Write .orbit/cook-receipt.json with ok, shipped, next, files, tests. "
        "Do not commit .orbit/. One meaningful ship then stop this turn. "
        "If the tree is occupied, stop."
    )


def cursor_cook_prompt(title: str, leftover: str = "") -> str:
    extra = f" Leftover: {safe_text(leftover, 100)}." if leftover else ""
    return (
        f"Orbit COOK follow-up on {title}. Continue low-risk improvement.{extra} "
        "If a PR is open, land or update it. Do not wait for approval. "
        "Do not print secrets. One focused ship."
    )


SKIP_LABEL = {
    "leftover": "not a project well",
    "no-clone": "no local folder",
    "live-pager": "live pager already there",
    "cook-running": "already cooking",
    "desk-occupied": "another agent has this tree",
    "cap": "next wave (only 4 Grok at a time)",
    "fresh-ship": "just shipped (cooldown)",
    "no-followup": "Cursor follow-up unavailable",
    "spawn": "could not start Grok",
}

WELL_TITLE = {
    "vela": "VELA",
    "leoaware": "LeoAware",
    "instar": "INSTAR",
    "ghost": "Ghost",
    "grok-orbit": "Grok Orbit",
    "orbitstack": "orbitstack",
    "cursor": "Cursor",
}


def _extra_well_titles() -> dict[str, str]:
    try:
        from projects import load_extra_specs
    except Exception:
        return {}
    return {s["id"]: str(s.get("name") or s["id"]) for s in load_extra_specs()}


def _well_scan_names() -> tuple[str, ...]:
    base = ("vela", "leoaware", "instar", "ghost", "grok-orbit", "orbitstack")
    extra = tuple(_extra_well_titles().keys())
    return base + extra


def skip_label(reason: str) -> str:
    return SKIP_LABEL.get(reason, reason)


def well_title(wid: str, roster_map: dict[str, str] | None = None) -> str:
    if roster_map and wid in roster_map:
        return roster_map[wid]
    titles = {**WELL_TITLE, **_extra_well_titles()}
    if wid in titles:
        return titles[wid]
    if len(wid) > 20:
        return "Cursor"
    return wid


def load_cook_state() -> dict:
    try:
        from web_adapters import read_json, web_home

        path = web_home() / "cook.json"
        data = read_json(path) if path.exists() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def receipt_file(root: Path) -> Path:
    return root / ".orbit" / "cook-receipt.json"


def parse_iso(text: str) -> datetime | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def read_receipt(root: Path) -> dict | None:
    path = receipt_file(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    files = []
    for item in data.get("files") or []:
        name = safe_text(str(item), 80)
        if name:
            files.append(name)
        if len(files) >= 8:
            break
    rec = {
        "ok": bool(data.get("ok")),
        "shipped": safe_text(str(data.get("shipped") or ""), 160),
        "next": safe_text(str(data.get("next") or ""), 160),
        "tests": safe_text(str(data.get("tests") or ""), 120),
        "files": files,
        "ticked_at": str(data.get("ticked_at") or ""),
        "mtime": path.stat().st_mtime,
    }
    return rec


def receipt_age_secs(rec: dict) -> int | None:
    parsed = parse_iso(str(rec.get("ticked_at") or ""))
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    mtime = rec.get("mtime")
    if isinstance(mtime, (int, float)):
        return max(0, int(datetime.now(timezone.utc).timestamp() - float(mtime)))
    return None


def is_fresh_proof(rec: dict | None, max_age: int = PROOF_SECS) -> bool:
    if not rec or not rec.get("ok") or not rec.get("shipped"):
        return False
    age = receipt_age_secs(rec)
    return age is not None and age < max_age


def git_dirty_count(root: Path) -> int:
    git_dir = root / ".git"
    if not git_dir.exists():
        return 0
    key = str(root)
    sig = 0.0
    try:
        sig = (git_dir / "HEAD").stat().st_mtime
    except OSError:
        sig = 0.0
    hit = _GIT_DIRTY_MEMO.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    kwargs: dict = {
        "args": ["git", "-C", str(root), "status", "--porcelain"],
        "text": True,
        "timeout": 1.5,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        out = subprocess.check_output(**kwargs)
        n = len([line for line in out.splitlines() if line.strip()])
    except Exception:
        n = -1
    _GIT_DIRTY_MEMO[key] = (sig, n)
    return n


def mission_excerpt(root: Path) -> str:
    for rel in MISSION_FILES:
        path = root / rel
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        body = safe_text(raw, 320)
        if body:
            return f"{rel}: {body}"
    return ""


def gather_proofs(wells: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for well in wells:
        wid = str(well.get("id") or "")
        paths = [Path(p) for p in (well.get("paths") or []) if p]
        real = [p for p in paths if p.is_dir()]
        if not wid or not real:
            continue
        rec = read_receipt(real[0]) or {}
        dirty = git_dirty_count(real[0])
        rec["dirty"] = dirty
        rec["fresh"] = is_fresh_proof(rec)
        rec["age"] = receipt_age_secs(rec) if rec.get("shipped") or rec.get("mtime") else None
        rec["mission"] = mission_excerpt(real[0])
        out[wid] = rec
    return out


def prior_sent_ids(state: dict | None = None) -> list[str]:
    """Grok wells that actually shipped last wave. Empty cooks stay in front."""
    blob = state if isinstance(state, dict) else load_cook_state()
    ids: list[str] = []
    seen: set[str] = set()
    for row in blob.get("last_board") or []:
        if not isinstance(row, dict):
            continue
        wid = str(row.get("id") or "")
        if not wid or wid == "cursor" or wid in seen:
            continue
        state_name = str(row.get("state") or "")
        shipped = str(row.get("shipped") or "")
        if state_name == "empty":
            continue
        if state_name != "sent":
            continue
        seen.add(wid)
        if shipped or state_name == "sent":
            ids.append(wid)
    return ids


def order_wells(
    wells: list[dict],
    sent_ids: list[str] | None = None,
    fresh_ids: list[str] | None = None,
) -> list[dict]:
    """Tide + proof: empty/waiting first, last-sent next, fresh ships last."""
    fresh = {str(s) for s in (fresh_ids or []) if s and s != "cursor"}
    sent = {str(s) for s in (sent_ids or []) if s and s != "cursor"} - fresh
    if not sent and not fresh:
        return list(wells)
    front = [w for w in wells if str(w.get("id") or "") not in sent and str(w.get("id") or "") not in fresh]
    mid = [w for w in wells if str(w.get("id") or "") in sent]
    back = [w for w in wells if str(w.get("id") or "") in fresh]
    return front + mid + back


def next_wave_names(board: list[dict], limit: int = MAX_GROK) -> list[str]:
    names: list[str] = []
    for row in board:
        if str(row.get("state") or "") not in {"waiting", "empty"}:
            continue
        names.append(str(row.get("name") or well_title(str(row.get("id") or ""))))
        if len(names) >= limit:
            break
    return names


def next_interval(staff_now: int) -> int:
    return BUSY_SECS if staff_now > 0 else IDLE_SECS


def build_board(
    wells: list[dict],
    dispatched: list[dict],
    skipped: list[dict],
    living: list[dict],
    proofs: dict[str, dict] | None = None,
) -> list[dict]:
    living_ids = {str(r.get("well") or "") for r in living}
    sent_grok = {str(r.get("id")) for r in dispatched if r.get("via") == "grok"}
    skip_map = {str(s.get("id")): str(s.get("reason")) for s in skipped}
    proofs = proofs or {}
    board: list[dict] = []
    for well in wells:
        wid = str(well["id"])
        name = str(well.get("name") or well_title(wid))
        proof = proofs.get(wid) or {}
        shipped = str(proof.get("shipped") or "")
        nxt = str(proof.get("next") or "")
        row = {"id": wid, "name": name, "shipped": shipped, "next": nxt}
        if wid in living_ids:
            row.update({"state": "cooking", "note": "window still open"})
        elif wid in sent_grok:
            if shipped and proof.get("ok"):
                row.update({"state": "sent", "note": f"shipped: {shipped[:90]}"})
            else:
                row.update({"state": "sent", "note": "turn finished, waiting receipt"})
        elif wid in skip_map:
            reason = skip_map[wid]
            note = skip_label(reason)
            if reason == "fresh-ship" and shipped:
                note = f"cooldown: {shipped[:80]}"
            state = "idle" if reason == "fresh-ship" else "waiting"
            row.update({"state": state, "note": note})
        else:
            row.update({"state": "idle", "note": "not this wave"})
        board.append(row)
    cur_n = sum(1 for r in dispatched if r.get("via") == "cursor")
    if cur_n:
        board.append(
            {
                "id": "cursor",
                "name": "Cursor",
                "state": "sent",
                "note": f"{cur_n} follow-up{'s' if cur_n != 1 else ''} sent",
                "shipped": "",
                "next": "",
            }
        )
    return board


def decorate_board(board: list[dict], proofs: dict[str, dict], living: list[dict]) -> list[dict]:
    living_ids = {str(r.get("well") or "") for r in living}
    out = []
    for raw in board:
        row = dict(raw)
        wid = str(row.get("id") or "")
        proof = proofs.get(wid) or {}
        if proof.get("shipped"):
            row["shipped"] = proof["shipped"]
        if proof.get("next"):
            row["next"] = proof["next"]
        if wid in living_ids:
            row["state"] = "cooking"
            row["note"] = "window still open"
        elif row.get("state") == "sent":
            if proof.get("ok") and proof.get("shipped"):
                row["note"] = f"shipped: {proof['shipped'][:90]}"
            elif not living_ids and not proof.get("ok"):
                age = proof.get("age")
                if age is None or age > 120:
                    row["state"] = "empty"
                    row["note"] = "no ship last turn"
                else:
                    row["note"] = "turn finished, waiting receipt"
        elif row.get("state") == "empty" and proof.get("ok") and proof.get("shipped"):
            row["state"] = "sent"
            row["note"] = f"shipped: {proof['shipped'][:90]}"
        out.append(row)
    return out


def harvest_ships(wells: list[dict], proofs: dict[str, dict]) -> list[dict]:
    ships = []
    for well in wells:
        wid = str(well.get("id") or "")
        proof = proofs.get(wid) or {}
        if not proof.get("shipped"):
            continue
        ships.append(
            {
                "id": wid,
                "name": str(well.get("name") or well_title(wid)),
                "shipped": proof.get("shipped") or "",
                "next": proof.get("next") or "",
                "fresh": bool(proof.get("fresh")),
            }
        )
    return ships


def staff_alive() -> list[dict]:
    if os.name != "nt":
        return []
    try:
        out = subprocess.check_output(
            [
                "wmic",
                "process",
                "where",
                "name='grok.exe'",
                "get",
                "ProcessId,CommandLine",
            ],
            text=True,
            timeout=4,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        low = line.lower()
        if "orbit cook" not in low:
            continue
        pid = None
        for part in line.split():
            if part.isdigit():
                pid = int(part)
        well = "cook"
        for name in _well_scan_names():
            if name in low or name.replace("-", " ") in low:
                well = name
                break
        if "leo-aware" in low:
            well = "leoaware"
        if "ghost-continuum" in low:
            well = "ghost"
        rows.append({"well": well, "pid": pid})
    return rows


def skip_reason(
    well: dict,
    live_cwds: list[str],
    proofs: dict[str, dict] | None = None,
) -> str | None:
    slug = str(well.get("id") or "")
    if slug in {"loose", "grok.com", "cursor.com"}:
        return "leftover"
    paths = [Path(p) for p in (well.get("paths") or []) if p]
    real = [p for p in paths if p.is_dir()]
    if not real:
        return "no-clone"
    root = real[0]
    for cwd in live_cwds:
        try:
            if Path(cwd).resolve() == root.resolve() or str(Path(cwd).resolve()).lower().startswith(
                str(root.resolve()).lower() + os.sep
            ):
                return "live-pager"
        except Exception:
            continue
    if cook_pids_on(root) > 0:
        return "cook-running"
    if DESK.is_file():
        try:
            proc = subprocess.run(
                [sys.executable, str(DESK), "check", str(root)],
                capture_output=True,
                text=True,
                timeout=8,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 2 or "OURS" in out or "OCCUPIED" in out:
                return "desk-occupied"
        except Exception:
            pass
    proof = (proofs or {}).get(slug) or {}
    if proof.get("fresh"):
        return "fresh-ship"
    return None


def cook_pids_on(path: Path) -> int:
    if os.name != "nt":
        return 0
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", "name='grok.exe'", "get", "CommandLine"],
            text=True,
            timeout=4,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return 0
    needle = str(path).lower()
    n = 0
    for line in out.splitlines():
        low = line.lower()
        if "orbit cook" in low and needle in low:
            n += 1
    return n


def live_cwds() -> list[str]:
    from snapshot import grok_home, live_sessions

    rows, _ = live_sessions(grok_home())
    return [str(s.get("cwd") or "") for s in rows if s.get("live") and s.get("cwd")]


def roster() -> list[dict]:
    from projects import build_catalog, is_named_well

    out = []
    for well in build_catalog():
        if not is_named_well(str(well.get("id") or "")):
            continue
        paths = [p for p in (well.get("paths") or []) if Path(p).is_dir()]
        if not paths:
            continue
        out.append(
            {
                "id": well["id"],
                "name": well.get("name") or well["id"],
                "paths": paths,
            }
        )
    return out


def spawn_grok(path: Path, prompt: str) -> dict:
    bin_path = grok_bin()
    if not bin_path.is_file():
        return {"error": "grok binary missing", "path": str(path)}
    kwargs: dict = {
        "args": [str(bin_path), "-p", prompt],
        "cwd": str(path),
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NEW_CONSOLE
    try:
        proc = subprocess.Popen(**kwargs)
    except Exception as e:
        return {"error": str(e)[:160], "path": str(path)}
    return {"ok": True, "pid": proc.pid, "path": str(path)}


def cursor_idle_agents() -> list[dict]:
    try:
        from web_adapters import cache_path, read_json
        from pr_state import apply_to_sessions

        cache = read_json(cache_path("cursor_web")) or {}
        rows = []
        for item in cache.get("sessions") or []:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title") or "cursor agent",
                    "agent_name": item.get("status") or item.get("agent_name"),
                    "pr_url": item.get("pr_url"),
                }
            )
        apply_to_sessions(rows)
        return [r for r in rows if r.get("agent_name") != "running" and r.get("id")]
    except Exception:
        return []


def leftover_for_cursor(title: str, proofs: dict[str, dict], wells: list[dict]) -> str:
    low = (title or "").lower()
    for well in wells:
        name = str(well.get("name") or well.get("id") or "").lower()
        wid = str(well.get("id") or "")
        if name and name in low:
            return str((proofs.get(wid) or {}).get("next") or "")
    return ""


def harvest() -> dict:
    wells = roster()
    proofs = gather_proofs(wells)
    living = staff_alive()
    state = load_cook_state()
    board = decorate_board(list(state.get("last_board") or []), proofs, living)
    ships = harvest_ships(wells, proofs)
    staff_now = len(living)
    report = {
        "ok": True,
        "harvested_at": utc_now(),
        "staff_now": staff_now,
        "staff": living,
        "board": board,
        "ships": ships,
        "interval_sec": next_interval(staff_now),
        "next_wave": next_wave_names(board),
    }
    persist_report(report, merge=True)
    return report


def tick(dry_run: bool = False) -> dict:
    live = live_cwds()
    raw_wells = roster()
    proofs = gather_proofs(raw_wells)
    fresh_ids = [wid for wid, proof in proofs.items() if proof.get("fresh")]
    wells = order_wells(raw_wells, prior_sent_ids(), fresh_ids)
    dispatched: list[dict] = []
    skipped: list[dict] = []
    grok_n = 0
    for well in wells:
        reason = skip_reason(well, live, proofs)
        if reason:
            skipped.append({"id": well["id"], "reason": reason})
            continue
        if grok_n >= MAX_GROK:
            skipped.append({"id": well["id"], "reason": "cap"})
            continue
        path = Path(well["paths"][0])
        proof = proofs.get(str(well["id"]))
        prompt = cook_prompt(
            str(well["name"]),
            str(path),
            proof=proof,
            mission=str((proof or {}).get("mission") or mission_excerpt(path)),
            dirty=git_dirty_count(path),
        )
        if dry_run:
            dispatched.append({"id": well["id"], "via": "grok", "dry": True})
            grok_n += 1
            continue
        spawned = spawn_grok(path, prompt)
        if spawned.get("ok"):
            dispatched.append({"id": well["id"], "via": "grok", "pid": spawned.get("pid")})
            grok_n += 1
        else:
            skipped.append({"id": well["id"], "reason": spawned.get("error") or "spawn"})

    cursor_n = 0
    if not dry_run:
        try:
            from brave_grok import followup_cursor_agent
        except Exception:
            followup_cursor_agent = None  # type: ignore
    else:
        followup_cursor_agent = None
    for agent in cursor_idle_agents():
        if cursor_n >= MAX_CURSOR:
            break
        leftover = leftover_for_cursor(str(agent.get("title") or ""), proofs, wells)
        text = cursor_cook_prompt(str(agent.get("title") or "agent"), leftover)
        if dry_run:
            dispatched.append({"id": agent.get("id"), "via": "cursor", "dry": True})
            cursor_n += 1
            continue
        if followup_cursor_agent is None:
            skipped.append({"id": agent.get("id"), "reason": "no-followup"})
            continue
        got = followup_cursor_agent(str(agent.get("id") or ""), text)
        if got.get("error"):
            skipped.append({"id": agent.get("id"), "reason": str(got.get("error"))[:80]})
            continue
        dispatched.append({"id": agent.get("id"), "via": "cursor"})
        cursor_n += 1

    living = staff_alive()
    titles = {str(w["id"]): str(w.get("name") or w["id"]) for w in wells}
    sent_names = []
    for row in dispatched:
        if row.get("via") == "grok":
            sent_names.append(well_title(str(row.get("id")), titles))
        elif row.get("via") == "cursor":
            sent_names.append("Cursor")
    cap_n = sum(1 for s in skipped if s.get("reason") == "cap")
    skip_names = [
        f"{well_title(str(s.get('id')), titles)} ({skip_label(str(s.get('reason')))})"
        for s in skipped
    ]
    board = build_board(wells, dispatched, skipped, living, proofs)
    ships = harvest_ships(wells, proofs)
    nxt = next_wave_names(board)
    nxt_bit = f" Next wave: {', '.join(nxt)}." if nxt else ""
    ship_bits = [f"{s['name']} {s['shipped']}" for s in ships[:4] if s.get("shipped")]
    ship_bit = f" Ships: {'; '.join(ship_bits)}." if ship_bits else ""
    if living:
        summary = (
            f"{len(living)} cook window{'s' if len(living) != 1 else ''} still open. "
            "A window that closes means that turn finished."
            + nxt_bit
            + ship_bit
        )
    elif grok_n or cursor_n:
        summary = (
            f"Last wave done. {grok_n} Grok turn{'s' if grok_n != 1 else ''} finished "
            "(windows closed on purpose). "
            f"{cursor_n} Cursor follow-up{'s' if cursor_n != 1 else ''}. "
            + (
                f"{cap_n} well{'s' if cap_n != 1 else ''} waiting "
                "(only 4 Grok at a time)."
                if cap_n
                else "No wells waiting on the 4-at-a-time cap."
            )
            + nxt_bit
            + ship_bit
        )
    else:
        summary = "No staff sent this wave." + nxt_bit + ship_bit
    detail = f"{grok_n} Grok finished | {cap_n} waiting next wave | {len(living)} open"
    if not dispatched and not skipped:
        detail = "roster empty"
    report = {
        "ok": True,
        "ticked_at": utc_now(),
        "dispatched": dispatched,
        "skipped": skipped,
        "sent": sent_names,
        "waiting": skip_names,
        "board": board,
        "ships": ships,
        "staff_now": len(living),
        "staff": living,
        "detail": detail,
        "summary": summary,
        "next_wave": nxt,
        "interval_sec": next_interval(len(living)),
        "dry_run": dry_run,
        "grok": grok_n,
        "cursor": cursor_n,
    }
    if not dry_run:
        persist_report(report)
    return report


def persist_report(report: dict, merge: bool = False) -> None:
    try:
        from web_adapters import read_json, web_home, write_json
    except Exception:
        return
    path = web_home() / "cook.json"
    state = read_json(path) if path.exists() else {}
    if not isinstance(state, dict):
        state = {}
    if report.get("ticked_at"):
        state["last_tick"] = report.get("ticked_at")
    if report.get("detail"):
        state["last_detail"] = report.get("detail")
    if report.get("summary"):
        state["last_summary"] = report.get("summary")
    if "sent" in report:
        state["last_sent"] = report.get("sent") or []
    if "waiting" in report:
        state["last_waiting"] = report.get("waiting") or []
    if "board" in report:
        state["last_board"] = report.get("board") or []
    if "next_wave" in report:
        state["last_next"] = report.get("next_wave") or []
    if "ships" in report:
        state["last_ships"] = report.get("ships") or []
    if "staff_now" in report:
        state["staff_now"] = report.get("staff_now") or 0
    if "interval_sec" in report:
        state["interval_sec"] = report.get("interval_sec") or IDLE_SECS
    if merge and report.get("harvested_at"):
        state["last_harvest"] = report.get("harvested_at")
    write_json(path, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Orbit COOK tick")
    parser.add_argument("command", choices=["roster", "tick", "prompt", "board", "harvest"])
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--well", default="")
    args = parser.parse_args()
    if args.command == "harvest":
        print(json.dumps(harvest(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "board":
        living = staff_alive()
        print(
            json.dumps(
                {"staff_now": len(living), "staff": living, "roster": [w["id"] for w in roster()]},
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0
    if args.command == "roster":
        print(json.dumps({"wells": roster()}, indent=2, ensure_ascii=True))
        return 0
    if args.command == "prompt":
        wells = [w for w in roster() if w["id"] == args.well] or roster()[:1]
        if not wells:
            print(json.dumps({"error": "no well"}))
            return 1
        path = Path(wells[0]["paths"][0])
        print(
            cook_prompt(
                wells[0]["name"],
                str(path),
                proof=read_receipt(path),
                mission=mission_excerpt(path),
                dirty=git_dirty_count(path),
            )
        )
        return 0
    print(json.dumps(tick(dry_run=args.dry), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
