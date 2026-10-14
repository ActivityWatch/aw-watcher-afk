"""Opt-in, stdlib-only Windows idle diagnostic. Does not modify AFK behavior."""

import argparse
import ctypes
import json
import sys
import time
from typing import Dict, Optional


def classify(kind: str, flags: int) -> str:
    """Unflagged does NOT prove physical input (drivers can synthesize it)."""
    injected, lower = {"keyboard": (0x10, 0x02), "mouse": (0x01, 0x02)}[kind]
    if flags & lower:
        return "lower_integrity_injected"
    return "injected" if flags & injected else "unflagged"


def idle_ms(tick: int, last_input: int) -> int:
    return (tick - last_input) & 0xFFFFFFFF


class EventCounts:
    def __init__(self) -> None:
        self.counts = {
            kind + "_" + label: 0
            for kind in ("mouse", "keyboard")
            for label in ("unflagged", "injected", "lower_integrity_injected")
        }

    def observe(self, kind: str, flags: int) -> None:
        self.counts[kind + "_" + classify(kind, flags)] += 1

    def snapshot(self) -> Dict[str, int]:
        counts = self.counts.copy()
        for key in self.counts:
            self.counts[key] = 0
        return counts


def sample_row(
    elapsed: float,
    tick: int,
    last_input: int,
    previous: Optional[int],
    events: Dict[str, int],
) -> dict:
    return {
        "elapsed_s": round(elapsed, 3),
        "idle_ms": idle_ms(tick, last_input),
        "last_input_tick_changed": None if previous is None else last_input != previous,
        "events": events,
    }


def run(duration: int) -> None:
    # Load native APIs only after the platform guard; pure tests work on Linux.
    from ctypes import wintypes as w

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    result_type = ctypes.c_ssize_t
    hook_proc = ctypes.WINFUNCTYPE(result_type, ctypes.c_int, w.WPARAM, w.LPARAM)

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]

    class KeyboardInfo(ctypes.Structure):
        _fields_ = [
            ("vkCode", w.DWORD),
            ("scanCode", w.DWORD),
            ("flags", w.DWORD),
            ("time", w.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class MouseInfo(ctypes.Structure):
        _fields_ = [
            ("pt", w.POINT),
            ("mouseData", w.DWORD),
            ("flags", w.DWORD),
            ("time", w.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    # Explicit signatures preserve handles/pointers on 64-bit Windows.
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, hook_proc, w.HINSTANCE, w.DWORD]
    user32.SetWindowsHookExW.restype = w.HANDLE
    user32.CallNextHookEx.argtypes = [w.HANDLE, ctypes.c_int, w.WPARAM, w.LPARAM]
    user32.CallNextHookEx.restype = result_type
    user32.UnhookWindowsHookEx.argtypes = [w.HANDLE]
    user32.UnhookWindowsHookEx.restype = w.BOOL
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
    user32.GetLastInputInfo.restype = w.BOOL
    kernel32.GetTickCount64.argtypes = []
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    kernel32.GetModuleHandleW.argtypes = [w.LPCWSTR]
    kernel32.GetModuleHandleW.restype = w.HMODULE
    user32.SetTimer.argtypes = [w.HWND, ctypes.c_size_t, w.UINT, ctypes.c_void_p]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.KillTimer.argtypes = [w.HWND, ctypes.c_size_t]
    user32.KillTimer.restype = w.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
    user32.GetMessageW.restype = w.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(w.MSG)]
    user32.TranslateMessage.restype = w.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(w.MSG)]
    user32.DispatchMessageW.restype = result_type

    counts = EventCounts()
    callback_errors = []
    interrupted = False

    def callback(kind, structure):
        def observe(code, message, data):
            nonlocal interrupted
            try:
                if code >= 0:
                    # Only flags are read; never retain keys, coordinates or timestamps.
                    flags = ctypes.cast(data, ctypes.POINTER(structure)).contents.flags
                    counts.observe(kind, flags)
            except KeyboardInterrupt:
                # ctypes cannot propagate this safely to main; defer cancellation.
                interrupted = True
            except Exception:
                # Fail visibly outside the callback, but ALWAYS pass input through.
                callback_errors.append(kind)
            try:
                return user32.CallNextHookEx(None, code, message, data)
            except KeyboardInterrupt:
                # Cancellation can surface on this call's return too; keep the
                # callback boundary exception-free so the loop still stops.
                interrupted = True
                return 0
            except Exception:
                # An exception escaping a ctypes callback is reported only by
                # ctypes; defer it so the run fails visibly instead.
                callback_errors.append(kind)
                return 0

        return hook_proc(observe)

    # Strong references keep callback thunks alive until after unhooking.
    keyboard_callback = callback("keyboard", KeyboardInfo)
    mouse_callback = callback("mouse", MouseInfo)
    hooks = []
    timer = 0
    started = time.monotonic()
    previous = None

    def check_state():
        # Deferred failures are only visible in the main thread.
        if interrupted:
            raise KeyboardInterrupt
        if callback_errors:
            raise RuntimeError("Hook callback failed; observation is incomplete")

    def emit_sample():
        nonlocal previous
        check_state()
        info = LastInputInfo(ctypes.sizeof(LastInputInfo), 0)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        tick = kernel32.GetTickCount64()
        print(
            json.dumps(
                sample_row(
                    time.monotonic() - started,
                    tick,
                    info.dwTime,
                    previous,
                    counts.snapshot(),
                )
            ),
            flush=True,
        )
        previous = info.dwTime

    try:
        module = kernel32.GetModuleHandleW(None)
        if not module:
            raise ctypes.WinError(ctypes.get_last_error())
        for hook_id, proc in ((13, keyboard_callback), (14, mouse_callback)):
            handle = user32.SetWindowsHookExW(hook_id, proc, module, 0)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            hooks.append(handle)
        timer = user32.SetTimer(None, 0, 1000, None)
        if not timer:
            raise ctypes.WinError(ctypes.get_last_error())
        print(
            json.dumps(
                {
                    "status": "hooks_installed",
                    "duration_s": duration,
                    "warning": "unflagged != physical; missing hooks != no input",
                }
            ),
            flush=True,
        )
        emit_sample()
        msg = w.MSG()
        while time.monotonic() - started < duration:
            status = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if status == -1:
                raise ctypes.WinError(ctypes.get_last_error())
            if status == 0:
                break
            if msg.message == 0x0113 and msg.wParam == timer:  # WM_TIMER
                emit_sample()
            else:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        # A callback failure landing after the final sample must still surface,
        # rather than reporting a clean run over incomplete observation.
        check_state()
    finally:
        if timer:
            user32.KillTimer(None, timer)
        for handle in reversed(hooks):
            if not user32.UnhookWindowsHookEx(handle):
                print("WARNING: hook cleanup failed", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration",
        type=int,
        default=120,
        help="seconds to observe (1..600; default 120)",
    )
    args = parser.parse_args()
    if not 1 <= args.duration <= 600:
        parser.error("--duration must be between 1 and 600 seconds")
    if sys.platform != "win32":
        parser.error("this diagnostic requires Windows")
    try:
        run(args.duration)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError) as exc:
        print("Diagnostic failed: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
