import ctypes
import time
from ctypes import POINTER, WINFUNCTYPE, Structure, c_ulonglong  # type: ignore
from ctypes.wintypes import BOOL, DWORD, UINT

ULONGLONG = c_ulonglong


class LastInputInfo(Structure):
    _fields_ = [("cbSize", UINT), ("dwTime", DWORD)]


def _getLastInputTick() -> int:
    prototype = WINFUNCTYPE(BOOL, POINTER(LastInputInfo))
    paramflags = ((1, "lastinputinfo"),)
    c_GetLastInputInfo = prototype(("GetLastInputInfo", ctypes.windll.user32), paramflags)  # type: ignore

    lastinput = LastInputInfo()
    lastinput.cbSize = ctypes.sizeof(LastInputInfo)
    assert 0 != c_GetLastInputInfo(lastinput)
    return lastinput.dwTime


def _getTickCount64() -> int:
    """Use GetTickCount64 to avoid 32-bit overflow after ~49.7 days of uptime."""
    prototype = WINFUNCTYPE(ULONGLONG)
    paramflags = ()
    c_GetTickCount64 = prototype(("GetTickCount64", ctypes.windll.kernel32), paramflags)  # type: ignore
    return c_GetTickCount64()


def seconds_since_last_input():
    tick_count = _getTickCount64()
    last_input_tick = _getLastInputTick()  # 32-bit DWORD from GetLastInputInfo

    # GetLastInputInfo returns a 32-bit DWORD tick count that wraps at 2^32 ms.
    # GetTickCount64 returns 64-bit. To compute the difference correctly, we
    # compare only the lower 32 bits when the values are close (normal case),
    # and handle the wraparound when dwTime > lower 32 bits of tick_count.
    tick_lower32 = tick_count & 0xFFFFFFFF
    if tick_lower32 >= last_input_tick:
        diff_ms = tick_lower32 - last_input_tick
    else:
        # 32-bit wraparound: tick_count's lower bits wrapped past dwTime
        diff_ms = (0x100000000 - last_input_tick) + tick_lower32

    return diff_ms / 1000


if __name__ == "__main__":
    while True:
        time.sleep(1)
        print(seconds_since_last_input())
