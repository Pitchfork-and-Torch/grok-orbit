"""Orbit COOK tick. Deploys staff to named wells. Never injects a live TUI.

Arm/disarm is owned by the Orbit app. This script is one tick.
No Windows scheduled task. No Bot tokens. No --always-approve.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CREATE_NEW_CONSOLE = 0x00000010
MAX_GROK = 4
MAX_CURSOR = 2
DESK = Path(os.environ.get("USERPROFILE") or Path.home()) / ".grok" / "desk" / "desk.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def grok_bin() -> Path:
    home = Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok"))
    return home / "bin" / "grok.exe"


def cook_prompt(name: str, path: str) -> str:
    return (
        f"Orbit COOK. You are staff on {name} at {path}. "
        "Read AGENTS.md if present. Desk-check then claim this path. "
        "Improve, test, and ship low-risk work. Default model free-coding. "
        "Do not wait for approval on low-risk. Do not inject into a live TUI. "
        "Do not reboot. Do not change Windows passwords. Do not print secrets. "
        "ASCII only. One meaningful ship then stop this turn. "
        "If the tree is occupied, stop."
    )


def cursor_cook_prompt(title: str) -> str:
    return (
        f"Orbit COOK follow-up on {title}. Continue low-risk improvement. "
        "Do not wait for approval. Do not print secrets. One focused ship."
    )


SKIP_LABEL = {
    "leftover": "not a project well",
    "no-clone": "no local folder",
    "live-pager": "live pager already there",
    "cook-running": "already cooking",
    "desk-occupied": "another agent has this tree",
    "cap": "next wave (only 4 Grok at a time)",
    "no-followup": "Cursor follow-up unavailable",
    "spawn": "could not start Grok",
}

WELL_TITLE = {
    "vela": "VELA",
    "leoaware": "LeoAware",
    "instar": "INSTAR",
    "ghost": "Ghost",
    "grok-orbit": "Grok Orbit",
    "axiom": "AXIOM",
    "safedeposit": "SafeDeposit",
    "orbitstack": "orbitstack",
    "cursor": "Cursor",
}


def skip_label(reason: str) -> str:
    return SKIP_LABEL.get(reason, reason)


def well_title(wid: str, roster_map: dict[str, str] | None = None) -> str:
    if roster_map and wid in roster_map:
        return roster_map[wid]
    if wid in WELL_TITLE:
        return WELL_TITLE[wid]
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


def prior_sent_ids(state: dict | None = None) -> list[str]:
    """Grok wells cooked last wave. Cursor rows are not wells."""
    blob = state if isinstance(state, dict) else load_cook_state()
    ids: list[str] = []
    seen: set[str] = set()
    for row in blob.get("last_board") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("state") or "") != "sent":
            continue
        wid = str(row.get("id") or "")
        if not wid or wid == "cursor" or wid in seen:
            continue
        seen.add(wid)
        ids.append(wid)
    return ids


def order_wells(wells: list[dict], sent_ids: list[str] | None = None) -> list[dict]:
    """Tide: wells that waited last wave go first. Last-sent fill leftover slots."""
    sent = {str(s) for s in (sent_ids or []) if s and s != "cursor"}
    if not sent:
        return list(wells)
    waiting = [w for w in wells if str(w.get("id") or "") not in sent]
    cooked = [w for w in wells if str(w.get("id") or "") in sent]
    return waiting + cooked


def next_wave_names(board: list[dict], limit: int = MAX_GROK) -> list[str]:
    names: list[str] = []
    for row in board:
        if str(row.get("state") or "") != "waiting":
            continue
        names.append(str(row.get("name") or well_title(str(row.get("id") or ""))))
        if len(names) >= limit:
            break
    return names


def build_board(
    wells: list[dict],
    dispatched: list[dict],
    skipped: list[dict],
    living: list[dict],
) -> list[dict]:
    living_ids = {str(r.get("well") or "") for r in living}
    sent_grok = {str(r.get("id")) for r in dispatched if r.get("via") == "grok"}
    skip_map = {str(s.get("id")): str(s.get("reason")) for s in skipped}
    board: list[dict] = []
    for well in wells:
        wid = str(well["id"])
        name = str(well.get("name") or well_title(wid))
        if wid in living_ids:
            board.append(
                {"id": wid, "name": name, "state": "cooking", "note": "window still open"}
            )
        elif wid in sent_grok:
            board.append(
                {
                    "id": wid,
                    "name": name,
                    "state": "sent",
                    "note": "turn finished, window closed",
                }
            )
        elif wid in skip_map:
            board.append(
                {
                    "id": wid,
                    "name": name,
                    "state": "waiting",
                    "note": skip_label(skip_map[wid]),
                }
            )
        else:
            board.append({"id": wid, "name": name, "state": "idle", "note": "not this wave"})
    cur_n = sum(1 for r in dispatched if r.get("via") == "cursor")
    if cur_n:
        board.append(
            {
                "id": "cursor",
                "name": "Cursor",
                "state": "sent",
                "note": f"{cur_n} follow-up{'s' if cur_n != 1 else ''} sent",
            }
        )
    return board


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
        for name in ("vela", "leoaware", "instar", "ghost", "grok-orbit", "axiom", "safedeposit", "orbitstack"):
            if name in low or name.replace("-", " ") in low:
                well = name
                break
        if "leo-aware" in low:
            well = "leoaware"
        if "ghost-continuum" in low:
            well = "ghost"
        if "axiom-wear" in low:
            well = "axiom"
        rows.append({"well": well, "pid": pid})
    return rows


def skip_reason(well: dict, live_cwds: list[str]) -> str | None:
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


def tick(dry_run: bool = False) -> dict:
    live = live_cwds()
    wells = order_wells(roster(), prior_sent_ids())
    dispatched: list[dict] = []
    skipped: list[dict] = []
    grok_n = 0
    for well in wells:
        reason = skip_reason(well, live)
        if reason:
            skipped.append({"id": well["id"], "reason": reason})
            continue
        if grok_n >= MAX_GROK:
            skipped.append({"id": well["id"], "reason": "cap"})
            continue
        path = Path(well["paths"][0])
        prompt = cook_prompt(str(well["name"]), str(path))
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
        text = cursor_cook_prompt(str(agent.get("title") or "agent"))
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
    board = build_board(wells, dispatched, skipped, living)
    nxt = next_wave_names(board)
    nxt_bit = f" Next wave: {', '.join(nxt)}." if nxt else ""
    if living:
        summary = (
            f"{len(living)} cook window{'s' if len(living) != 1 else ''} still open. "
            "A window that closes means that turn finished."
            + nxt_bit
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
        )
    else:
        summary = "No staff sent this wave." + nxt_bit
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
        "staff_now": len(living),
        "staff": living,
        "detail": detail,
        "summary": summary,
        "next_wave": nxt,
        "dry_run": dry_run,
        "grok": grok_n,
        "cursor": cursor_n,
    }
    if not dry_run:
        persist_report(report)
    return report


def persist_report(report: dict) -> None:
    try:
        from web_adapters import read_json, web_home, write_json
    except Exception:
        return
    path = web_home() / "cook.json"
    state = read_json(path) if path.exists() else {}
    if not isinstance(state, dict):
        state = {}
    state["last_tick"] = report.get("ticked_at")
    state["last_detail"] = report.get("detail")
    state["last_summary"] = report.get("summary")
    state["last_sent"] = report.get("sent") or []
    state["last_waiting"] = report.get("waiting") or []
    state["last_board"] = report.get("board") or []
    state["last_next"] = report.get("next_wave") or []
    state["staff_now"] = report.get("staff_now") or 0
    write_json(path, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="Orbit COOK tick")
    parser.add_argument("command", choices=["roster", "tick", "prompt", "board"])
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--well", default="")
    args = parser.parse_args()
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
        print(cook_prompt(wells[0]["name"], wells[0]["paths"][0]))
        return 0
    print(json.dumps(tick(dry_run=args.dry), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
