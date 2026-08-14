"""Throwaway ACP probe. Prints initialize + first messages. Does not yolo."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE") or Path.home())
GROK = HOME / ".grok" / "bin" / "grok.exe"
CWD = HOME / "grok-orbit"


def send(proc: subprocess.Popen, msg: dict) -> None:
    line = json.dumps(msg, separators=(",", ":"))
    assert proc.stdin
    proc.stdin.write(line + "\n")
    proc.stdin.flush()
    print(">>", line[:400], flush=True)


def reader(proc: subprocess.Popen, sink: list[dict]) -> None:
    assert proc.stdout
    for raw in proc.stdout:
        line = raw.strip()
        if not line:
            continue
        print("<<", line[:800], flush=True)
        try:
            sink.append(json.loads(line))
        except json.JSONDecodeError:
            sink.append({"_raw": line})


def main() -> int:
    if not GROK.exists():
        print("missing grok", GROK)
        return 2
    env = os.environ.copy()
    env["GROK_DISABLE_AUTOUPDATER"] = "1"
    proc = subprocess.Popen(
        [str(GROK), "agent", "--no-leader", "stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(CWD),
        env=env,
        bufsize=1,
    )
    sink: list[dict] = []
    t = threading.Thread(target=reader, args=(proc, sink), daemon=True)
    t.start()

    def drain_err() -> None:
        assert proc.stderr
        for line in proc.stderr:
            print("EE", line.rstrip(), flush=True)

    threading.Thread(target=drain_err, daemon=True).start()

    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientInfo": {"name": "grok-orbit-probe", "version": "0.1.0"},
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        },
    )
    deadline = time.time() + 20
    while time.time() < deadline and not any(
        isinstance(m, dict) and m.get("id") == 1 for m in sink
    ):
        time.sleep(0.1)

    init = next((m for m in sink if isinstance(m, dict) and m.get("id") == 1), None)
    print("INIT_RESULT", json.dumps(init, indent=2)[:4000] if init else "NONE")

    if "--session" in sys.argv:
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": str(CWD), "mcpServers": []},
            },
        )
        deadline = time.time() + 25
        while time.time() < deadline and not any(
            isinstance(m, dict) and m.get("id") == 2 for m in sink
        ):
            time.sleep(0.1)
        created = next((m for m in sink if isinstance(m, dict) and m.get("id") == 2), None)
        print("NEW_RESULT", json.dumps(created, indent=2)[:4000] if created else "NONE")

    time.sleep(1.5)
    try:
        proc.terminate()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
