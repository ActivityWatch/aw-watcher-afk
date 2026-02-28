import logging
from datetime import datetime
from time import sleep

from .listeners import KeyboardListener, MouseListener


class LastInputUnix:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # self.logger.setLevel(logging.DEBUG)

        self._start_listeners()
        self.last_activity = datetime.now()

    def _start_listeners(self):
        self.mouseListener = MouseListener()
        self.mouseListener.start()

        self.keyboardListener = KeyboardListener()
        self.keyboardListener.start()

    def _check_listeners(self):
        """Check if input listeners are still alive, restart if dead.

        Pynput listeners can silently die when the X server restarts
        (e.g. after suspend/resume, display server crash, or session switch).
        Without this check, the watcher would permanently report AFK.

        See: https://github.com/ActivityWatch/aw-watcher-afk/issues/27
        """
        if not self.mouseListener.is_alive() or not self.keyboardListener.is_alive():
            self.logger.warning(
                "Input listeners died (X server restart?), reinitializing..."
            )
            self._start_listeners()
            # Reset last_activity so we don't report a huge AFK gap
            self.last_activity = datetime.now()

    def seconds_since_last_input(self) -> float:
        # TODO: This has a delay of however often it is called.
        #       Could be solved by creating a custom listener.
        self._check_listeners()
        now = datetime.now()
        if self.mouseListener.has_new_event() or self.keyboardListener.has_new_event():
            self.logger.debug("New event")
            self.last_activity = now
            # Get/clear events
            self.mouseListener.next_event()
            self.keyboardListener.next_event()
        return (now - self.last_activity).total_seconds()


_last_input_unix = None


def seconds_since_last_input():
    global _last_input_unix

    if _last_input_unix is None:
        _last_input_unix = LastInputUnix()

    return _last_input_unix.seconds_since_last_input()


if __name__ == "__main__":
    while True:
        sleep(1)
        print(seconds_since_last_input())
