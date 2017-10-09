import logging
from Quartz.CoreGraphics import (CGEventSourceSecondsSinceLastEventType,
                                 kCGEventSourceStateHIDSystemState,
                                 kCGAnyInputEventType)


def seconds_since_last_input() -> float:
    return CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)


if __name__ == "__main__":
    from time import sleep
    while True:
        sleep(1)
        print(seconds_since_last_input())
