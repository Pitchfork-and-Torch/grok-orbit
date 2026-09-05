"""Unattended linker tests. No git, no browser."""

from __future__ import annotations

import os
from pathlib import Path

from projects import (
    assign_slug,
    build_catalog,
    contains_kw,
    is_named_well,
    link_sessions,
    normalize_remote,
    thread_clause,
)


def catalog():
    return [
        {
            "id": "vela",
            "name": "VELA",
            "paths": [r"C:\Users\dev\vela"],
            "keywords": ("vela", "interval n"),
            "remotes": ("github.com/pitchfork-and-torch/vela",),
        },
        {
            "id": "leoaware",
            "name": "LeoAware",
            "paths": [r"C:\Users\dev\Projects\leo-aware-transport"],
            "keywords": ("leoaware", "leocc", "leocc_v1"),
            "remotes": (),
        },
        {
            "id": "instar",
            "name": "INSTAR",
            "paths": [r"C:\Users\dev\instar"],
            "keywords": ("instar",),
            "remotes": ("github.com/pitchfork-and-torch/instar",),
        },
        {
            "id": "ghost",
            "name": "Ghost",
            "paths": [r"C:\Users\dev\ghost-continuum"],
            "keywords": ("ghost continuum", "ghost-lan"),
            "remotes": ("github.com/pitchfork-and-torch/ghost-continuum",),
        },
        {
            "id": "grok-orbit",
            "name": "Grok Orbit",
            "paths": [r"C:\Users\dev\grok-orbit"],
            "keywords": ("grok orbit", "grok-orbit"),
            "remotes": (),
        },
    ]


def main() -> int:
    assert normalize_remote("https://github.com/Pitchfork-and-Torch/vela.git") == (
        "github.com/pitchfork-and-torch/vela"
    )
    assert normalize_remote("git@github.com:Pitchfork-and-Torch/instar.git") == (
        "github.com/pitchfork-and-torch/instar"
    )
    assert contains_kw("v3.14 D/600 reclaim on leocc_v1", "leocc_v1")
    assert not contains_kw("orbitstack CCA", "grok orbit")

    cat = catalog()
    assert (
        assign_slug({"id": "1", "cwd": r"C:\Users\dev\vela", "title": "pager"}, cat)
        == "vela"
    )
    assert (
        assign_slug(
            {
                "id": "2",
                "cwd": "cursor.com",
                "title": "VELA interval n",
                "source": "cursor_web",
            },
            cat,
        )
        == "vela"
    )
    assert (
        assign_slug(
            {
                "id": "3",
                "cwd": "cursor.com",
                "title": "v3.14 D/600 reclaim on leocc_v1",
                "source": "cursor_web",
            },
            cat,
        )
        == "leoaware"
    )
    assert (
        assign_slug(
            {"id": "4", "cwd": r"C:\Users\dev", "title": "Continue Previous"},
            cat,
        )
        == "loose"
    )
    assert (
        assign_slug(
            {"id": "web:grok:abc", "cwd": "grok.com", "source": "grok_web", "title": "chat"},
            cat,
        )
        == "grok.com"
    )
    assert (
        assign_slug(
            {
                "id": "web:cursor:x",
                "cwd": "cursor.com",
                "source": "cursor_web",
                "title": "Skill collection",
            },
            cat,
        )
        == "cursor.com"
    )
    assert (
        assign_slug(
            {
                "id": "5",
                "cwd": r"C:\Users\dev\work",
                "title": "x",
                "remote": "https://github.com/Pitchfork-and-Torch/vela.git",
            },
            cat,
        )
        == "vela"
    )
    assert (
        assign_slug(
            {
                "id": "6",
                "cwd": "cursor.com",
                "title": "Restore Ghost continuum overlay",
                "source": "cursor_web",
            },
            cat,
        )
        == "ghost"
    )

    sessions = [
        {
            "id": "web:cursor:run",
            "cwd": "cursor.com",
            "source": "cursor_web",
            "title": "v3.14 D/600 reclaim on leocc_v1",
            "agent_name": "running",
            "live": False,
        },
        {
            "id": "web:cursor:done",
            "cwd": "cursor.com",
            "source": "cursor_web",
            "title": "Rebase VELA #8 Hint law onto main",
            "agent_name": "finished",
            "live": False,
        },
        {
            "id": "live-1",
            "cwd": r"C:\Users\dev",
            "title": "Continue Previous",
            "live": True,
        },
    ]
    projects = link_sessions(sessions, catalog=cat, remotes_by_cwd={})
    ids = [p["id"] for p in projects]
    assert "leoaware" in ids, ids
    assert "vela" in ids, ids
    assert "loose" in ids, ids
    leo = next(p for p in projects if p["id"] == "leoaware")
    assert leo["running_count"] == 1, leo
    assert leo["health"] == "attention", leo
    assert sessions[0]["project_id"] == "leoaware"
    assert sessions[1]["project_id"] == "vela"
    built = build_catalog()
    assert any(s["id"] == "vela" for s in built)
    from projects import git_remote, resolve_clone
    vela = Path(os.environ.get("USERPROFILE") or ".") / "vela"
    if vela.is_dir() and (vela / ".git").exists():
        a = git_remote(vela)
        b = git_remote(vela)
        assert a == b

    clone = resolve_clone(
        {
            "id": "web:cursor:run",
            "cwd": "cursor.com",
            "source": "cursor_web",
            "title": "v3.14 D/600 reclaim on leocc_v1",
        },
        catalog=cat,
    )
    # fixture catalog path may not exist in CI-less unit test; live tree should
    live_clone = resolve_clone(
        {
            "id": "web:cursor:run",
            "cwd": "cursor.com",
            "source": "cursor_web",
            "title": "v3.14 D/600 reclaim on leocc_v1",
        }
    )
    if live_clone:
        assert "leo" in live_clone.lower() or "aware" in live_clone.lower(), live_clone
    clause = thread_clause(
        [
            {"id": "live-v", "project_id": "vela", "live": True, "source": "grok_build", "title": "pager"},
            {
                "id": "web:cursor:v",
                "project_id": "vela",
                "source": "cursor_web",
                "pr_state": "draft",
                "title": "land",
            },
        ],
        [{"id": "vela", "name": "VELA"}],
    )
    assert clause and "VELA spans" in clause and "live pager" in clause, clause
    assert is_named_well("vela")
    assert not is_named_well("loose")

    import json
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    (tmp / ".grok-orbit").mkdir()
    (tmp / ".grok-orbit" / "wells.json").write_text(
        json.dumps(
            {
                "wells": [
                    {
                        "id": "localwell",
                        "name": "Local Well",
                        "rel_paths": [],
                        "keywords": ["localwell-token"],
                        "remotes": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    extra_cat = build_catalog(home=tmp)
    assert any(s["id"] == "localwell" for s in extra_cat)
    assert (
        assign_slug(
            {
                "id": "x",
                "cwd": "cursor.com",
                "title": "please localwell-token now",
                "source": "cursor_web",
            },
            extra_cat,
        )
        == "localwell"
    )

    print("OK projects linker", ids, "clone", live_clone or clone or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
