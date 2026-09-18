"""Resume must refuse a live TUI. No grok spawn. No tokens."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
# focus.py imports ctypes.windll at import time (Windows-only).
sys.modules.setdefault("focus", MagicMock())

import orbit_mcp as mcp  # noqa: E402


def main() -> int:
    live_id = "01a00022-b643-7b40-9d7e-dc185c67e3c2"
    mcp.live_ids = lambda: {live_id}  # type: ignore[method-assign]
    blocked = mcp.resume_session(live_id)
    err = str(blocked.get("error") or "")
    assert "refusing" in err, blocked
    assert "live TUI" in err, blocked
    web = mcp.resume_session("web:cursor:bc-1")
    assert web.get("error") == "invalid session id", web
    print("OK resume guard refuses live TUI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
