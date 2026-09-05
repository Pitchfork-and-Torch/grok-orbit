"""Phase 7 Gravity linker. Deterministic. No LLM. No network.

Optional extra wells (not in this tree): GROK_ORBIT_WELLS or
<home>/.grok-orbit/wells.json as {\"wells\":[{id,name,rel_paths,keywords,remotes}]}.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

LOOSE = "loose"
GROK_WEB = "grok.com"
CURSOR_WEB = "cursor.com"

# More specific wells first. orbitstack is not grok-orbit.
CATALOG = (
    {
        "id": "vela",
        "name": "VELA",
        "rel_paths": ("vela",),
        "keywords": ("vela", "interval n", "compose cuts"),
        "remotes": ("github.com/pitchfork-and-torch/vela",),
    },
    {
        "id": "leoaware",
        "name": "LeoAware",
        "rel_paths": ("Projects/leo-aware-transport", "leo-aware-transport", "LeoAware"),
        "keywords": ("leoaware", "leo-aware", "leocc", "leocc_v1", "dual-gate"),
        "remotes": (),
    },
    {
        "id": "instar",
        "name": "INSTAR",
        "rel_paths": ("instar", "INSTAR"),
        "keywords": ("instar", "page 56", "liber primus"),
        "remotes": ("github.com/pitchfork-and-torch/instar",),
    },
    {
        "id": "ghost",
        "name": "Ghost",
        "rel_paths": ("ghost-continuum", ".ghost-continuum", ".ghost-lan"),
        "keywords": ("ghost continuum", "ghost-lan"),
        "remotes": ("github.com/pitchfork-and-torch/ghost-continuum",),
    },
    {
        "id": "grok-orbit",
        "name": "Grok Orbit",
        "rel_paths": ("grok-orbit",),
        "keywords": ("grok orbit", "grok-orbit"),
        "remotes": (),
    },
    {
        "id": "orbitstack",
        "name": "orbitstack",
        "rel_paths": ("orbitstack",),
        "keywords": ("orbitstack",),
        "remotes": (),
    },
)


def user_home() -> Path:
    return Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")


def extra_wells_path(home: Path | None = None) -> Path:
    override = (os.environ.get("GROK_ORBIT_WELLS") or "").strip()
    if override:
        return Path(override)
    return (home or user_home()) / ".grok-orbit" / "wells.json"


def load_extra_specs(home: Path | None = None) -> list[dict]:
    """Optional operator wells. Not shipped. JSON: {\"wells\":[{id,name,rel_paths,keywords,remotes}]}."""
    path = extra_wells_path(home)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    rows = data.get("wells") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        wid = str(row.get("id") or "").strip()
        if not wid:
            continue
        rel = row.get("rel_paths") or ()
        kws = row.get("keywords") or ()
        rems = row.get("remotes") or ()
        out.append(
            {
                "id": wid,
                "name": str(row.get("name") or wid),
                "rel_paths": tuple(str(x) for x in rel),
                "keywords": tuple(str(x) for x in kws),
                "remotes": tuple(str(x) for x in rems if x),
            }
        )
    return out


def normalize_remote(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    raw = raw.replace("\\", "/")
    raw = re.sub(r"^git@([^:]+):", r"https://\1/", raw)
    raw = re.sub(r"^ssh://git@", "https://", raw)
    raw = re.sub(r"^https?://", "", raw, flags=re.I)
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    raw = raw.rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    return raw.lower()


_GIT_MEMO: dict[str, tuple[float, str]] = {}


def _git_sig(path: Path) -> float:
    git_dir = path / ".git"
    best = 0.0
    for name in ("HEAD", "config"):
        p = git_dir / name
        try:
            if p.exists():
                best = max(best, p.stat().st_mtime)
        except OSError:
            continue
    return best


def git_remote(path: Path) -> str:
    git_dir = path / ".git"
    if not git_dir.exists():
        return ""
    key = str(path)
    sig = _git_sig(path)
    hit = _GIT_MEMO.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        out = subprocess.check_output(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            text=True,
            timeout=1.5,
            stderr=subprocess.DEVNULL,
        )
        remote = normalize_remote(out)
    except Exception:
        remote = ""
    _GIT_MEMO[key] = (sig, remote)
    return remote


def _norm_path(path: str) -> str:
    try:
        return str(Path(path).resolve()).replace("\\", "/").lower()
    except Exception:
        return path.replace("\\", "/").lower()


def looks_like_path(cwd: str) -> bool:
    if not cwd:
        return False
    p = Path(cwd)
    if p.is_absolute():
        return True
    if len(cwd) >= 3 and cwd[1] == ":" and cwd[0].isalpha():
        return True
    return False


def path_under(cwd: str, root: str) -> bool:
    if not looks_like_path(cwd) or not root:
        return False
    c = _norm_path(cwd)
    r = _norm_path(root)
    return c == r or c.startswith(r.rstrip("/") + "/")


def contains_kw(text: str, kw: str) -> bool:
    if not kw:
        return False
    hay = f" {(text or '').lower().replace('_', ' ').replace('-', ' ')} "
    needle = f" {kw.lower().replace('_', ' ').replace('-', ' ')} "
    return needle in hay


def build_catalog(home: Path | None = None, extra_remotes: dict[str, str] | None = None) -> list[dict]:
    home = home or user_home()
    extra_remotes = extra_remotes or {}
    out = []
    seen = set()
    for spec in (*CATALOG, *load_extra_specs(home)):
        wid = spec["id"]
        if wid in seen:
            continue
        seen.add(wid)
        paths = []
        remotes = {normalize_remote(r) for r in spec.get("remotes") or [] if r}
        for rel in spec.get("rel_paths") or ():
            p = (home / rel) if not Path(rel).is_absolute() else Path(rel)
            if p.is_dir():
                paths.append(str(p))
                remote = extra_remotes.get(str(p)) or git_remote(p)
                if remote:
                    remotes.add(remote)
        out.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "paths": paths,
                "keywords": tuple(spec.get("keywords") or ()),
                "remotes": sorted(r for r in remotes if r),
            }
        )
    return out


