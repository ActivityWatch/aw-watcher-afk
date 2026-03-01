from Quartz.CoreGraphics import (CGEventSourceSecondsSinceLastEventType,
                                 kCGEventSourceStateHIDSystemState,
                                 kCGAnyInputEventType,
                                 CGSessionCopyCurrentDictionary)


def lock_screen_shown() -> bool:
    session = CGSessionCopyCurrentDictionary()
    if "CGSSessionScreenIsLocked" in session:
        return session["CGSSessionScreenIsLocked"] == True
    return False


def seconds_since_last_input() -> float:
    return CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)


if __name__ == "__main__":
    from time import sleep
    while True:
        sleep(1)
        print(seconds_since_last_input(), lock_screen_shown())
