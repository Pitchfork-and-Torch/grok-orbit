"""Unattended Orbit gate. No GUI. No operator clicks. Exit 0 = green."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("USERPROFILE") or Path.home())
PY = [sys.executable]


def resolve_cmd(cmd: list[str]) -> list[str]:
    head = cmd[0]
    found = shutil.which(head)
    if found:
        cmd = [found, *cmd[1:]]
        return cmd
    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat"):
            found = shutil.which(head + ext)
            if found:
                return [found, *cmd[1:]]
    return cmd


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 180) -> tuple[int, str]:
    p = subprocess.run(
        resolve_cmd(cmd),
        cwd=str(cwd or ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out


def live_refuse() -> None:
    path = HOME / ".grok" / "active_sessions.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    live = [r for r in rows if isinstance(r, dict) and r.get("session_id") and r.get("pid")]
    if not live:
        print("OK live-refuse skipped (no live pagers)")
        return
    sid = live[0]["session_id"]
    # Same rule Orbit ACP uses.
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(live[0]["pid"]))
    alive = bool(handle)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
    if alive:
        print("OK live-refuse would block", sid[:8], "pid", live[0]["pid"])
    else:
        print("OK live-refuse pid dead, attach allowed", sid[:8])


def main() -> int:
    fast = "--fast" in sys.argv
    failed: list[str] = []

    code, out = run(PY + [str(ROOT / "scripts" / "snapshot.py")])
    if code != 0 or '"situation"' not in out:
        failed.append("snapshot")
        print("FAIL snapshot")
        print(out[-800:])
    else:
        data = json.loads(out)
        print("OK snapshot", data.get("elapsed_ms"), "ms", data.get("situation", "")[:160])
        hot = any(
            a.get("kind") in ("stale", "running", "pr_ready", "desk_claim")
            for a in (data.get("attention") or [])
        )
        if hot and not str(data.get("situation") or "").startswith("Next:"):
            failed.append("snapshot-next")
            print("FAIL situation missing Next hop")
        else:
            print("OK situation next", (data.get("situation") or "")[:48])
        from snapshot import build_next

        nxt = build_next()
        if not nxt.get("cheap") or "suggested_hop" not in nxt:
            failed.append("cheap-next")
            print("FAIL cheap next", nxt)
        else:
            print("OK cheap next", nxt.get("elapsed_ms"), "ms", nxt.get("suggested_hop"))
        surf = data.get("surfaces") or {}
        if "grok_web" not in surf:
            failed.append("snapshot-web")
            print("FAIL snapshot missing grok_web surface")
        else:
            print("OK web-surface", surf.get("grok_web"), surf.get("cursor_web"), "consent", surf.get("web_consent"))
            if "cursor_web_probed_at" not in surf:
                failed.append("snapshot-cursor-probed")
                print("FAIL snapshot missing cursor_web_probed_at")
            else:
                print("OK cursor probed_at", surf.get("cursor_web_probed_at") or "none")
            pr_n = sum(1 for s in (data.get("sessions") or []) if s.get("pr_url"))
            pr_att = sum(1 for a in (data.get("attention") or []) if a.get("kind") == "pr_ready")
            from snapshot import unique_pr_groups

            uniq = len(unique_pr_groups(data.get("sessions") or [], clearance_only=True))
            if uniq and pr_att == 0:
                failed.append("snapshot-pr-ready")
                print("FAIL snapshot has open pr_url but no pr_ready attention")
            elif pr_att != uniq:
                failed.append("snapshot-pr-collapse")
                print("FAIL pr_ready", pr_att, "!= unique open", uniq, "agents", pr_n)
            else:
                print("OK pr_ready", pr_att, "open of", pr_n, "agents")
            if not data.get("snap_profile"):
                failed.append("snapshot-profile")
                print("FAIL snapshot missing snap_profile")
            else:
                print("OK snap_profile", str(data.get("snap_profile"))[:80])
        if "activity" not in data:
            failed.append("snapshot-activity")
            print("FAIL snapshot missing activity")
        else:
            print("OK activity", len(data.get("activity") or []))
        if "local_exec_alive" not in surf or "steward_pack" not in surf:
            failed.append("snapshot-bot-fields")
            print("FAIL snapshot missing bot surface fields")
        else:
            print(
                "OK bot-surface exec",
                surf.get("local_exec_alive"),
                "pack",
                surf.get("steward_pack"),
            )

    live_refuse()

    code, out = run(PY + [str(ROOT / "scripts" / "resume_guard_test.py")], timeout=20)
    print(out.strip())
    if code != 0:
        failed.append("resume-guard")

    code, out = run(PY + [str(ROOT / "scripts" / "handoff_test.py")], timeout=40)
    print(out.strip())
    if code != 0:
        failed.append("handoff")

    code, out = run(PY + [str(ROOT / "scripts" / "projects_test.py")], timeout=20)
    print(out.strip())
    if code != 0:
        failed.append("projects")

    code, out = run(PY + [str(ROOT / "scripts" / "brave_grok_test.py")], timeout=20)
    print(out.strip())
    if code != 0:
        failed.append("brave-grok")

    code, out = run(PY + [str(ROOT / "scripts" / "cook_test.py")], timeout=20)
    print(out.strip())
    if code != 0:
        failed.append("cook")

    code, out = run(PY + [str(ROOT / "scripts" / "pr_state_test.py")], timeout=20)
    print(out.strip())
    if code != 0:
        failed.append("pr-state")

    code, out = run(PY + [str(ROOT / "scripts" / "web_adapters_test.py")], timeout=20)
    print(out.strip())
    if code != 0:
        failed.append("web-adapters")

    code, out = run(PY + [str(ROOT / "scripts" / "portable_acp_mock_test.py")], timeout=20)
    print(out.strip())
    if code != 0:
        failed.append("portable-mock")

    code, out = run(
        ["cargo", "test", "--lib"],
        cwd=ROOT / "src-tauri",
        timeout=180,
    )
    if code != 0:
        failed.append("cargo-test")
        print(out[-1200:])
    else:
        print("OK cargo test")

    code, out = run(["npx", "--yes", "tsc", "--noEmit"], timeout=60)
    if code != 0:
        failed.append("tsc")
        print(out[-800:])
    else:
        print("OK tsc")

    code, out = run(PY + [str(ROOT / "scripts" / "orbit_mcp_test.py")], timeout=40)
    print(out.strip())
    if code != 0:
        failed.append("orbit-mcp")

    if fast:
        print("SKIP live ACP (--fast)")
        print("---")
        if failed:
            print("FAIL", ",".join(failed))
            return 1
        print("OK orbit auto-test fast gates")
        return 0

    code, out = run(PY + [str(ROOT / "scripts" / "acp_roundtrip.py")], timeout=150)
    print(out.strip()[-600:])
    if code != 0:
        failed.append("acp-roundtrip")

    code, out = run(PY + [str(ROOT / "scripts" / "acp_ask_home_test.py")], timeout=150)
    print(out.strip()[-600:])
    if code != 0:
        failed.append("acp-ask-home")

    print("---")
    if failed:
        print("FAIL", ",".join(failed))
        return 1
    print("OK orbit auto-test all gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