def assign_slug(
    session: dict,
    catalog: list[dict],
    remotes_by_cwd: dict[str, str] | None = None,
) -> str:
    cwd = str(session.get("cwd") or "")
    title = str(session.get("title") or "")
    url = str(session.get("url") or "")
    summary = str(session.get("summary") or "")
    remote = normalize_remote(str(session.get("remote") or ""))
    if cwd and remotes_by_cwd and cwd in remotes_by_cwd:
        remote = remote or normalize_remote(remotes_by_cwd[cwd])
    elif looks_like_path(cwd) and Path(cwd).is_dir():
        remote = remote or git_remote(Path(cwd))

    if remote:
        for spec in catalog:
            if remote in spec["remotes"]:
                return spec["id"]

    if cwd:
        for spec in catalog:
            for root in spec["paths"]:
                if path_under(cwd, root):
                    return spec["id"]

    blob = " ".join((title, url, summary, cwd))
    for spec in catalog:
        if any(contains_kw(blob, kw) for kw in spec["keywords"]):
            return spec["id"]

    src = str(session.get("source") or "")
    sid = str(session.get("id") or "")
    if src == "grok_web" or sid.startswith("web:grok:"):
        return GROK_WEB
    if src == "cursor_web" or sid.startswith("web:cursor:"):
        return CURSOR_WEB
    return LOOSE


def _is_error(session: dict) -> bool:
    return session.get("agent_name") == "error" or session.get("state") == "needs_input"


def resolve_clone(session: dict, catalog: list[dict] | None = None) -> str:
    """Local clone path for ACP/handoff. Empty if none."""
    cwd = str(session.get("cwd") or "")
    if looks_like_path(cwd) and Path(cwd).is_dir():
        return str(Path(cwd))
    catalog = catalog if catalog is not None else build_catalog()
    slug = str(session.get("project_id") or "")
    if not slug or slug in {LOOSE, GROK_WEB, CURSOR_WEB}:
        slug = assign_slug(session, catalog)
    for spec in catalog:
        if spec["id"] == slug:
            for path in spec.get("paths") or []:
                if Path(path).is_dir():
                    return path
    extra = session.get("project_path")
    if extra and Path(str(extra)).is_dir():
        return str(extra)
    return ""


