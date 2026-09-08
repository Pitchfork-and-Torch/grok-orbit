"""Resolve (and optionally foreground) the window hosting a live Grok pid.

Grok Build often lives inside Windows Terminal, so we walk parent processes.
Default is resolve-only. Pass apply=True to steal focus.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ntdll = ctypes.windll.ntdll

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4
SW_RESTORE = 9
ASFW_ANY = 0xFFFFFFFF
HWND_TOP = 0
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040

user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]


class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
    ]


def _title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    n = user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value if n else ""


def hwnds_for_pid(pid: int) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        out = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(out))
        if out.value != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        hits.append((int(hwnd), _title(int(hwnd))))
        return True

    user32.EnumWindows(cb, 0)
    return hits


def parent_pid(pid: int) -> int | None:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        info = PROCESS_BASIC_INFORMATION()
        ret = ctypes.c_ulong()
        status = ntdll.NtQueryInformationProcess(
            handle, 0, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(ret)
        )
        if status != 0:
            return None
        return int(info.InheritedFromUniqueProcessId or 0)
    finally:
        kernel32.CloseHandle(handle)


def resolve_pid(start_pid: int) -> dict | None:
    if start_pid <= 0:
        return None
    pid = int(start_pid)
    via = f"pid {start_pid}"
    for hop in range(7):
        hits = hwnds_for_pid(pid)
        if hits:
            grok = next((h for h in hits if "grok" in (h[1] or "").lower()), None)
            hwnd, title = grok or hits[0]
            if hop:
                via = f"ancestor pid {pid} of {start_pid}"
            return {"pid": pid, "hwnd": hwnd, "title": title, "via": via}
        parent = parent_pid(pid)
        if not parent or parent in (0, 4, pid):
            return None
        pid = parent
    return None


def apply_focus(hwnd: int) -> bool:
    user32.AllowSetForegroundWindow(ASFW_ANY)
    user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd):
        return True
    return bool(user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW))


def focus_pid(pid: int, apply: bool = False) -> dict:
    hit = resolve_pid(int(pid))
    if not hit:
        return {"error": f"no visible window for pid {pid}"}
    applied = False
    if apply:
        applied = apply_focus(int(hit["hwnd"]))
        if not applied:
            hit["error"] = "Windows refused foreground"
    hit["applied"] = applied
    return hit
