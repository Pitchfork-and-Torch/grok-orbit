"""Local gh PR state cache for Orbit Lens.

Read-only `gh pr view`. Never prints tokens. Never writes GitHub.
Cache lives under the Orbit web cache directory (no secrets).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

TTL_SECS = 300
CREATE_NO_WINDOW = 0x08000000


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


def classify(state: str | None, is_draft: bool = False) -> str:
    key = (state or "").strip().upper()
    if key == "OPEN" and is_draft:
        return "draft"
    if key == "OPEN":
        return "open"
    if key == "MERGED":
        return "merged"
    if key == "CLOSED":
        return "closed"
    return "unknown"


def needs_clearance(pr_state: str | None) -> bool:
    key = (pr_state or "unknown").strip().lower()
    return key in ("open", "unknown", "")


def parse_files(payload: dict) -> tuple[list[str], int]:
    rows = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], 0
    paths: list[str] = []
    for item in rows:
        if isinstance(item, dict):
            path = item.get("path") or item.get("filename") or ""
        else:
            path = str(item or "")
        path = str(path).strip()
        if path:
            paths.append(path)
    return paths[:8], len(rows)


def row_from_payload(payload: dict) -> dict:
    state = classify(payload.get("state"), bool(payload.get("isDraft") or payload.get("is_draft")))
    files, count = parse_files(payload)
    title = str(payload.get("title") or "")[:180]
    return {
        "state": state,
        "is_draft": bool(payload.get("isDraft") or payload.get("is_draft")),
        "title": title,
        "files": files,
        "file_count": count,
        "fetched_at": int(time.time()),
    }


def cache_path() -> Path:
    from web_adapters import web_home

    return web_home() / "cache" / "pr_state.json"


def load_cache(path: Path | None = None) -> dict:
    from web_adapters import read_json

    data = read_json(path or cache_path())
    return data if isinstance(data, dict) else {"updated_at": 0, "prs": {}}


def save_cache(cache: dict, path: Path | None = None) -> Path:
    from web_adapters import write_json

    dest = path or cache_path()
    cache = dict(cache)
    cache["updated_at"] = int(time.time())
    if "prs" not in cache or not isinstance(cache["prs"], dict):
        cache["prs"] = {}
    write_json(dest, cache)
    return dest


def cache_is_fresh(cache: dict, urls: list[str], now: float | None = None) -> bool:
    now = time.time() if now is None else now
    updated = float(cache.get("updated_at") or 0)
    if now - updated > TTL_SECS:
        return False
    prs = cache.get("prs") if isinstance(cache.get("prs"), dict) else {}
    for url in urls:
        key = normalize_pr_url(url)
        if key and key not in prs:
            return False
    return True


def apply_to_sessions(sessions: list, cache: dict | None = None) -> list:
    data = cache if cache is not None else load_cache()
    prs = data.get("prs") if isinstance(data.get("prs"), dict) else {}
    for session in sessions:
        url = session.get("pr_url")
        if not url:
            continue
        row = prs.get(normalize_pr_url(str(url)))
        if not isinstance(row, dict):
            continue
        session["pr_state"] = row.get("state") or "unknown"
        session["pr_files"] = list(row.get("files") or [])[:8]
        count = row.get("file_count")
        session["pr_file_count"] = int(count) if isinstance(count, (int, float)) else len(session["pr_files"])
    return sessions


def urls_from_cursor_cache() -> list[str]:
    from web_adapters import cache_path as surface_cache, read_json

    data = read_json(surface_cache("cursor_web"))
    if not isinstance(data, dict):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for session in data.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        url = str(session.get("pr_url") or "").strip()
        if not url:
            continue
        key = normalize_pr_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out


def gh_pr_view(url: str) -> dict | None:
    kwargs: dict = {
        "args": ["gh", "pr", "view", url, "--json", "state,isDraft,title,files"],
        "capture_output": True,
        "text": True,
        "timeout": 20,
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = subprocess.run(**kwargs)
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "")
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def refresh(urls: list[str] | None = None, dest: Path | None = None) -> dict:
    wanted = [u for u in (urls if urls is not None else urls_from_cursor_cache()) if u]
    cache = load_cache(dest)
    prs = cache.get("prs") if isinstance(cache.get("prs"), dict) else {}
    fetched = 0
    skipped = 0
    for url in wanted:
        key = normalize_pr_url(url)
        if not key:
            continue
        payload = gh_pr_view(url)
        if payload is None:
            skipped += 1
            if key not in prs:
                prs[key] = {
                    "state": "unknown",
                    "is_draft": False,
                    "title": "",
                    "files": [],
                    "file_count": 0,
                    "fetched_at": int(time.time()),
                }
            continue
        prs[key] = row_from_payload(payload)
        fetched += 1
    cache["prs"] = prs
    save_cache(cache, dest)
    return {
        "ok": True,
        "count": len(wanted),
        "fetched": fetched,
        "skipped": skipped,
        "cached": len(prs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Orbit PR state cache (gh pr view, no tokens)")
    parser.add_argument("command", choices=["refresh", "lookup"], nargs="?", default="refresh")
    parser.add_argument("urls", nargs="*")
    args = parser.parse_args()
    if args.command == "lookup":
        cache = load_cache()
        prs = cache.get("prs") or {}
        out = {normalize_pr_url(u): prs.get(normalize_pr_url(u)) for u in args.urls}
        print(json.dumps(out, indent=2, ensure_ascii=True))
        return 0
    result = refresh(args.urls or None)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
