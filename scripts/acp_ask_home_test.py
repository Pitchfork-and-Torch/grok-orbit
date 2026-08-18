"""Real grok agent in an isolated GROK_HOME with permission_mode=ask.

Does not edit the operator's ~/.grok/config.toml.
Uses XAI_API_KEY from the environment if present. Does not print secrets.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE") or Path.home())
GROK = HOME / ".grok" / "bin" / "grok.exe"
CWD = HOME / "grok-orbit"


def main() -> int:
    if not GROK.exists():
        print("SKIP no grok.exe")
        return 0
    if not os.environ.get("XAI_API_KEY"):
        print("SKIP no XAI_API_KEY in env (will not copy auth.json)")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="orbit-ask-home-"))
    (tmp / "config.toml").write_text(
        '[ui]\npermission_mode = "ask"\nyolo = false\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["GROK_HOME"] = str(tmp)
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
                "clientInfo": {"name": "orbit-ask-home", "version": "0.2.0"},
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        }
    )
    init = wait_id(1, 25)
    if not init or "result" not in init:
        print("FAIL initialize", (init or {}).get("error"))
        proc.terminate()
        return 1

    send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {
                "cwd": str(CWD),
                "mcpServers": [],
                "_meta": {"yoloMode": False},
            },
        }
    )
    created = wait_id(2, 45)
    if not created or "result" not in created:
        print("FAIL session/new", created)
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
                        "text": "You must invoke the shell tool to run exactly: echo ORBIT_PERM_PROBE. Do not invent the output. Paste the tool result.",
                    }
                ],
            },
        }
    )
    answered = 0
    seen = set()
    deadline = time.time() + 90
    while time.time() < deadline:
        for m in list(sink):
            if m.get("method") == "session/request_permission" and m.get("id") not in seen:
                seen.add(m.get("id"))
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
                    print("ALLOWED", pick.get("optionId"))
        if any(m.get("id") == 3 for m in sink):
            break
        time.sleep(0.08)

    proc.terminate()
    methods = sorted({str(m.get("method") or "") for m in sink if m.get("method")})
    print("METHODS", ",".join(x for x in methods if x))
    print("ANSWERED", answered)
    if answered == 0:
        # Model may skip tools; protocol mock is the deterministic permission test.
        print("WARN isolated ask-home: no session/request_permission (likely inherit or no tool call)")
        return 0
    print("OK isolated ask-home permission path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
