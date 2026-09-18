"""Ask-mode permission path. Allows the first option whose kind is allow_once."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE") or Path.home())
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
            line = raw.strip()
            if line:
                try:
                    sink.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    threading.Thread(target=read, daemon=True).start()

    def send(msg: dict) -> None:
        assert proc.stdin
        proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def wait_id(rid: int, timeout: float) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for m in sink:
                if m.get("id") == rid:
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
                "clientInfo": {"name": "grok-orbit-perm", "version": "0.2.0"},
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        }
    )
    if not wait_id(1, 25):
        print("FAIL initialize")
        proc.terminate()
        return 1
    send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": str(CWD), "mcpServers": []},
        }
    )
    created = wait_id(2, 45)
    if not created or "result" not in created:
        print("FAIL session/new")
        proc.terminate()
        return 1
    sid = created["result"]["sessionId"]
    send(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {
                "sessionId": sid,
                "prompt": [
                    {
                        "type": "text",
                        "text": "Use a file-read tool to read DESIGN.md in this directory. Then reply with the first markdown heading only.",
                    }
                ],
            },
        }
    )
    answered = 0
    seen_ids = set()
    deadline = time.time() + 90
    while time.time() < deadline:
        for m in list(sink):
            if m.get("method") == "session/request_permission" and m.get("id") not in seen_ids:
                seen_ids.add(m.get("id"))
                opts = (m.get("params") or {}).get("options") or []
                pick = next((o for o in opts if o.get("kind") == "allow_once"), None)
                if not pick and opts:
                    pick = opts[0]
                if pick:
                    send(
                        {
                            "jsonrpc": "2.0",
                            "id": m["id"],
                            "result": {
                                "outcome": {
                                    "outcome": "selected",
                                    "optionId": pick.get("optionId"),
                                }
                            },
                        }
                    )
                    answered += 1
                    title = ((m.get("params") or {}).get("toolCall") or {}).get("title")
                    print("ALLOWED", pick.get("optionId"), title)
        if any(m.get("id") == 3 for m in sink):
            break
        time.sleep(0.08)
    done = any(m.get("id") == 3 for m in sink)
    print("ANSWERED", answered, "PROMPT_DONE", done)
    try:
        proc.terminate()
    except Exception:
        pass
    if answered == 0:
        print("FAIL no permission request")
        return 1
    print("OK permission path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
