"""Frameless window helpers for Windows: move, resize, maximize, minimize with Win32 calls.

The app window is created without the system title bar (pywebview frameless=True) and draws its own one in HTML.
A frameless window can neither be dragged nor resized by Windows, so the page asks the server to do it and the loops
below follow the mouse until the button is released. Everything works in physical pixels through Win32, so it is
independent of how pywebview scales its own coordinates. Outside Windows every function does nothing."""
import os
import threading
import time

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsZoomed.argtypes = [wintypes.HWND]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

    class MARGINS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]

SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
SW_MINIMIZE, SW_RESTORE = 6, 9
VK_LBUTTON = 0x01
MIN_W, MIN_H = 900, 560  # logical pixels; multiplied by the window's DPI scale

_hwnd = None
_restore_rect = None  # window rect before our own "maximize"
_maximized = False
_busy = threading.Lock()


def find_window(title):
    """Top-level window of this process with the given title (pywebview creates it with the app name)."""
    if not IS_WINDOWS:
        return None
    found = []
    pid = os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def setup(title):
    """Finds the window and gives the borderless frame a shadow and rounded corners (Windows 11)."""
    global _hwnd
    if not IS_WINDOWS:
        return False
    for _ in range(100):  # the window appears a moment after webview.start()
        _hwnd = find_window(title)
        if _hwnd:
            break
        time.sleep(0.1)
    if not _hwnd:
        return False
    try:
        dwmapi.DwmExtendFrameIntoClientArea(_hwnd, ctypes.byref(MARGINS(0, 0, 1, 0)))  # a 1px frame brings the shadow
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        dwmapi.DwmSetWindowAttribute(_hwnd, 33, ctypes.byref(pref), 4)
    except Exception:  # noqa: BLE001 — cosmetic only, older Windows versions lack some of it
        pass
    return True


def _rect():
    r = wintypes.RECT()
    user32.GetWindowRect(_hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def _scale():
    try:
        return max(user32.GetDpiForWindow(_hwnd) / 96, 1)
    except Exception:  # noqa: BLE001
        return 1


def _work_area():
    mon = user32.MonitorFromWindow(_hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(mon, ctypes.byref(info))
    w = info.rcWork
    return w.left, w.top, w.right, w.bottom


def _place(x, y, w, h):
    user32.SetWindowPos(_hwnd, None, int(x), int(y), int(w), int(h), SWP_NOZORDER | SWP_NOACTIVATE)


def _held():
    return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def is_maximized():
    return _maximized


def toggle_maximize():
    """Maximizes to the work area (the taskbar stays visible) or restores the previous size."""
    global _maximized, _restore_rect
    if not _hwnd:
        return False
    if _maximized:
        if _restore_rect:
            l, t, r, b = _restore_rect
            _place(l, t, r - l, b - t)
        _maximized = False
    else:
        _restore_rect = _rect()
        l, t, r, b = _work_area()
        _place(l, t, r - l, b - t)
        _maximized = True
    return _maximized


def minimize():
    if _hwnd:
        user32.ShowWindow(_hwnd, SW_MINIMIZE)


def _run(loop):
    """Runs a mouse-following loop in a thread; only one at a time."""
    def work():
        if not _busy.acquire(blocking=False):
            return
        try:
            loop()
        finally:
            _busy.release()
    threading.Thread(target=work, daemon=True).start()


def start_drag():
    """Moves the window with the cursor until the left button is released; a maximized window is first restored."""
    if not _hwnd:
        return

    def loop():
        global _maximized
        cx, cy = _cursor()
        l, t, r, b = _rect()
        if _maximized and _restore_rect:
            rl, rt, rr, rb = _restore_rect
            w, h = rr - rl, rb - rt
            frac = (cx - l) / max(r - l, 1)  # keep the cursor at the same relative spot of the title bar
            l, t = cx - int(w * frac), t
            _place(l, t, w, h)
            _maximized = False
            r, b = l + w, t + h
        ox, oy = cx - l, cy - t
        w, h = r - l, b - t
        while _held():
            x, y = _cursor()
            _place(x - ox, y - oy, w, h)
            time.sleep(0.008)

    _run(loop)


def start_resize(edge):
    """Resizes from the given edge/corner (n, s, e, w, ne, nw, se, sw) until the left button is released."""
    global _maximized
    if not _hwnd or _maximized or any(c not in "nsew" for c in edge) or not edge:
        return

    def loop():
        sx, sy = _cursor()
        l0, t0, r0, b0 = _rect()
        min_w, min_h = int(MIN_W * _scale()), int(MIN_H * _scale())
        while _held():
            x, y = _cursor()
            dx, dy = x - sx, y - sy
            l, t, r, b = l0, t0, r0, b0
            if "e" in edge:
                r = max(r0 + dx, l0 + min_w)
            if "w" in edge:
                l = min(l0 + dx, r0 - min_w)
            if "s" in edge:
                b = max(b0 + dy, t0 + min_h)
            if "n" in edge:
                t = min(t0 + dy, b0 - min_h)
            _place(l, t, r - l, b - t)
            time.sleep(0.008)

    _run(loop)