def is_named_well(slug: str) -> bool:
    return bool(slug) and slug not in {LOOSE, GROK_WEB, CURSOR_WEB}


def member_kind(session: dict) -> str:
    if session.get("live"):
        return "live pager"
    src = str(session.get("source") or "")
    sid = str(session.get("id") or "")
    if src == "cursor_web" or sid.startswith("web:cursor:"):
        st = str(session.get("pr_state") or "")
        if st == "draft":
            return "Cursor draft"
        if st == "open":
            return "Cursor PR"
        return "Cursor"
    if src == "grok_web" or sid.startswith("web:grok:"):
        return "grok.com"
    return "Grok disk"


def thread_clause(sessions, projects, attention=None) -> str | None:
    notes = attention or []
    for project in projects or []:
        slug = str(project.get("id") or "")
        if not is_named_well(slug):
            continue
        kinds: list[str] = []
        for session in sessions or []:
            if str(session.get("project_id") or "") != slug:
                continue
            kind = member_kind(session)
            if kind not in kinds:
                kinds.append(kind)
        desk_hit = any(
            (a.get("kind") == "desk_claim")
            and f"claim {slug}" in str(a.get("title") or "").lower()
            for a in notes
        )
        if desk_hit and "desk" not in kinds:
            kinds.append("desk")
        if len(kinds) >= 2:
            name = project.get("name") or slug
            return f"{name} spans {' + '.join(kinds)}"
    return None


def link_sessions(
    sessions: list[dict],
    home: Path | None = None,
    remotes_by_cwd: dict[str, str] | None = None,
    catalog: list[dict] | None = None,
) -> list[dict]:
    catalog = catalog if catalog is not None else build_catalog(home)
    by_id = {s["id"]: s for s in catalog}
    for s in sessions:
        slug = assign_slug(s, catalog, remotes_by_cwd)
        s["project_id"] = slug
        spec = by_id.get(slug)
        if spec and spec.get("remotes") and not s.get("remote"):
            s["remote"] = spec["remotes"][0]
        if spec and spec.get("paths") and not s.get("project_path"):
            s["project_path"] = spec["paths"][0]

    leftovers = {
        GROK_WEB: {"id": GROK_WEB, "name": "grok.com", "paths": [], "remotes": [], "keywords": ()},
        CURSOR_WEB: {"id": CURSOR_WEB, "name": "cursor.com", "paths": [], "remotes": [], "keywords": ()},
        LOOSE: {"id": LOOSE, "name": "(loose)", "paths": [], "remotes": [], "keywords": ()},
    }
    groups: dict[str, dict] = {}
    for s in sessions:
        slug = s.get("project_id") or LOOSE
        spec = by_id.get(slug) or leftovers.get(slug) or leftovers[LOOSE]
        g = groups.setdefault(
            slug,
            {
                "id": spec["id"],
                "name": spec["name"],
                "paths": list(spec.get("paths") or []),
                "remotes": list(spec.get("remotes") or []),
                "tags": [],
                "session_ids": [],
                "live_count": 0,
                "running_count": 0,
                "health": "ok",
                "updated_at": s.get("updated_at"),
            },
        )
        g["session_ids"].append(s["id"])
        if s.get("live"):
            g["live_count"] += 1
        if s.get("agent_name") == "running":
            g["running_count"] += 1
        if _is_error(s):
            g["health"] = "error"
        elif g["health"] != "error" and (s.get("live") or s.get("agent_name") == "running"):
            g["health"] = "attention"
        if s.get("updated_at") and (not g.get("updated_at") or s["updated_at"] > g["updated_at"]):
            g["updated_at"] = s["updated_at"]

    def sort_key(p: dict):
        leftover = 1 if p["id"] in leftovers else 0
        return (-p["running_count"], -p["live_count"], leftover, p["name"].lower())

    return sorted(groups.values(), key=sort_key)
