"""Force the isolated Edge grok.com login onto the primary monitor.

Daily Brave swallows isolated Brave. Isolated Edge on grok.com as first
paint can crash. This starts Edge on about:blank in a clean profile, then
opens the xAI sign-in tab, then pins the window to 0,0 maximized + topmost.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from focus import apply_focus
from web_adapters import profile_dir_for

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
SIGNIN = "https://accounts.x.ai/sign-in?redirect=grok-com"

user32 = ctypes.windll.user32
SW_RESTORE = 9
SW_SHOW = 5
SW_MAXIMIZE = 3
HWND_TOP = 0
HWND_NOTOPMOST = -2
SWP_SHOWWINDOW = 0x0040


def all_windows() -> list[tuple[int, bool, str, tuple[int, int, int, int]]]:
    found: list[tuple[int, bool, str, tuple[int, int, int, int]]] = []
    rect = wintypes.RECT()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lp):
        buf = ctypes.create_unicode_buffer(512)
        n = user32.GetWindowTextW(hwnd, buf, 512)
        if not n:
            return True
        vis = bool(user32.IsWindowVisible(hwnd))
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        found.append(
            (
                int(hwnd),
                vis,
                buf.value,
                (rect.left, rect.top, rect.right, rect.bottom),
            )
        )
        return True

    user32.EnumWindows(cb, 0)
    return found


def edge_windows() -> list[tuple[int, bool, str, tuple[int, int, int, int]]]:
    out = []
    for row in all_windows():
        t = row[2].lower()
        if "microsoft" in t and "edge" in t:
            out.append(row)
        elif "profile 1" in t and "edge" in t:
            out.append(row)
    return out


def pin(hwnd: int) -> tuple[int, int, int, int]:
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.ShowWindow(hwnd, SW_MAXIMIZE)
    user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 1600, 1000, SWP_SHOWWINDOW)
    apply_focus(hwnd)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 1600, 1000, SWP_SHOWWINDOW)
    user32.BringWindowToTop(hwnd)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def launch() -> None:
    if not EDGE.is_file():
        raise SystemExit("msedge.exe missing")
    profile = profile_dir_for("grok_web", "msedge")
    profile.mkdir(parents=True, exist_ok=True)
    common = [
        str(EDGE),
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--new-window",
        "--window-position=0,0",
        "--window-size=1600,1000",
    ]
    subprocess.Popen(common + ["about:blank"])
    time.sleep(2.0)
    subprocess.Popen(
        [
            str(EDGE),
            f"--user-data-dir={profile}",
            SIGNIN,
        ]
    )


def main() -> int:
    if not edge_windows():
        launch()
        for _ in range(20):
            time.sleep(0.4)
            if edge_windows():
                break
    wins = edge_windows()
    if not wins:
        print("FAIL no Microsoft Edge window after launch")
        for hwnd, vis, title, box in all_windows():
            if vis and title.strip():
                print("VISIBLE", box, title[:80])
        return 2
    # Pin every Edge window so one of them is unavoidable.
    for hwnd, vis, title, box in wins:
        newbox = pin(hwnd)
        print("PINNED", vis, newbox, title)
    print("OK look at the primary monitor top-left for Microsoft Edge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
