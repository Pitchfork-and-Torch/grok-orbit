"""Print session/new result so we can see modes / permission hooks."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

HOME = Path(os.environ["USERPROFILE"])
GROK = HOME / ".grok" / "bin" / "grok.exe"
CWD = HOME / "grok-orbit"


def main() -> int:
    env = os.environ.copy()
    env["GROK_DISABLE_AUTOUPDATER"] = "1"
    proc = subprocess.Popen(
        [str(GROK), "agent", "--no-leader", "stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=str(CWD),
        env=env,
        bufsize=1,
    )
    sink: list[dict] = []

    def read() -> None:
        assert proc.stdout
        for raw in proc.stdout:
            try:
                sink.append(json.loads(raw))
            except json.JSONDecodeError:
                pass

    threading.Thread(target=read, daemon=True).start()

    def send(o: dict) -> None:
        assert proc.stdin
        proc.stdin.write(json.dumps(o) + "\n")
        proc.stdin.flush()

    def wait(i: int) -> dict | None:
        t = time.time() + 30
        while time.time() < t:
            for m in sink:
                if m.get("id") == i:
                    return m
            time.sleep(0.05)
        return None

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientInfo": {"name": "dump", "version": "0"},
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}},
            },
        }
    )
    wait(1)
    send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {
                "cwd": str(CWD),
                "mcpServers": [],
                "_meta": {"yoloMode": False, "permissionMode": "default"},
            },
        }
    )
    created = wait(2)
    print(json.dumps(created, indent=2)[:5000])
    try:
        proc.terminate()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
