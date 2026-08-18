"""Portable ACP permission mock. Python 3 only. No grok binary. No GUI.

A fake agent speaks JSON-RPC on stdio. The client under test is this
script: initialize, session/new, session/prompt, then answer
session/request_permission. Cloud VMs can run this if they have Python 3.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import queue


def fake_agent(stdin: io.TextIOBase, stdout: io.TextIOBase) -> None:
    pending_prompt_id = None
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "protocolVersion": 1,
                            "agentCapabilities": {
                                "loadSession": True,
                                "sessionCapabilities": {"resume": {}, "close": {}},
                            },
                        },
                    }
                )
                + "\n"
            )
            stdout.flush()
        elif method == "session/new":
            stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {"sessionId": "01a00000-0000-7000-8000-000000000001"},
                    }
                )
                + "\n"
            )
            stdout.flush()
        elif method == "session/prompt":
            pending_prompt_id = mid
            stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 9001,
                        "method": "session/request_permission",
                        "params": {
                            "sessionId": "01a00000-0000-7000-8000-000000000001",
                            "toolCall": {
                                "toolCallId": "call_1",
                                "title": "Read DESIGN.md",
                                "kind": "read",
                            },
                            "options": [
                                {
                                    "optionId": "allow-once",
                                    "name": "Allow once",
                                    "kind": "allow_once",
                                },
                                {
                                    "optionId": "reject-once",
                                    "name": "Reject",
                                    "kind": "reject_once",
                                },
                            ],
                        },
                    }
                )
                + "\n"
            )
            stdout.flush()
        elif "result" in msg and mid == 9001:
            outcome = ((msg.get("result") or {}).get("outcome") or {}).get("optionId")
            stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "01a00000-0000-7000-8000-000000000001",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {
                                    "type": "text",
                                    "text": "ALLOWED:" + str(outcome),
                                },
                            },
                        },
                    }
                )
                + "\n"
            )
            stdout.flush()
            if pending_prompt_id is not None:
                stdout.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": pending_prompt_id,
                            "result": {"stopReason": "end_turn"},
                        }
                    )
                    + "\n"
                )
                stdout.flush()
            return


def run_client() -> int:
    to_agent: queue.Queue[str] = queue.Queue()
    from_agent: queue.Queue[str] = queue.Queue()

    class QIn(io.TextIOBase):
        def __iter__(self):
            while True:
                item = to_agent.get()
                if item is None:
                    return
                yield item

    class QOut(io.TextIOBase):
        def write(self, s: str) -> int:
            from_agent.put(s)
            return len(s)

        def flush(self) -> None:
            return None

    t = threading.Thread(target=fake_agent, args=(QIn(), QOut()), daemon=True)
    t.start()

    def send(obj: dict) -> None:
        to_agent.put(json.dumps(obj) + "\n")

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": 1, "clientInfo": {"name": "orbit-mock", "version": "0"}},
        }
    )
    init = json.loads(from_agent.get(timeout=5))
    assert init.get("result", {}).get("protocolVersion") == 1, init

    send({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": "/", "mcpServers": []}})
    created = json.loads(from_agent.get(timeout=5))
    sid = created["result"]["sessionId"]
    assert sid.startswith("01a00000"), created

    send(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {"sessionId": sid, "prompt": [{"type": "text", "text": "read it"}]},
        }
    )
    perm = json.loads(from_agent.get(timeout=5))
    assert perm.get("method") == "session/request_permission", perm
    opts = perm["params"]["options"]
    pick = next(o for o in opts if o["kind"] == "allow_once")
    send(
        {
            "jsonrpc": "2.0",
            "id": perm["id"],
            "result": {"outcome": {"outcome": "selected", "optionId": pick["optionId"]}},
        }
    )
    update = json.loads(from_agent.get(timeout=5))
    text = update["params"]["update"]["content"]["text"]
    done = json.loads(from_agent.get(timeout=5))
    assert "ALLOWED:allow-once" == text, text
    assert done.get("id") == 3, done
    to_agent.put(None)
    print("OK portable mock permission allow-once")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run_client())
    except Exception as e:
        print("FAIL", type(e).__name__, e)
        raise SystemExit(1)
