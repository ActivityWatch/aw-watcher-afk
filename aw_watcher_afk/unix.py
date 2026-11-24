import logging
import sys
import time
from time import sleep

from .listeners import GamepadListener, KeyboardListener, MouseListener

# Idle time is elapsed time, so measure it on a clock that DST changes, NTP
# steps and manual clock changes can't move. On Linux, CLOCK_BOOTTIME also
# keeps counting during suspend, so a resume without input still reports the
# time away.
#
# This module is the Linux implementation: afk.py imports it only when
# platform.system() == "Linux" (Darwin uses macos.py, Windows uses windows.py).
# The monotonic fallback exists so the module can still be imported by tests on
# other platforms (CLOCK_BOOTTIME is Linux-only); it is not a macOS/BSD code
# path in production.
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
        self._start_mouse_listener()
        self._start_keyboard_listener()
        self._start_gamepad_listener()

    def _start_mouse_listener(self):
        self.mouseListener = MouseListener()
        self.mouseListener.start()

    def _start_keyboard_listener(self):
        self.keyboardListener = KeyboardListener()
        self.keyboardListener.start()

    def _start_gamepad_listener(self):
        # Optional: gamepad support via evdev (Linux only).
        # Starts silently if evdev is not installed or no gamepads are found.
        self.gamepadListener = GamepadListener()
        self.gamepadListener.start()

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
        mouse_died = not self.mouseListener.is_alive()
        keyboard_died = not self.keyboardListener.is_alive()
        gamepad_died = self.gamepadListener.needs_restart()
        if not (mouse_died or keyboard_died or gamepad_died):
            return

        if gamepad_died and (mouse_died or keyboard_died):
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
        # When recovering the keyboard or mouse listener (e.g. after an X
        # server restart), also rescan for gamepads if none is being read: a
        # controller connected since the last scan would otherwise stay
        # invisible, because needs_restart() is False when no gamepad was found.
        rescan_gamepad = gamepad_died or (
            (mouse_died or keyboard_died) and not self.gamepadListener.is_alive()
        )
        # Restart only the listeners that actually died. Stopping a healthy
        # pynput listener discards events it has already buffered, and stopping
        # a healthy keyboard listener also drops its held-key state, so
        # restarting everything because a gamepad disconnected could lose input
        # that has not been polled yet.
        replaced = []
        if mouse_died:
            replaced.append(self.mouseListener)
        if keyboard_died:
            replaced.append(self.keyboardListener)
        if rescan_gamepad:
            replaced.append(self.gamepadListener)
        for listener in replaced:
            listener.stop()
        # A replaced listener may still hold input recorded before it stopped
        # (e.g. a button pressed just before the controller disconnected, or on
        # a second controller whose reader was still running). stop() leaves
        # the event flag intact, so read it after stopping, when no more input
        # can arrive, and before the poll moves on to the new listeners.
        had_pending_input = any(listener.has_new_event() for listener in replaced)
        if mouse_died:
            self._start_mouse_listener()
        if keyboard_died:
            self._start_keyboard_listener()
        if rescan_gamepad:
            self._start_gamepad_listener()
        # A dead keyboard or mouse listener couldn't record input, so its
        # stale last_activity would report a false AFK gap: reset it. A
        # gamepad dying (e.g. a controller powering off while the user is
        # away) says nothing about keyboard/mouse input, so keep the idle
        # time rather than marking an away user as active.
        if mouse_died or keyboard_died or had_pending_input:
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
