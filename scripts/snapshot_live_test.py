"""live_sessions must tolerate corrupt pager rows (bad pid / non-objects)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from snapshot import live_sessions


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="orbit-live-"))
    (home / "active_sessions.json").write_text(
        json.dumps(
            [
                {
                    "session_id": "12345678-1234-1234-1234-123456789abc",
                    "cwd": "/tmp",
                    "pid": "not-a-number",
                },
                {
                    "session_id": "22345678-1234-1234-1234-123456789abc",
                    "cwd": "/tmp",
                    "pid": 42,
                },
                "skip-me",
            ]
        ),
        encoding="utf-8",
    )
    rows, adapter = live_sessions(home)
    assert adapter.get("status") == "ok", adapter
    assert len(rows) == 1, rows
    assert rows[0]["id"] == "22345678-1234-1234-1234-123456789abc", rows[0]
    print("OK live_sessions skips bad pid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
