from Quartz.CoreGraphics import (
    CGEventSourceSecondsSinceLastEventType,
    CGSessionCopyCurrentDictionary,
    kCGAnyInputEventType,
    kCGEventSourceStateHIDSystemState,
)


def is_screen_locked() -> bool:
    """Return True if the macOS screen/session is locked.

    Uses the CGSSessionScreenIsLocked key from the current CoreGraphics
    session dictionary. That key is only present when the screen is locked
    (e.g. loginwindow after Cmd-Ctrl-Q or after the lock delay).
    """
    session = CGSessionCopyCurrentDictionary()
    if not session:
        return False
    return bool(session.get("CGSSessionScreenIsLocked", False))


def seconds_since_last_input() -> float:
    return CGEventSourceSecondsSinceLastEventType(
        kCGEventSourceStateHIDSystemState, kCGAnyInputEventType
    )


if __name__ == "__main__":
    from time import sleep

    while True:
        sleep(1)
        print(seconds_since_last_input(), is_screen_locked())
