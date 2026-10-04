"""tail_events: zero/negative limit or nbytes must return [] (not the whole file)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from snapshot import tail_events


def _write_jsonl(path: Path, n: int = 5) -> None:
    lines = []
    for i in range(n):
        lines.append(
            json.dumps(
                {
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"text": f"msg{i}"},
                        }
                    }
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="orbit-tail-"))
    path = home / "updates.jsonl"
    _write_jsonl(path, 5)

    assert tail_events(path, 24000, 2) == [
        {"kind": "agent_message_chunk", "text": "msg3"},
        {"kind": "agent_message_chunk", "text": "msg4"},
    ]
    # Python's seq[-0:] is the whole sequence  -  must fail closed.
    assert tail_events(path, 24000, 0) == []
    assert tail_events(path, 24000, -1) == []
    assert tail_events(path, 0, 3) == []
    assert tail_events(path, -100, 3) == []
    print("OK tail_events zero/negative limit and nbytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
