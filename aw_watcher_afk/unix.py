import logging
from datetime import datetime, timedelta, timezone
import platform

from .listeners import KeyboardListener, MouseListener


class LastInputUnix:
    def __init__(self):
        self.logger = logging.getLogger("LastInputUnix")
        # self.logger.setLevel(logging.DEBUG)

        self.mouseListener = MouseListener()
        self.mouseListener.start()

        self.keyboardListener = KeyboardListener()
        # FIXME: OS X doesn't seem to like the KeyboardListener, segfaults
        if platform.system() == "Darwin":
            self.logger.warning("KeyboardListener is broken in OS X, will not use for detecting AFK state.")
        else:
            self.keyboardListener.start()

        self.last_activity = datetime.now()

    def seconds_since_last_input(self) -> float:
        # TODO: This has a delay of however often it is called.
        #       Could be solved by creating a custom listener.
        now = datetime.now()
        if self.mouseListener.has_new_event() or self.keyboardListener.has_new_event():
            self.logger.debug("New event")
            self.last_activity = now
            # Get/clear events
            mouse_event = self.mouseListener.next_event()
            keyboard_event = self.keyboardListener.next_event()
        return (now - self.last_activity).total_seconds()

_last_input_unix = None


def seconds_since_last_input():
    global _last_input_unix

    if _last_input_unix is None:
        _last_input_unix = LastInputUnix()

    return _last_input_unix.seconds_since_last_input()


if __name__ == "__main__":
    from time import sleep
    while True:
        sleep(1)
        print(seconds_since_last_input())
