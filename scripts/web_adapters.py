"""Consented grok.com / Cursor web adapters.

Isolated Playwright profiles only. Never copies Chrome/Edge cookies.
Never runs a browser from the snapshot tick. Probe and login are explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

SURFACES = ("grok_web", "cursor_web")
START_URLS = {
    "grok_web": "https://accounts.x.ai/sign-in?redirect=grok-com",
    "cursor_web": "https://cursor.com/agents",
}
GROK_LOGIN = (
    "accounts.x.ai",
    "sign in to grok",
    "log in to grok",
    "/sign-in",
    "data-testid=\"login\"",
)
CURSOR_LOGIN = (
    "/api/auth/login",
    "sign in to cursor",
    "workos",
    "authenticator",
)
GROK_HREF = re.compile(
    r"(?:https?://(?:www\.)?grok\.com)?/(?:c|chat)/[A-Za-z0-9._~-]+",
    re.I,
)
CURSOR_HREF = re.compile(
    r"(?:https?://(?:www\.)?cursor\.com)?/(?:agents?|background-agent)/[A-Za-z0-9._~-]+"
    r"|(?:https?://(?:www\.)?cursor\.com)?/agents?\?[^'\"\s]*\bid=",
    re.I,
)
A_TAG = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.I | re.S)
HREF_ATTR = re.compile(r"""href\s*=\s*['"]([^'"]+)['"]""", re.I)
TAG = re.compile(r"<[^>]+>")
CURSOR_STATUS_TAIL = re.compile(
    r"\s*\[(?:BACKGROUND_COMPOSER_STATUS_)?([A-Z_]+)\]\s*$"
)
CURSOR_STATUS_MAP = {
    "RUNNING": "running",
    "CREATING": "running",
    "ACTIVE": "active",
    "FINISHED": "finished",
    "COMPLETED": "finished",
    "ERROR": "error",
    "FAILED": "error",
    "EXPIRED": "error",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
    "ARCHIVED": "archived",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ascii_hyphens(text: str) -> str:
    return (text or "").replace("\u2014", " - ").replace("\u2013", " - ").replace("\u2212", "-")


def normalize_cursor_status(title: str, status: str | None = None) -> tuple[str, str]:
    raw = (status or "").strip()
    t = title or ""
    m = CURSOR_STATUS_TAIL.search(t)
    if m:
        raw = raw or m.group(1)
        t = CURSOR_STATUS_TAIL.sub("", t).strip()
    t = ascii_hyphens(t).strip() or "untitled"
    key = raw.upper().replace("BACKGROUND_COMPOSER_STATUS_", "")
    mapped = CURSOR_STATUS_MAP.get(key)
    if mapped:
        return t[:180], mapped
    if not key:
        return t[:180], "unknown"
    return t[:180], key.lower()[:24]


def cursor_session_fields(status: str) -> tuple[str, str, str]:
    if status == "running":
        return "live_working", "ok", "running"
    if status == "error":
        return "needs_input", "degraded", "error"
    if status in {"finished", "cancelled", "archived", "active", "unknown"}:
        return "disk", "ok", status
    return "disk", "ok", status or "unknown"


def web_home() -> Path:
    raw = os.environ.get("ORBIT_WEB_HOME")
    if raw:
        return Path(raw)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or "."
    return Path(base) / "com.knock.grokorbit" / "web"


def consent_path() -> Path:
    return web_home() / "consent.json"


def cache_path(surface: str) -> Path:
    return web_home() / "cache" / f"{surface}.json"


def profile_dir(surface: str) -> Path:
    return profile_dir_for(surface, resolve_browser().get("name") or "unknown")


def available_browsers() -> list[dict]:
    """Preferred first. Used when Brave merges into the already-running instance."""
    preferred = resolve_browser()
    out = []
    if preferred.get("executable"):
        out.append(preferred)
    local = os.environ.get("LOCALAPPDATA") or ""
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    extras = [
        ("msedge", Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        ("msedge", Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        ("brave", Path(pf) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        ("chrome", Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    seen = {out[0]["executable"]} if out else set()
    for name, path in extras:
        if path.is_file() and str(path) not in seen:
            seen.add(str(path))
            out.append({"name": name, "kind": "system", "executable": str(path)})
    return out


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def playwright_importable() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("playwright") is not None
    except Exception:
        return False


def _bundled_chromium() -> Path | None:
    root = Path(os.environ.get("LOCALAPPDATA") or "") / "ms-playwright"
    if not root.is_dir():
        return None
    for pat in ("chromium-*/chrome-win64/chrome.exe", "chromium-*/chrome-win/chrome.exe"):
        hits = sorted(root.glob(pat), reverse=True)
        if hits:
            return hits[0]
    return None


def resolve_browser() -> dict:
    """Pick an isolated-capable browser. Never the user's Default profile.

    Default is Brave when installed. Override with ORBIT_WEB_BROWSER=
    brave|msedge|chrome|chromium.
    """
    local = os.environ.get("LOCALAPPDATA") or ""
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    found: list[dict] = []
    bundled = _bundled_chromium()
    if bundled and bundled.is_file():
        found.append({"name": "chromium", "kind": "bundled", "executable": str(bundled)})
    for name, path in (
        ("brave", Path(pf) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        ("brave", Path(local) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        ("brave", Path(pf86) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
        ("msedge", Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        ("msedge", Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        ("chrome", Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        ("chrome", Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ):
        if path.is_file() and not any(x.get("executable") == str(path) for x in found):
            found.append({"name": name, "kind": "system", "executable": str(path)})
    if not found:
        return {
            "name": None,
            "kind": "missing",
            "executable": None,
            "detail": "no Brave/Edge/Chrome/Playwright Chromium binary",
        }
    want = (os.environ.get("ORBIT_WEB_BROWSER") or "brave").strip().lower()
    for item in found:
        if item["name"] == want:
            return item
    # Brave first among system browsers if no explicit hit.
    for item in found:
        if item["name"] == "brave":
            return item
    return found[0]


def chromium_launch_args() -> list[str]:
    return [
        "--disable-features=Translate,AutomationControlled",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def launch_persistent(p, profile: Path, headed: bool):
    resolved = resolve_browser()
    exe = resolved.get("executable")
    if not exe:
        raise RuntimeError(resolved.get("detail") or "no browser binary")
    return p.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        executable_path=exe,
        headless=not headed,
        viewport={"width": 1280, "height": 800},
        args=chromium_launch_args(),
        ignore_default_args=["--enable-automation"],
    )


def native_login_cmd(surface: str, resolved: dict | None = None) -> list[str]:
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface}")
    resolved = resolved or resolve_browser()
    exe = resolved.get("executable")
    if not exe:
        raise RuntimeError(resolved.get("detail") or "no browser binary")
    profile = profile_dir_for(surface, resolved["name"])
    profile.mkdir(parents=True, exist_ok=True)
    return [
        exe,
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--new-window",
        "--start-maximized",
        "--window-position=80,80",
        "--window-size=1280,860",
        "--disable-features=Translate",
        START_URLS[surface],
    ]


def profile_dir_for(surface: str, browser_name: str) -> Path:
    name = (browser_name or "unknown").replace(" ", "-")
    # grok.com as first paint was crashing isolated Edge on the older profile.
    # accounts.x.ai via a clean orbit_login profile stays visible.
    if name == "msedge" and surface == "grok_web":
        return web_home() / "profiles" / name / "orbit_login"
    return web_home() / "profiles" / name / surface


def pids_using_profile(profile: Path) -> set[int]:
    needle = str(profile)
    env = os.environ.copy()
    env["ORBIT_PROFILE_NEEDLE"] = needle
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process | Where-Object { "
                    "$_.CommandLine -and $_.CommandLine.Contains($env:ORBIT_PROFILE_NEEDLE) "
                    "-and $_.Name -match '^(brave|msedge|chrome)\\.exe$' } | "
                    "Select-Object -ExpandProperty ProcessId"
                ),
            ],
            text=True,
            timeout=8,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except Exception:
        return set()
    pids = set()
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.add(int(line))
    return pids


def visible_isolated_window(profile: Path) -> dict | None:
    from focus import hwnds_for_pid

    for pid in pids_using_profile(profile):
        for hwnd, title in hwnds_for_pid(pid):
            if title.strip():
                return {"pid": pid, "hwnd": hwnd, "title": title}
    return None


def wait_profile_idle(profile: Path, timeout: int = 1800) -> bool:
    import time

    start = time.time()
    seen = False
    idle = 0
    while time.time() - start < timeout:
        pids = pids_using_profile(profile)
        if pids:
            seen = True
            idle = 0
        else:
            if seen:
                idle += 1
                if idle >= 2:
                    return True
            elif time.time() - start > 12:
                return False
        time.sleep(1.0)
    return False


def consent_state() -> dict:
    data = read_json(consent_path())
    if not isinstance(data, dict) or not data.get("granted"):
        return {
            "granted": False,
            "granted_at": None,
            "surfaces": [],
        }
    surfaces = [s for s in (data.get("surfaces") or SURFACES) if s in SURFACES]
    return {
        "granted": True,
        "granted_at": data.get("granted_at"),
        "surfaces": surfaces or list(SURFACES),
    }


def grant_consent() -> dict:
    payload = {
        "granted": True,
        "granted_at": utc_now(),
        "surfaces": list(SURFACES),
        "note": "isolated Orbit profile only; never copies Chrome or Edge cookies",
    }
    write_json(consent_path(), payload)
    for surface in SURFACES:
        profile_dir(surface).mkdir(parents=True, exist_ok=True)
    return payload


def revoke_consent() -> dict:
    path = consent_path()
    if path.exists():
        path.unlink()
    return {"granted": False}


def looks_like_login(surface: str, html: str, final_url: str) -> bool:
    blob = f"{final_url}\n{html}".lower()
    markers = GROK_LOGIN if surface == "grok_web" else CURSOR_LOGIN
    if any(m.lower() in blob for m in markers):
        return True
    host = (urlparse(final_url).netloc or "").lower()
    if surface == "grok_web" and "accounts.x.ai" in host:
        return True
    if surface == "cursor_web" and "/api/auth/login" in (urlparse(final_url).path or "").lower():
        return True
    return False


def abs_url(surface: str, href: str) -> str:
    base = "https://grok.com" if surface == "grok_web" else "https://cursor.com"
    if href.startswith("http://") or href.startswith("https://"):
        return href.split("#")[0]
    return urljoin(base + "/", href.lstrip("/")).split("#")[0]


def web_id(surface: str, url: str) -> str:
    prefix = "web:grok:" if surface == "grok_web" else "web:cursor:"
    parsed = urlparse(url)
    if surface == "cursor_web":
        from urllib.parse import parse_qs

        qid = (parse_qs(parsed.query).get("id") or [""])[0]
        if qid and re.fullmatch(r"[A-Za-z0-9._~-]{4,}", qid):
            return prefix + qid[:80]
    path = parsed.path.rstrip("/")
    tail = path.split("/")[-1] if path else ""
    skip = {"agents", "agent", "background-agent", "c", "chat"}
    if tail and tail.lower() not in skip and re.fullmatch(r"[A-Za-z0-9._~-]{4,}", tail):
        return prefix + tail[:80]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return prefix + digest


def parse_surface(surface: str, html: str, final_url: str = "") -> dict:
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface}")
    href_re = GROK_HREF if surface == "grok_web" else CURSOR_HREF
    items: list[dict] = []
    seen: set[str] = set()
    for tag, inner in A_TAG.findall(html or ""):
        hm = HREF_ATTR.search(tag)
        if not hm:
            continue
        href = hm.group(1).strip()
        if not href_re.search(href):
            continue
        url = abs_url(surface, href)
        if url in seen:
            continue
        title = TAG.sub("", inner).strip()
        title = re.sub(r"\s+", " ", title)
        if not title:
            title = urlparse(url).path.rstrip("/").split("/")[-1] or url
        seen.add(url)
        items.append(
            {
                "id": web_id(surface, url),
                "title": title[:180],
                "url": url,
            }
        )
        if len(items) >= 24:
            break
    if not items:
        for href in href_re.findall(html or ""):
            url = abs_url(surface, href)
            if url in seen:
                continue
            seen.add(url)
            items.append(
                {
                    "id": web_id(surface, url),
                    "title": urlparse(url).path.rstrip("/").split("/")[-1] or url,
                    "url": url,
                }
            )
            if len(items) >= 24:
                break
    logged_in = bool(items) and not looks_like_login(surface, html, final_url)
    if looks_like_login(surface, html, final_url) and not items:
        logged_in = False
    return {
        "surface": surface,
        "logged_in": logged_in,
        "sessions": items,
    }


def cache_to_status(surface: str, cache: dict | None, granted: bool) -> dict:
    if not granted:
        return {
            "surface": surface,
            "status": "needs_consent",
            "detail": "isolated browser consent not granted",
            "probed_at": None,
            "sessions": [],
        }
    if not cache:
        return {
            "surface": surface,
            "status": "unauth",
            "detail": "consent granted; no probe yet. Open login in the isolated profile.",
            "probed_at": None,
            "sessions": [],
        }
    return {
        "surface": surface,
        "status": cache.get("status") or "degraded",
        "detail": cache.get("detail") or "",
        "probed_at": cache.get("probed_at"),
        "sessions": cache.get("sessions") or [],
        "final_url": cache.get("final_url"),
    }


def status() -> dict:
    granted = consent_state()
    out_surfaces = {}
    sessions = []
    for surface in SURFACES:
        cache = read_json(cache_path(surface))
        if not isinstance(cache, dict):
            cache = None
        row = cache_to_status(surface, cache, granted["granted"] and surface in granted["surfaces"])
        out_surfaces[surface] = row
        for item in row.get("sessions") or []:
            title = item.get("title") or item.get("id") or ""
            agent_status = item.get("status")
            state = "disk"
            health = "ok"
            agent_name = None
            if surface == "cursor_web":
                title, agent_status = normalize_cursor_status(str(title), str(agent_status) if agent_status else None)
                state, health, agent_name = cursor_session_fields(agent_status)
            sessions.append(
                {
                    **item,
                    "title": title,
                    "status": agent_status,
                    "source": surface,
                    "cwd": "grok.com" if surface == "grok_web" else "cursor.com",
                    "state": state,
                    "health": health,
                    "agent_name": agent_name,
                }
            )
    browser = resolve_browser()
    daily = running_browser_names()
    return {
        "consent": granted,
        "playwright": playwright_importable(),
        "browser": browser,
        "daily": {
            "brave": "brave" in daily,
            "msedge": "msedge" in daily,
            "chrome": "chrome" in daily,
            "note": "daily Brave can already be signed in. Orbit does not copy those cookies.",
        },
        "home": str(web_home()),
        "isolated": True,
        "copies_browser_profile": False,
        "surfaces": out_surfaces,
        "sessions": sessions,
    }


def running_browser_names() -> set[str]:
    found = set()
    try:
        tl = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            errors="replace",
            timeout=4,
        )
    except Exception:
        return found
    for line in tl.lower().splitlines():
        if line.startswith('"brave.exe"'):
            found.add("brave")
        elif line.startswith('"msedge.exe"'):
            found.add("msedge")
        elif line.startswith('"chrome.exe"'):
            found.add("chrome")
    return found


def open_daily(surface: str) -> dict:
    if surface not in SURFACES:
        return {"error": f"unknown surface {surface}"}
    url = START_URLS[surface]
    try:
        if os.name == "nt":
            subprocess.Popen(["cmd", "/C", "start", "", url], shell=False)
        else:
            subprocess.Popen(["xdg-open", url])
    except Exception as e:
        return {"error": str(e), "url": url}
    return {
        "ok": True,
        "url": url,
        "daily": sorted(running_browser_names()),
        "detail": "opened in the default/daily browser. This is not the isolated Orbit profile.",
    }


def save_cache(surface: str, parsed: dict, final_url: str, status_name: str, detail: str) -> dict:
    payload = {
        "surface": surface,
        "probed_at": utc_now(),
        "final_url": final_url,
        "status": status_name,
        "detail": detail,
        "sessions": parsed.get("sessions") or [],
    }
    write_json(cache_path(surface), payload)
    return payload


def probe(surface: str, headed: bool = False) -> dict:
    if surface not in SURFACES:
        return {"error": f"unknown surface {surface}"}
    granted = consent_state()
    if not granted["granted"] or surface not in granted["surfaces"]:
        return {"error": "consent not granted", "status": "needs_consent"}
    if not playwright_importable():
        return {"error": "playwright not installed", "status": "offline"}
    resolved = resolve_browser()
    if not resolved.get("executable"):
        return {
            "error": resolved.get("detail") or "no browser binary",
            "status": "offline",
            "browser": resolved,
        }
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return {"error": f"playwright import failed: {e}", "status": "offline"}
    profile = profile_dir(surface)
    profile.mkdir(parents=True, exist_ok=True)
    url = START_URLS[surface]
    try:
        with sync_playwright() as p:
            ctx = launch_persistent(p, profile, headed=headed)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1200)
            final_url = page.url
            html = page.content()
            ctx.close()
    except Exception as e:
        return save_cache(
            surface,
            {"sessions": []},
            url,
            "degraded",
            f"probe failed: {type(e).__name__}: {e}",
        )
    parsed = parse_surface(surface, html, final_url)
    if looks_like_login(surface, html, final_url) or not parsed["logged_in"]:
        return save_cache(
            surface,
            parsed,
            final_url,
            "unauth",
            "login page in isolated profile; open login and sign in once",
        )
    n = len(parsed["sessions"])
    return save_cache(
        surface,
        parsed,
        final_url,
        "ok",
        f"{n} conversation{'' if n == 1 else 's'} from isolated profile",
    )


def open_login(surface: str, force_browser: str | None = None) -> dict:
    if surface not in SURFACES:
        return {"error": f"unknown surface {surface}"}
    granted = consent_state()
    if not granted["granted"]:
        return {"error": "consent not granted"}
    import time

    running = set()
    try:
        tl = subprocess.check_output(["tasklist", "/FO", "CSV", "/NH"], text=True, errors="replace", timeout=4)
        low = tl.lower()
        if "brave.exe" in low:
            running.add("brave")
        if "msedge.exe" in low:
            running.add("msedge")
        if "chrome.exe" in low:
            running.add("chrome")
    except Exception:
        pass
    browsers = available_browsers()
    if force_browser:
        browsers.sort(key=lambda b: 0 if b.get("name") == force_browser else 1)
    else:
        browsers.sort(key=lambda b: 0 if b.get("name") not in running else 1)

    tried = []
    for resolved in browsers:
        profile = profile_dir_for(surface, resolved["name"])
        try:
            cmd = native_login_cmd(surface, resolved)
            subprocess.Popen(cmd)
        except Exception as e:
            tried.append({"browser": resolved["name"], "error": str(e)})
            continue
        time.sleep(4.0)
        hit = visible_isolated_window(profile)
        if hit:
            return {
                "ok": True,
                "waiting": True,
                "detail": (
                    f"opened isolated {resolved['name']} window '{hit['title']}'. "
                    "This is not daily Brave. Sign in, then refresh cache."
                ),
                "browser": resolved,
                "profile": str(profile),
                "pids": sorted(pids_using_profile(profile)),
                "window": hit,
                "tried": tried,
            }
        tried.append(
            {
                "browser": resolved["name"],
                "error": "no visible isolated window; daily browser likely ate the launch",
            }
        )
    return {
        "error": "could not keep an isolated browser process running",
        "tried": tried,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orbit consented web adapters")
    parser.add_argument(
        "command",
        choices=["status", "grant", "revoke", "probe", "login", "parse", "daily"],
    )
    parser.add_argument("surface", nargs="?", choices=list(SURFACES))
    parser.add_argument("--html", help="parse a local HTML fixture (no browser)")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--browser", choices=["brave", "msedge", "chrome", "chromium"])
    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "grant":
        print(json.dumps(grant_consent(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "revoke":
        print(json.dumps(revoke_consent(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "parse":
        if not args.surface or not args.html:
            print("parse needs surface and --html", file=sys.stderr)
            return 2
        html = Path(args.html).read_text(encoding="utf-8")
        print(json.dumps(parse_surface(args.surface, html), indent=2, ensure_ascii=True))
        return 0
    if args.command == "daily":
        if not args.surface:
            print("surface required", file=sys.stderr)
            return 2
        print(json.dumps(open_daily(args.surface), indent=2, ensure_ascii=True))
        return 0
    if args.command in ("probe", "login"):
        if not args.surface:
            print("surface required", file=sys.stderr)
            return 2
        if args.command == "login":
            if args.browser:
                os.environ["ORBIT_WEB_BROWSER"] = args.browser
            print(json.dumps(open_login(args.surface, force_browser=args.browser), indent=2, ensure_ascii=True))
        else:
            print(json.dumps(probe(args.surface, headed=args.headed), indent=2, ensure_ascii=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
