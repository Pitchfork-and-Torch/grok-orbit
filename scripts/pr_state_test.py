"""Unattended tests for PR state classify/cache. No live gh. No tokens."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pr_state import (
    apply_to_sessions,
    cache_is_fresh,
    classify,
    needs_clearance,
    normalize_pr_url,
    parse_files,
    row_from_payload,
    save_cache,
)


def main() -> int:
    assert classify("OPEN", False) == "open"
    assert classify("OPEN", True) == "draft"
    assert classify("MERGED") == "merged"
    assert classify("CLOSED") == "closed"
    assert classify("") == "unknown"
    assert classify("WAT") == "unknown"
    assert needs_clearance("open")
    assert needs_clearance("unknown")
    assert needs_clearance(None)
    assert needs_clearance("")
    assert not needs_clearance("draft")
    assert not needs_clearance("merged")
    assert not needs_clearance("closed")

    assert (
        normalize_pr_url("https://www.github.com/Pitchfork-and-Torch/vela/pull/8/")
        == "https://github.com/pitchfork-and-torch/vela/pull/8"
    )

    files, count = parse_files(
        {
            "files": [
                {"path": "src/a.rs"},
                {"filename": "src/b.rs"},
                {"path": "src/c.rs"},
            ]
        }
    )
    assert count == 3
    assert files == ["src/a.rs", "src/b.rs", "src/c.rs"]

    row = row_from_payload(
        {
            "state": "OPEN",
            "isDraft": False,
            "title": "land lens",
            "files": [{"path": "App.tsx"}, {"path": "web.rs"}],
        }
    )
    assert row["state"] == "open"
    assert row["file_count"] == 2
    assert row["files"][0] == "App.tsx"

    sessions = [
        {"id": "web:cursor:a", "pr_url": "https://github.com/Pitchfork-and-Torch/vela/pull/8"},
        {"id": "web:cursor:b", "pr_url": "https://github.com/other/repo/pull/1"},
    ]
    cache = {
        "updated_at": 1,
        "prs": {
            "https://github.com/pitchfork-and-torch/vela/pull/8": {
                "state": "merged",
                "files": ["x.rs"],
                "file_count": 1,
            }
        },
    }
    apply_to_sessions(sessions, cache)
    assert sessions[0]["pr_state"] == "merged"
    assert sessions[0]["pr_file_count"] == 1
    assert "pr_state" not in sessions[1]

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "pr_state.json"
        save_cache({"prs": {"https://github.com/a/b/pull/1": {"state": "open"}}}, dest)
        disk = json.loads(dest.read_text(encoding="utf-8"))
        assert disk["prs"]["https://github.com/a/b/pull/1"]["state"] == "open"
        assert cache_is_fresh(disk, ["https://github.com/a/b/pull/1"], now=disk["updated_at"] + 10)
        assert not cache_is_fresh(disk, ["https://github.com/a/b/pull/1"], now=disk["updated_at"] + 400)
        assert not cache_is_fresh(disk, ["https://github.com/a/b/pull/2"], now=disk["updated_at"] + 10)

    print("OK pr_state classify cache apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
