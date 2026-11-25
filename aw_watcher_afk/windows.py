import ctypes
import time
from ctypes import POINTER, Structure, c_ulonglong
from ctypes.wintypes import BOOL, DWORD, UINT

ULONGLONG = c_ulonglong

# How far dwTime may lead the sampled tick and still count as fresh input.
# The observed lead is one ~15.6 ms timer tick; a minute leaves ample margin.
_MAX_INPUT_AHEAD_MS = 60_000


class LastInputInfo(Structure):
    _fields_ = [("cbSize", UINT), ("dwTime", DWORD)]


def _getLastInputTick() -> int:
    prototype = ctypes.WINFUNCTYPE(BOOL, POINTER(LastInputInfo))  # type: ignore[attr-defined]
    paramflags = ((1, "lastinputinfo"),)
    c_GetLastInputInfo = prototype(("GetLastInputInfo", ctypes.windll.user32), paramflags)  # type: ignore

    lastinput = LastInputInfo()
    lastinput.cbSize = ctypes.sizeof(LastInputInfo)
    if 0 == c_GetLastInputInfo(lastinput):
        raise OSError("GetLastInputInfo failed")
    return lastinput.dwTime


def _getTickCount64() -> int:
    """Use GetTickCount64 to avoid 32-bit overflow after ~49.7 days of uptime."""
    prototype = ctypes.WINFUNCTYPE(ULONGLONG)  # type: ignore[attr-defined]
    paramflags = ()
    c_GetTickCount64 = prototype(("GetTickCount64", ctypes.windll.kernel32), paramflags)  # type: ignore
    return c_GetTickCount64()


def is_screen_locked() -> bool:
    # TODO: Windows implementation (e.g. WTSQuerySessionInformation)
    return False


def seconds_since_last_input() -> float:
    # Read the last-input tick before the current tick, so input arriving
    # between the two reads can't put dwTime ahead of the sampled tick.
    last_input_tick = _getLastInputTick()  # 32-bit DWORD from GetLastInputInfo
    tick_count = _getTickCount64()

    # GetLastInputInfo returns a 32-bit DWORD tick count that wraps at 2^32 ms,
    # while GetTickCount64 is 64-bit. Subtracting modulo 2^32 handles the wrap.
    diff_ms = ((tick_count & 0xFFFFFFFF) - last_input_tick) & 0xFFFFFFFF

    # A difference just below 2^32 means dwTime is slightly ahead of the tick,
    # not ~49.7 days old. Treating it as a wrap would emit an AFK event starting
    # weeks in the past, so report fresh input instead. Only a small margin is
    # treated this way: longer idle periods (even past 2^31 ms, ~24.9 days) are
    # real. dwTime is 32 bits, so idle times within the margin of 2^32 ms are
    # indistinguishable from input ahead of the tick anyway.
    if 0x100000000 - diff_ms <= _MAX_INPUT_AHEAD_MS:
        return 0.0

    return diff_ms / 1000


if __name__ == "__main__":
    while True:
        time.sleep(1)
        print(seconds_since_last_input(), is_screen_locked())
