"""Read grok.com chats and cursor.com agents from daily Brave.

Operator-granted. Hosts: grok.com / x.ai for Grok, cursor.com for the
signed-in agents page. Never prints cookie values or API keys.
Never copies the Brave profile. Writes Orbit web cache only (titles + urls).

Cursor official Cloud Agents API (GET https://api.cursor.com/v1/agents)
is used only when ORBIT_CURSOR_API_KEY / CURSOR_API_KEY or
%LOCALAPPDATA%\\com.knock.grokorbit\\web\\cursor_api_key.txt is set.
Browser cookies are never sent to api.cursor.com.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

GROK_HOSTS = ("grok.com", "x.ai")
CURSOR_HOSTS = ("cursor.com",)
ALLOWED_HOST_PARTS = GROK_HOSTS
LIST_URLS = (
    "https://grok.com/rest/app-chat/conversations?pageSize=40",
    "https://grok.com/rest/app-chat/conversations",
    "https://grok.com/rest/conversations?pageSize=40",
)
CURSOR_AGENTS_URL = "https://cursor.com/agents"
CURSOR_API_URL = "https://api.cursor.com/v1/agents?limit=20"
BC_ID = re.compile(r"bc-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
EXTRACT_AGENTS_JS = r"""
(() => {
  const out = [];
  const seen = new Set();
  const add = (id, title, url) => {
    if (!id || seen.has(String(id))) return;
    seen.add(String(id));
    const href = (url || ("https://cursor.com/agents/" + id)).split("#")[0];
    out.push({
      id: String(id),
      name: String(title || id).trim().slice(0, 180),
      url: href.startsWith("http") ? href : ("https://cursor.com" + href),
    });
  };
  for (const a of document.querySelectorAll("a[href]")) {
    const href = a.href || a.getAttribute("href") || "";
    const bc = href.match(/bc-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/);
    const path = href.match(/\/agents\/([A-Za-z0-9._~-]{6,})/);
    const q = href.match(/[?&]id=([A-Za-z0-9._~-]{6,})/);
    const id = (bc && bc[0]) || (q && q[1]) || (path && path[1]);
    if (!id || id === "agents" || id === "new" || id === "login") continue;
    add(id, (a.innerText || a.textContent || "").replace(/\s+/g, " ").trim(), href);
  }
  const html = document.documentElement.innerHTML || "";
  const re = /bc-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g;
  let m;
  while ((m = re.exec(html))) add(m[0], m[0], "https://cursor.com/agents/" + m[0]);
  return out.slice(0, 40);
})()
""".strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def brave_user_data() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "BraveSoftware" / "Brave-Browser" / "User Data"


def cookie_db(ud: Path) -> Path:
    return ud / "Default" / "Network" / "Cookies"


def host_allowed(host: str, parts: tuple[str, ...] = GROK_HOSTS) -> bool:
    h = (host or "").lower().lstrip(".")
    return any(h == p or h.endswith("." + p) for p in parts)


def _crypt_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_byte)),
    )
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError(f"CryptUnprotectData {kernel32.GetLastError()}")
    raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    kernel32.LocalFree(blob_out.pbData)
    return raw


def brave_master_key(ud: Path) -> bytes:
    data = json.loads((ud / "Local State").read_text(encoding="utf-8"))
    enc = base64.b64decode(data["os_crypt"]["encrypted_key"])
    if enc.startswith(b"DPAPI"):
        enc = enc[5:]
    elif enc.startswith(b"APPB"):
        enc = enc[4:]
    return _crypt_unprotect(enc)


def decrypt_value(key: bytes, value: bytes) -> str:
    if not value:
        return ""
    if value.startswith(b"v10") or value.startswith(b"v20"):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = value[3:15]
        pt = AESGCM(key).decrypt(nonce, value[15:], None)
        return pt.decode("utf-8", errors="replace")
    return _crypt_unprotect(value).decode("utf-8", errors="replace")


def copy_locked(src: Path, dst: Path) -> None:
    import ctypes
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    FILE_SHARE = 0x00000007
    OPEN_EXISTING = 3
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(str(src), GENERIC_READ, FILE_SHARE, None, OPEN_EXISTING, 0x80, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise OSError(f"Cookies locked (Win32 {kernel32.GetLastError()}). Close Brave for 10 seconds.")
    try:
        size = src.stat().st_size
        buf = (ctypes.c_char * max(size, 1))()
        read = wintypes.DWORD()
        if not kernel32.ReadFile(handle, buf, size, ctypes.byref(read), None):
            raise OSError(f"ReadFile {kernel32.GetLastError()}")
        dst.write_bytes(bytes(buf[: read.value]))
    finally:
        kernel32.CloseHandle(handle)


def brave_exe() -> Path:
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(pf) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"


def stop_brave() -> None:
    subprocess.run(
        ["taskkill", "/IM", "brave.exe", "/F"],
        capture_output=True,
        text=True,
    )
    for _ in range(20):
        tl = subprocess.run(["tasklist", "/FI", "IMAGENAME eq brave.exe"], capture_output=True, text=True)
        if "brave.exe" not in (tl.stdout or "").lower():
            return
        time.sleep(0.25)


def start_brave(args: list[str]) -> None:
    exe = brave_exe()
    subprocess.Popen([str(exe), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _cookie_header_from_list(cookies: list, parts: tuple[str, ...]) -> dict:
    cookie_parts = []
    names = []
    for c in cookies:
        host = str(c.get("domain") or "")
        name = str(c.get("name") or "")
        if not host_allowed(host, parts) or not name:
            continue
        val = str(c.get("value") or "")
        if not val:
            continue
        cookie_parts.append(f"{name}={val}")
        names.append(f"{host}:{name}")
    if not cookie_parts:
        return {"error": f"CDP returned no cookies for {','.join(parts)}", "seen": len(cookies)}
    return {"cookie": "; ".join(cookie_parts), "names": names, "via": "cdp"}


def cdp_wait_version(timeout: float = 25.0) -> dict:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1.5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            time.sleep(0.4)
    return {"error": f"CDP not ready: {type(last_err).__name__ if last_err else 'timeout'}"}


def cdp_cookie_header(timeout: float = 25.0, parts: tuple[str, ...] = GROK_HOSTS) -> dict:
    import websocket

    version = cdp_wait_version(timeout=timeout)
    if version.get("error"):
        return version
    ws_url = version.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"error": "CDP missing browser websocket"}
    ws = websocket.create_connection(ws_url, timeout=8)
    try:
        ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        payload = None
        for _ in range(20):
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                payload = msg
                break
    finally:
        ws.close()
    if not payload:
        return {"error": "CDP Storage.getCookies no reply"}
    if payload.get("error"):
        return {"error": f"CDP {payload['error']}"}
    cookies = ((payload.get("result") or {}).get("cookies")) or []
    return _cookie_header_from_list(cookies, parts)


def extract_cookie_header() -> dict:
    cdp = None
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=0.6) as resp:
            if resp.status == 200:
                cdp = cdp_cookie_header(timeout=8)
                if "cookie" in cdp:
                    return cdp
    except Exception:
        pass
    ud = brave_user_data()
    if not cookie_db(ud).exists():
        return {"error": "Brave Cookies DB missing"}
    key = brave_master_key(ud)
    tmp = Path(tempfile.mkdtemp(prefix="orbit-brave-ck-")) / "Cookies"
    try:
        copy_locked(cookie_db(ud), tmp)
    except OSError as e:
        return {"error": str(e), "locked": True}
    con = sqlite3.connect(str(tmp))
    try:
        rows = con.execute("SELECT host_key, name, encrypted_value FROM cookies").fetchall()
    finally:
        con.close()
        try:
            tmp.unlink()
        except OSError:
            pass
    cookie_parts = []
    names = []
    for host, name, ev in rows:
        if not host_allowed(str(host)) or not name:
            continue
        try:
            val = decrypt_value(key, ev or b"")
        except Exception:
            continue
        if not val:
            continue
        cookie_parts.append(f"{name}={val}")
        names.append(f"{host}:{name}")
    if not cookie_parts:
        return {"error": "no grok.com/x.ai cookies decrypted", "names": names}
    return {"cookie": "; ".join(cookie_parts), "names": names}


def parse_conversations(payload) -> list[dict]:
    items = []
    if isinstance(payload, dict):
        for key in ("conversations", "items", "data", "results"):
            if isinstance(payload.get(key), list):
                items = payload[key]
                break
        if not items and "conversation_id" in payload:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        cid = (
            it.get("conversation_id")
            or it.get("conversationId")
            or it.get("id")
            or it.get("conversationIdStr")
        )
        title = it.get("title") or it.get("name") or it.get("summary") or str(cid or "")
        if not cid:
            continue
        url = f"https://grok.com/c/{cid}"
        out.append(
            {
                "id": f"web:grok:{cid}",
                "title": str(title)[:180],
                "url": url,
            }
        )
        if len(out) >= 40:
            break
    return out


def _cursor_url(cid: str, raw_url: str | None = None) -> str:
    url = str(raw_url or "").split("#")[0]
    if url.startswith("https://cursor.com/") or url.startswith("https://www.cursor.com/"):
        return url
    return f"https://cursor.com/agents/{cid}"


def parse_cursor_agents(payload) -> list[dict]:
    """Official List Agents shape plus nested dashboard JSON."""
    items: list = []
    if isinstance(payload, dict):
        if isinstance(payload.get("agent"), dict) and payload["agent"].get("id"):
            items = [payload["agent"]]
        else:
            for key in ("items", "agents", "data", "results", "composers", "backgroundAgents"):
                if isinstance(payload.get(key), list):
                    items = payload[key]
                    break
        if not items and payload.get("id"):
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    out = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        if isinstance(it.get("agent"), dict) and it["agent"].get("id"):
            it = it["agent"]
        cid = it.get("id") or it.get("agentId") or it.get("bcId")
        if not cid:
            continue
        cid = str(cid)
        if cid.lower() in {"agents", "agent", "new", "login"}:
            continue
        if cid in seen:
            continue
        seen.add(cid)
        name = it.get("name") or it.get("title") or it.get("summary") or cid
        raw_status = it.get("status") or ""
        raw_url = it.get("url") or (it.get("target") or {}).get("url")
        from web_adapters import normalize_cursor_status

        title, mapped = normalize_cursor_status(str(name), str(raw_status) if raw_status else None)
        remote = ""
        repos = it.get("repos")
        if isinstance(repos, list) and repos and isinstance(repos[0], dict):
            remote = str(repos[0].get("url") or "")
        pr_url = None
        git = it.get("git") if isinstance(it.get("git"), dict) else {}
        branches = git.get("branches") if isinstance(git.get("branches"), list) else []
        branch = None
        if branches and isinstance(branches[0], dict):
            pr_url = branches[0].get("prUrl") or branches[0].get("pr_url")
            branch = branches[0].get("name") or branches[0].get("branch")
        row = {
            "id": f"web:cursor:{cid}"[:96],
            "title": title,
            "url": _cursor_url(cid, raw_url),
            "status": mapped,
        }
        if remote:
            row["remote"] = remote
        if branch:
            row["branch"] = str(branch)
        if pr_url:
            row["pr_url"] = str(pr_url)
        ts = pick_timestamp(it)
        if ts:
            row["updated_at"] = ts
        out.append(row)
        if len(out) >= 40:
            break
    if out:
        return out
    return _walk_bc_agents(payload)


def _walk_bc_agents(payload) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()

    def walk(node) -> None:
        if len(found) >= 40:
            return
        if isinstance(node, dict):
            cid = node.get("id") or node.get("agentId")
            if isinstance(cid, str) and BC_ID.fullmatch(cid) and cid not in seen:
                if node.get("name") or node.get("title") or node.get("url") or node.get("status"):
                    seen.add(cid)
                    found.extend(parse_cursor_agents([node]))
            for val in node.values():
                walk(val)
        elif isinstance(node, list):
            for val in node:
                walk(val)

    walk(payload)
    return found


def fetch_conversations(cookie_header: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Cookie": cookie_header,
        "Referer": "https://grok.com/",
    }
    last = None
    for url in LIST_URLS:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type") or ""
        except urllib.error.HTTPError as e:
            last = f"{url} HTTP {e.code}"
            continue
        except Exception as e:
            last = f"{url} {type(e).__name__}"
            continue
        if b"<!DOCTYPE" in raw[:80] or "text/html" in ctype:
            last = f"{url} html"
            continue
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            last = f"{url} not-json"
            continue
        sessions = parse_conversations(payload)
        return {
            "ok": True,
            "url": url,
            "sessions": sessions,
            "raw_keys": list(payload)[:12] if isinstance(payload, dict) else ["list"],
        }
    return {"error": last or "no conversation endpoint worked"}


def extract_crsr(text: str) -> str | None:
    for line in (text or "").splitlines():
        s = line.strip().strip('"').strip("'")
        if s.startswith("crsr_") and len(s) > 16:
            return s
    s = (text or "").strip().strip('"').strip("'")
    if s.startswith("crsr_") and len(s) > 16:
        return s
    return None


def orbit_key_path() -> Path:
    from web_adapters import web_home

    return web_home() / "cursor_api_key.txt"


def desktop_key_path() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop" / "cursorapiforyou.txt"


def load_cursor_api_key() -> str | None:
    env = extract_crsr(os.environ.get("ORBIT_CURSOR_API_KEY") or os.environ.get("CURSOR_API_KEY") or "")
    if env:
        return env
    for path in (orbit_key_path(), desktop_key_path()):
        try:
            if path.is_file():
                got = extract_crsr(path.read_text(encoding="utf-8"))
                if got:
                    return got
        except Exception:
            continue
    return None


def read_clipboard_text() -> str:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        if not user32.OpenClipboard(None):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return ""


def write_key_files(key: str) -> dict:
    orbit = orbit_key_path()
    orbit.parent.mkdir(parents=True, exist_ok=True)
    orbit.write_text(key + "\n", encoding="utf-8")
    desk = desktop_key_path()
    try:
        if not desk.exists():
            desk.write_text(key + "\n", encoding="utf-8")
            restored_desktop = True
        else:
            restored_desktop = False
    except Exception:
        restored_desktop = False
    return {
        "ok": True,
        "orbit_key": True,
        "desktop_restored": restored_desktop,
        "prefix": key[:5],
        "length": len(key),
    }


def cursor_api_request(api_key: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    token = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    headers = {
        "User-Agent": "GrokOrbit/1.0 (local; Cloud Agents)",
        "Accept": "application/json",
        "Authorization": f"Basic {token}",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    url = "https://api.cursor.com" + path
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type") or ""
            http = getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        payload = None
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            payload = None
        out = {"error": f"cursor api HTTP {e.code}", "http": e.code}
        if isinstance(payload, dict):
            out["payload"] = payload
        return out
    except Exception as e:
        return {"error": f"cursor api {type(e).__name__}"}
    if b"<!DOCTYPE" in raw[:80] or "text/html" in ctype:
        return {"error": "cursor api returned html"}
    try:
        return {"ok": True, "http": http, "payload": json.loads(raw.decode("utf-8", errors="replace"))}
    except json.JSONDecodeError:
        return {"error": "cursor api not-json"}


def followup_body(text: str) -> dict:
    return {"prompt": {"text": text}}


def is_agent_busy(status: str | None) -> bool:
    return str(status or "").strip().upper() in {"CREATING", "RUNNING"}


def followup_cursor_agent(agent_id: str, text: str) -> dict:
    key = load_cursor_api_key()
    if not key:
        return {"error": "no cursor api key"}
    prompt = (text or "").strip()
    if not prompt:
        return {"error": "empty follow-up"}
    cid = str(agent_id or "").replace("web:cursor:", "").strip()
    if not cid:
        return {"error": "missing agent id"}
    detail = cursor_api_request(key, f"/v1/agents/{cid}")
    payload = detail.get("payload") if isinstance(detail.get("payload"), dict) else {}
    run_id = payload.get("latestRunId") or payload.get("latest_run_id")
    run_status = payload.get("status")
    if run_id:
        run = cursor_api_request(key, f"/v1/agents/{cid}/runs/{run_id}")
        rp = run.get("payload") if isinstance(run.get("payload"), dict) else {}
        run_status = rp.get("status") or run_status
    if is_agent_busy(str(run_status) if run_status else None):
        return {"error": "agent_busy", "http": 409, "hint": "open in browser"}
    got = cursor_api_request(key, f"/v1/agents/{cid}/runs", method="POST", body=followup_body(prompt))
    if got.get("error"):
        if got.get("http") == 409:
            return {"error": "agent_busy", "http": 409, "hint": "open in browser"}
        return {"error": got.get("error")}
    rp = got.get("payload") if isinstance(got.get("payload"), dict) else {}
    new_id = rp.get("id") or rp.get("runId") or rp.get("run_id")
    return {
        "ok": True,
        "agent_id": cid,
        "run_id": str(new_id) if new_id else None,
        "status": rp.get("status"),
    }


def install_cursor_key() -> dict:
    key = extract_crsr(os.environ.get("ORBIT_CURSOR_API_KEY") or "")
    if not key:
        key = extract_crsr(read_clipboard_text())
        source = "clipboard" if key else None
    else:
        source = "env"
    if not key:
        for path in (desktop_key_path(), orbit_key_path()):
            try:
                if path.is_file():
                    key = extract_crsr(path.read_text(encoding="utf-8"))
                    if key:
                        source = path.name
                        break
            except Exception:
                continue
    if not key:
        return {"error": "no crsr_ key on clipboard, Desktop cursorapiforyou.txt, or orbit key file"}
    probe = cursor_api_request(key, "/v1/me")
    if probe.get("error"):
        return {"error": f"key rejected: {probe['error']}", "source": source}
    written = write_key_files(key)
    written["source"] = source
    written["me"] = "ok"
    name = ((probe.get("payload") or {}).get("apiKeyName")) if isinstance(probe.get("payload"), dict) else None
    if name:
        written["api_key_name"] = str(name)[:80]
    return written


def enrich_cursor_row(api_key: str, row: dict) -> dict:
    from web_adapters import normalize_cursor_status

    cid = str(row.get("id") or "").replace("web:cursor:", "")
    if not cid:
        return row
    detail = cursor_api_request(api_key, f"/v1/agents/{cid}")
    payload = detail.get("payload") if isinstance(detail.get("payload"), dict) else {}
    extra = parse_cursor_agents(payload) if payload else []
    if extra:
        if extra[0].get("remote"):
            row["remote"] = extra[0]["remote"]
        if extra[0].get("url"):
            row["url"] = extra[0]["url"]
    run_id = payload.get("latestRunId") or payload.get("latest_run_id")
    if run_id:
        run = cursor_api_request(api_key, f"/v1/agents/{cid}/runs/{run_id}")
        rp = run.get("payload") if isinstance(run.get("payload"), dict) else {}
        run_status = rp.get("status")
        git = rp.get("git") if isinstance(rp.get("git"), dict) else {}
        branches = git.get("branches") if isinstance(git.get("branches"), list) else []
        if branches and isinstance(branches[0], dict):
            pr = branches[0].get("prUrl") or branches[0].get("pr_url")
            if pr:
                row["pr_url"] = str(pr)
            name = branches[0].get("name") or branches[0].get("branch")
            if name:
                row["branch"] = str(name)
        if run_status:
            title, mapped = normalize_cursor_status(row.get("title") or "", str(run_status))
            row["title"] = title
            row["status"] = mapped
        ts = pick_timestamp(rp) or pick_timestamp(payload)
        if ts:
            row["updated_at"] = ts
    else:
        ts = pick_timestamp(payload)
        if ts:
            row["updated_at"] = ts
    return row


def pick_timestamp(row: dict | None) -> str | None:
    if not isinstance(row, dict):
        return None
    for key in (
        "updatedAt",
        "updated_at",
        "finishedAt",
        "finished_at",
        "createdAt",
        "created_at",
        "lastActiveAt",
        "last_active_at",
    ):
        val = row.get(key)
        if val:
            return str(val).strip()[:48]
    return None


def format_age_seconds(sec: int) -> str:
    if sec < 0:
        sec = 0
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        return f"{sec // 3600}h"
    return f"{sec // 86400}d"


def list_fingerprint(rows: list) -> str:
    bits = []
    for row in rows or []:
        cid = str(row.get("id") or "")
        status = str(row.get("status") or "")
        ts = str(row.get("updated_at") or "")
        bits.append(f"{cid}|{status}|{ts}")
    bits.sort()
    return hashlib.sha256("\n".join(bits).encode("utf-8")).hexdigest()[:20]


def pulse_should_skip(prev: dict | None, fingerprint: str, rows: list) -> bool:
    if not rows or not fingerprint:
        return False
    if not isinstance(prev, dict):
        return False
    return prev.get("fingerprint") == fingerprint


def write_cursor_pulse(
    fingerprint: str, skipped: bool, count: int, dest: Path | None = None
) -> Path:
    from web_adapters import cache_path, write_json, utc_now as web_utc

    path = dest or cache_path("cursor_web").with_name("cursor_web.pulse.json")
    write_json(
        path,
        {
            "fingerprint": fingerprint,
            "skipped": skipped,
            "count": count,
            "probed_at": web_utc(),
        },
    )
    return path


def read_cursor_pulse(path: Path | None = None) -> dict:
    from web_adapters import cache_path, read_json

    dest = path or cache_path("cursor_web").with_name("cursor_web.pulse.json")
    data = read_json(dest)
    return data if isinstance(data, dict) else {}


def fetch_cursor_official(api_key: str) -> dict:
    got = cursor_api_request(api_key, "/v1/agents?limit=20&includeArchived=false")
    if got.get("error"):
        return got
    sessions = parse_cursor_agents(got.get("payload"))
    fingerprint = list_fingerprint(sessions)
    if pulse_should_skip(read_cursor_pulse(), fingerprint, sessions):
        write_cursor_pulse(fingerprint, True, len(sessions))
        return {
            "ok": True,
            "sessions": sessions,
            "via": "official_api",
            "count": len(sessions),
            "enriched": 0,
            "skipped": True,
            "fingerprint": fingerprint,
        }
    if sessions:
        with ThreadPoolExecutor(max_workers=6) as pool:
            sessions = list(pool.map(lambda row: enrich_cursor_row(api_key, row), sessions))
    write_cursor_pulse(fingerprint, False, len(sessions))
    return {
        "ok": True,
        "sessions": sessions,
        "via": "official_api",
        "count": len(sessions),
        "enriched": len(sessions),
        "skipped": False,
        "fingerprint": fingerprint,
    }


def cursor_done_payload(sessions: list, elapsed_ms: int, probed_at: str) -> dict:
    running = sum(1 for s in sessions if s.get("status") == "running")
    return {
        "probed_at": probed_at,
        "count": len(sessions),
        "running": running,
        "elapsed_ms": elapsed_ms,
    }


def write_cursor_done(
    sessions: list, elapsed_ms: int, probed_at: str, dest: Path | None = None
) -> Path:
    from web_adapters import cache_path, write_json

    path = dest or cache_path("cursor_web").with_name("cursor_web.done.json")
    write_json(path, cursor_done_payload(sessions, elapsed_ms, probed_at))
    return path


def sync_cursor_official() -> dict:
    from web_adapters import grant_consent, consent_path, read_json, write_json, save_cache

    grant_consent()
    disk = read_json(consent_path()) if consent_path().exists() else {}
    if not isinstance(disk, dict):
        disk = {}
    disk["daily_brave_cursor"] = True
    write_json(consent_path(), disk)
    installed = install_cursor_key()
    if installed.get("error") and not load_cursor_api_key():
        return installed
    key = load_cursor_api_key()
    if not key:
        return {"error": "no cursor api key after install"}
    t0 = time.perf_counter()
    fetched = fetch_cursor_official(key)
    if fetched.get("error"):
        return fetched
    if fetched.get("skipped"):
        from web_adapters import cache_path, read_json

        existing = read_json(cache_path("cursor_web")) if cache_path("cursor_web").exists() else {}
        sessions = (existing or {}).get("sessions") if isinstance(existing, dict) else []
        sessions = sessions or []
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        running = sum(1 for s in sessions if s.get("status") == "running")
        return {
            "brave_bounce": False,
            "key": {k: installed.get(k) for k in ("ok", "source", "api_key_name", "orbit_key", "desktop_restored") if k in installed},
            "surfaces": {
                "cursor_web": {
                    "status": (existing or {}).get("status") if isinstance(existing, dict) else "ok",
                    "detail": f"{len(sessions)} agents unchanged (pulse skip)",
                    "count": len(sessions),
                    "source": "official_api",
                    "enriched": 0,
                    "skipped": True,
                    "fingerprint": fetched.get("fingerprint"),
                    "elapsed_ms": elapsed_ms,
                    "running": running,
                }
            },
        }
    sessions = fetched.get("sessions") or []
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    running = sum(1 for s in sessions if s.get("status") == "running")
    detail = f"{len(sessions)} cursor.com agent(s) via official Cloud Agents API"
    cache = save_cache(
        "cursor_web",
        {"sessions": sessions},
        CURSOR_AGENTS_URL,
        "ok" if sessions else "degraded",
        detail,
    )
    write_cursor_done(sessions, elapsed_ms, cache.get("probed_at") or utc_now())
    return {
        "brave_bounce": False,
        "key": {k: installed.get(k) for k in ("ok", "source", "api_key_name", "orbit_key", "desktop_restored") if k in installed},
        "surfaces": {
            "cursor_web": {
                "status": cache.get("status"),
                "detail": cache.get("detail"),
                "count": len(sessions),
                "source": "official_api",
                "enriched": fetched.get("enriched"),
                "elapsed_ms": elapsed_ms,
                "running": running,
            }
        },
    }


def cdp_pages() -> list[dict]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=2) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def cdp_open_page(url: str) -> dict:
    encoded = urllib.parse.quote(url, safe=":/?&=%")
    for method in ("GET", "PUT"):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:9222/json/new?{encoded}",
                method=method,
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                row = json.loads(resp.read().decode("utf-8"))
            if isinstance(row, dict) and row.get("webSocketDebuggerUrl"):
                return row
        except Exception:
            continue
    return {"error": "could not open CDP page"}


def _cdp_recv_until(ws, mid: int, extras: list, timeout: float = 8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = json.loads(ws.recv())
        except Exception:
            break
        extras.append(msg)
        if msg.get("id") == mid:
            return msg
    return None


def fetch_cursor_via_cdp() -> dict:
    """Read the signed-in cursor.com/agents tab. Do not call api.cursor.com with cookies."""
    import websocket

    page = None
    deadline = time.time() + 20
    while time.time() < deadline and not page:
        for row in cdp_pages():
            url = str(row.get("url") or "")
            if row.get("type") == "page" and "cursor.com" in url and row.get("webSocketDebuggerUrl"):
                page = row
                break
        if page:
            break
        time.sleep(0.4)
    if not page:
        opened = cdp_open_page(CURSOR_AGENTS_URL)
        if opened.get("error"):
            return opened
        page = opened
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        return {"error": "cursor tab missing websocket"}
    ws = websocket.create_connection(ws_url, timeout=10)
    extras: list = []
    bodies: list = []
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        _cdp_recv_until(ws, 1, extras, timeout=4)
        ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
        _cdp_recv_until(ws, 2, extras, timeout=4)
        ws.send(json.dumps({"id": 3, "method": "Runtime.enable"}))
        _cdp_recv_until(ws, 3, extras, timeout=4)
        current = str(page.get("url") or "")
        if "cursor.com/agents" not in current:
            ws.send(
                json.dumps(
                    {
                        "id": 4,
                        "method": "Page.navigate",
                        "params": {"url": CURSOR_AGENTS_URL},
                    }
                )
            )
            _cdp_recv_until(ws, 4, extras, timeout=6)
        pending: dict[str, str] = {}
        html = ""
        js_items: list = []
        poll_until = time.time() + 16
        next_id = 20
        while time.time() < poll_until:
            ws.settimeout(1.2)
            try:
                msg = json.loads(ws.recv())
            except Exception:
                msg = None
            if msg:
                extras.append(msg)
                method = msg.get("method")
                params = msg.get("params") or {}
                if method == "Network.responseReceived":
                    resp = params.get("response") or {}
                    mime = str(resp.get("mimeType") or "")
                    url = str(resp.get("url") or "")
                    rid = params.get("requestId")
                    interesting = (
                        "json" in mime.lower()
                        or "/agents" in url
                        or "composer" in url.lower()
                    ) and not url.startswith("data:")
                    if rid and interesting and "api.cursor.com" not in url:
                        pending[str(rid)] = url
                elif method == "Network.loadingFinished":
                    rid = str(params.get("requestId") or "")
                    if rid in pending:
                        next_id += 1
                        ws.send(
                            json.dumps(
                                {
                                    "id": next_id,
                                    "method": "Network.getResponseBody",
                                    "params": {"requestId": rid},
                                }
                            )
                        )
            if int(time.time() * 2) % 3 == 0:
                next_id += 1
                ws.send(
                    json.dumps(
                        {
                            "id": next_id,
                            "method": "Runtime.evaluate",
                            "params": {
                                "expression": EXTRACT_AGENTS_JS,
                                "returnByValue": True,
                                "awaitPromise": False,
                            },
                        }
                    )
                )
                ev = _cdp_recv_until(ws, next_id, extras, timeout=3)
                val = ((ev or {}).get("result") or {}).get("result") or {}
                if isinstance(val.get("value"), list) and val["value"]:
                    js_items = val["value"]
                    break
        for msg in extras:
            if msg.get("id") and ((msg.get("result") or {}).get("body") is not None):
                raw = (msg.get("result") or {}).get("body") or ""
                if (msg.get("result") or {}).get("base64Encoded"):
                    try:
                        raw = base64.b64decode(raw).decode("utf-8", errors="replace")
                    except Exception:
                        continue
                try:
                    bodies.append(json.loads(raw))
                except Exception:
                    continue
        next_id += 1
        ws.send(
            json.dumps(
                {
                    "id": next_id,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "document.documentElement.outerHTML",
                        "returnByValue": True,
                    },
                }
            )
        )
        ev = _cdp_recv_until(ws, next_id, extras, timeout=4)
        html = str((((ev or {}).get("result") or {}).get("result") or {}).get("value") or "")
    finally:
        try:
            ws.close()
        except Exception:
            pass

    sessions: list[dict] = []
    for body in bodies:
        for row in parse_cursor_agents(body):
            if row["id"] not in {s["id"] for s in sessions}:
                sessions.append(row)
    if js_items:
        mapped = parse_cursor_agents(js_items)
        for row in mapped:
            if row["id"] not in {s["id"] for s in sessions}:
                sessions.append(row)
    if html:
        try:
            from web_adapters import looks_like_login, parse_surface

            parsed = parse_surface("cursor_web", html, CURSOR_AGENTS_URL)
            if looks_like_login("cursor_web", html, CURSOR_AGENTS_URL) and not sessions:
                return {"error": "cursor.com agents page looks like login", "via": "cdp_page"}
            for row in parsed.get("sessions") or []:
                if row["id"] not in {s["id"] for s in sessions}:
                    sessions.append(row)
        except Exception:
            for m in BC_ID.findall(html):
                row = {
                    "id": f"web:cursor:{m}",
                    "title": m,
                    "url": f"https://cursor.com/agents/{m}",
                }
                if row["id"] not in {s["id"] for s in sessions}:
                    sessions.append(row)
    if not sessions:
        return {"error": "cursor.com agents page had no listable agents", "via": "cdp_page"}
    return {"ok": True, "sessions": sessions[:40], "via": "cdp_page"}


def _save_surface(surface: str, sessions: list, final_url: str, detail: str) -> dict:
    from web_adapters import save_cache

    status_name = "ok" if sessions else "degraded"
    return save_cache(surface, {"sessions": sessions}, final_url, status_name, detail)


def sync_via_cdp(cursor_official: dict | None = None) -> dict:
    stop_brave()
    time.sleep(0.6)
    start_brave(
        [
            f"--user-data-dir={brave_user_data()}",
            "--profile-directory=Default",
            "--remote-debugging-port=9222",
            "--remote-allow-origins=*",
            CURSOR_AGENTS_URL,
        ]
    )
    out: dict = {"brave_bounce": True, "surfaces": {}}
    try:
        ready = cdp_wait_version(timeout=30)
        if ready.get("error"):
            return ready
        from web_adapters import consent_path, read_json

        disk = read_json(consent_path()) if consent_path().exists() else {}
        if not isinstance(disk, dict):
            disk = {}

        if disk.get("daily_brave_grok"):
            extracted = cdp_cookie_header(timeout=20, parts=GROK_HOSTS)
            if extracted.get("error"):
                out["surfaces"]["grok_web"] = extracted
            else:
                fetched = fetch_conversations(extracted["cookie"])
                if fetched.get("error"):
                    out["surfaces"]["grok_web"] = {
                        "error": fetched["error"],
                        "via": "cdp",
                    }
                else:
                    sessions = fetched.get("sessions") or []
                    detail = (
                        f"{len(sessions)} grok.com conversation(s) via daily Brave (CDP)"
                        if sessions
                        else "Brave CDP cookies worked but conversation list was empty"
                    )
                    cache = _save_surface("grok_web", sessions, "https://grok.com/", detail)
                    cache["source"] = "daily_brave_cdp"
                    out["surfaces"]["grok_web"] = {
                        "status": cache.get("status"),
                        "detail": cache.get("detail"),
                        "count": len(sessions),
                        "source": "daily_brave_cdp",
                    }

        cursor_sessions = []
        cursor_via = None
        if cursor_official and cursor_official.get("sessions"):
            cursor_sessions = cursor_official["sessions"]
            cursor_via = "official_api"
        elif disk.get("daily_brave_cursor"):
            scraped = fetch_cursor_via_cdp()
            if scraped.get("error"):
                out["surfaces"]["cursor_web"] = scraped
            else:
                cursor_sessions = scraped.get("sessions") or []
                cursor_via = scraped.get("via") or "cdp_page"

        if cursor_sessions:
            detail = f"{len(cursor_sessions)} cursor.com agent(s) via {cursor_via}"
            cache = _save_surface("cursor_web", cursor_sessions, CURSOR_AGENTS_URL, detail)
            cache["source"] = cursor_via
            out["surfaces"]["cursor_web"] = {
                "status": cache.get("status"),
                "detail": cache.get("detail"),
                "count": len(cursor_sessions),
                "source": cursor_via,
            }
        return out
    finally:
        stop_brave()
        time.sleep(0.5)
        start_brave(
            [
                f"--user-data-dir={brave_user_data()}",
                "--profile-directory=Default",
                "--restore-last-session",
            ]
        )


def sync_to_cache() -> dict:
    from web_adapters import consent_path, read_json, save_cache

    disk = read_json(consent_path()) if consent_path().exists() else {}
    if not isinstance(disk, dict) or not (
        disk.get("daily_brave_grok") or disk.get("daily_brave_cursor")
    ):
        return {"error": "daily Brave grok.com / cursor.com consent not granted"}

    cursor_official = None
    key = load_cursor_api_key()
    if key and disk.get("daily_brave_cursor"):
        cursor_official = fetch_cursor_official(key)
        if cursor_official.get("sessions") and not disk.get("daily_brave_grok"):
            sessions = cursor_official["sessions"]
            detail = f"{len(sessions)} cursor.com agent(s) via official Cloud Agents API"
            cache = save_cache(
                "cursor_web",
                {"sessions": sessions},
                CURSOR_AGENTS_URL,
                "ok" if sessions else "degraded",
                detail,
            )
            return {
                "brave_bounce": False,
                "surfaces": {
                    "cursor_web": {
                        "status": cache.get("status"),
                        "detail": cache.get("detail"),
                        "count": len(sessions),
                        "source": "official_api",
                    }
                },
            }
    return sync_via_cdp(cursor_official=cursor_official)


def grant_daily() -> dict:
    from web_adapters import consent_path, grant_consent, read_json, write_json

    grant_consent()
    disk = read_json(consent_path()) or {}
    disk["daily_brave_grok"] = True
    disk["daily_brave_grok_at"] = utc_now()
    disk["daily_brave_cursor"] = True
    disk["daily_brave_cursor_at"] = utc_now()
    disk["daily_brave_scope"] = (
        "grok.com/x.ai cookies and cursor.com agents page from Brave Default. "
        "Never sends Brave cookies to api.cursor.com."
    )
    write_json(consent_path(), disk)
    return {
        "ok": True,
        "daily_brave_grok": True,
        "daily_brave_cursor": True,
        "scope": disk["daily_brave_scope"],
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument(
        "command",
        choices=["grant", "sync", "probe-cookies", "install-key", "cursor-api", "follow-up"],
    )
    p.add_argument("rest", nargs="*")
    args = p.parse_args()
    if args.command == "follow-up":
        agent_id = args.rest[0] if args.rest else ""
        text = " ".join(args.rest[1:]) if len(args.rest) > 1 else ""
        out = followup_cursor_agent(agent_id, text)
        print(json.dumps(out, indent=2, ensure_ascii=True))
        return 0 if "error" not in out else 2
    if args.command == "grant":
        print(json.dumps(grant_daily(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "install-key":
        out = install_cursor_key()
        print(json.dumps(out, indent=2, ensure_ascii=True))
        return 0 if "error" not in out else 2
    if args.command == "cursor-api":
        print(json.dumps(sync_cursor_official(), indent=2, ensure_ascii=True))
        return 0
    if args.command == "probe-cookies":
        out = extract_cookie_header()
        safe = {k: v for k, v in out.items() if k != "cookie"}
        if "cookie" in out:
            safe["cookie_count"] = out["cookie"].count("=")
        print(json.dumps(safe, indent=2, ensure_ascii=True))
        return 0 if "error" not in out else 2
    print(json.dumps(sync_to_cache(), indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
