import logging
import sys
import time
from time import sleep

from .listeners import GamepadListener, KeyboardListener, MouseListener

# Idle time is elapsed time, so measure it on a clock that DST changes, NTP
# steps and manual clock changes can't move. On Linux, CLOCK_BOOTTIME also
# keeps counting during suspend, so a resume without input still reports the
# time away.
if sys.platform.startswith("linux"):

    def _elapsed() -> float:
        return time.clock_gettime(time.CLOCK_BOOTTIME)

else:

    def _elapsed() -> float:
        return time.monotonic()


class LastInputUnix:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # self.logger.setLevel(logging.DEBUG)

        self._start_listeners()
        self.last_activity = _elapsed()

    def _start_listeners(self):
        self.mouseListener = MouseListener()
        self.mouseListener.start()

        self.keyboardListener = KeyboardListener()
        self.keyboardListener.start()

        # Optional: gamepad support via evdev (Linux only).
        # Starts silently if evdev is not installed or no gamepads are found.
        self.gamepadListener = GamepadListener()
        self.gamepadListener.start()

    def _stop_listeners(self):
        """Stop existing listeners to avoid duplicate instances."""
        if self.mouseListener.is_alive():
            self.mouseListener.stop()
        if self.keyboardListener.is_alive():
            self.keyboardListener.stop()
        if self.gamepadListener.is_alive():
            self.gamepadListener.stop()

    def _check_listeners(self):
        """Check if input listeners are still alive, restart if dead.

        Pynput listeners can silently die when the X server restarts
        (e.g. after suspend/resume, display server crash, or session switch).
        Without this check, the watcher would permanently report AFK.

        See: https://github.com/ActivityWatch/aw-watcher-afk/issues/27
        """
        # Only restart the gamepad listener if it was actually running before
        # and all its threads died (e.g. device unplugged). Without this guard,
        # systems without a gamepad would trigger a restart on every poll,
        # since is_alive() is always False when start() returned early.
        gamepad_died = self.gamepadListener.needs_restart()
        if (
            not self.mouseListener.is_alive()
            or not self.keyboardListener.is_alive()
            or gamepad_died
        ):
            mouse_kb_died = (
                not self.mouseListener.is_alive()
                or not self.keyboardListener.is_alive()
            )
            if gamepad_died and mouse_kb_died:
                self.logger.warning(
                    "All input listeners died (X server restart?), reinitializing..."
                )
            elif gamepad_died:
                self.logger.warning(
                    "Gamepad listener died (device removed?), reinitializing..."
                )
            else:
                self.logger.warning(
                    "Input listeners died (X server restart?), reinitializing..."
                )
            # Stop any still-running listeners before creating new ones
            # to avoid duplicate listener instances (e.g. if only one died)
            self._stop_listeners()
            self._start_listeners()
            # A dead keyboard or mouse listener couldn't record input, so its
            # stale last_activity would report a false AFK gap: reset it. A
            # gamepad dying (e.g. a controller powering off while the user is
            # away) says nothing about keyboard/mouse input, so keep the idle
            # time rather than marking an away user as active.
            if mouse_kb_died:
                self.last_activity = _elapsed()

    def seconds_since_last_input(self) -> float:
        # TODO: This has a delay of however often it is called.
        #       Could be solved by creating a custom listener.
        self._check_listeners()
        now = _elapsed()
        has_event = (
            self.mouseListener.has_new_event()
            or self.keyboardListener.has_new_event()
            or self.gamepadListener.has_new_event()
        )
        if has_event:
            self.logger.debug("New event")
            self.last_activity = now
            # Get/clear events
            self.mouseListener.next_event()
            self.keyboardListener.next_event()
            self.gamepadListener.next_event()
        return now - self.last_activity


_last_input_unix = None


def seconds_since_last_input():
    global _last_input_unix

    if _last_input_unix is None:
        _last_input_unix = LastInputUnix()

    return _last_input_unix.seconds_since_last_input()


def is_screen_locked() -> bool:
    # TODO: Linux implementation (e.g. logind LockedHint / DBus screensaver)
    return False


if __name__ == "__main__":
    while True:
        sleep(1)
        print(seconds_since_last_input(), is_screen_locked())
