import time

import ctypes
from ctypes import Structure, POINTER, WINFUNCTYPE, windll
from ctypes.wintypes import BOOL, UINT, DWORD


class LastInputInfo(Structure):
    _fields_ = [
        ("cbSize", UINT),
        ("dwTime", DWORD)
    ]


def _getLastInputTick():
    prototype = WINFUNCTYPE(BOOL, POINTER(LastInputInfo))
    paramflags = (1, "lastinputinfo"),
    c_GetLastInputInfo = prototype(("GetLastInputInfo", ctypes.windll.user32), paramflags)

    l = LastInputInfo()
    l.cbSize = ctypes.sizeof(LastInputInfo)
    assert 0 != c_GetLastInputInfo(l)
    return l.dwTime


def _getTickCount() -> int:
    prototype = WINFUNCTYPE(DWORD)
    paramflags = ()
    c_GetTickCount = prototype(("GetTickCount", ctypes.windll.kernel32), paramflags)
    return c_GetTickCount()


def time_since_last_input():
    seconds_since_input = (_getTickCount() - _getLastInputTick())/1000
    return seconds_since_input


if __name__ == "__main__":
    while True:
        time.sleep(1)
        print(time_since_last_input())
