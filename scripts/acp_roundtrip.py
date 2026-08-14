"""ACP roundtrip against grok agent stdio. Ask-mode. No yolo."""

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


class Acp:
    def __init__(self) -> None:
        env = os.environ.copy()
        env["GROK_DISABLE_AUTOUPDATER"] = "1"
        self.proc = subprocess.Popen(
            [str(GROK), "agent", "--no-leader", "stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=str(CWD),
            env=env,
            bufsize=1,
        )
        self.sink: list[dict] = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.proc.stdout
        for raw in self.proc.stdout:
            line = raw.strip()
            if not line:
                continue
            try:
                self.sink.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    def send(self, msg: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def wait_id(self, rid: int, timeout: float) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for m in self.sink:
                if m.get("id") == rid:
                    return m
            time.sleep(0.05)
        return None

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass


def main() -> int:
    acp = Acp()
    acp.send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientInfo": {"name": "grok-orbit-roundtrip", "version": "0.2.0"},
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        }
    )
    init = acp.wait_id(1, 25)
    if not init or "result" not in init:
        print("FAIL initialize", init)
        acp.close()
        return 1
    caps = init["result"].get("agentCapabilities") or {}
    print("OK initialize loadSession=", caps.get("loadSession"), "resume=", bool((caps.get("sessionCapabilities") or {}).get("resume")))

    acp.send(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/new",
            "params": {"cwd": str(CWD), "mcpServers": []},
        }
    )
    created = acp.wait_id(2, 45)
    if not created or "result" not in created:
        print("FAIL session/new", created)
        acp.close()
        return 1
    sid = created["result"]["sessionId"]
    print("OK session/new", sid)

    acp.send(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {
                "sessionId": sid,
                "prompt": [
                    {
                        "type": "text",
                        "text": "Reply with only the single word PONG. Do not use tools.",
                    }
                ],
            },
        }
    )
    deadline = time.time() + 90
    texts: list[str] = []
    perms = 0
    while time.time() < deadline:
        for m in list(acp.sink):
            if m.get("method") == "session/request_permission" and m.get("id") is not None:
                perms += 1
                acp.send(
                    {
                        "jsonrpc": "2.0",
                        "id": m["id"],
                        "result": {"outcome": {"outcome": "cancelled"}},
                    }
                )
                print("PERM cancelled", (m.get("params") or {}).get("toolCall", {}).get("title"))
            upd = (m.get("params") or {}).get("update") or {}
            if upd.get("sessionUpdate") == "agent_message_chunk":
                t = ((upd.get("content") or {}).get("text")) or ""
                if t:
                    texts.append(t)
        if any(m.get("id") == 3 for m in acp.sink):
            break
        time.sleep(0.1)

    blob = "".join(texts)
    print("TEXT", blob[:400].replace("\n", " "))
    print("PERMS", perms)
    done = any(m.get("id") == 3 for m in acp.sink)
    print("PROMPT_DONE", done)
    acp.close()
    if "PONG" in blob.upper():
        print("OK pong")
        return 0
    if done:
        print("WARN turn finished without PONG")
        return 0
    print("FAIL no prompt completion")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
