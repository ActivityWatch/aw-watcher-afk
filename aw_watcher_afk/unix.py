import logging
import os
import subprocess
from datetime import datetime
from time import sleep

from .listeners import GamepadListener, KeyboardListener, MouseListener


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
            # Reset last_activity so we don't report a huge AFK gap
            self.last_activity = datetime.now()

    def seconds_since_last_input(self) -> float:
        # TODO: This has a delay of however often it is called.
        #       Could be solved by creating a custom listener.
        self._check_listeners()
        now = datetime.now()
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
        return (now - self.last_activity).total_seconds()


_last_input_unix = None


def seconds_since_last_input():
    global _last_input_unix

    if _last_input_unix is None:
        _last_input_unix = LastInputUnix()

    return _last_input_unix.seconds_since_last_input()


logger = logging.getLogger(__name__)

# Set to False once we know loginctl isn't installed (non-systemd systems),
# so we stop spawning a process on every poll.
_loginctl_available = True
# Last state loginctl confirmed. A failed query returns this instead of
# False, so a transient failure while locked doesn't read as an unlock.
_last_locked = False


def is_screen_locked() -> bool:
    """Return True if the logind session reports the screen as locked.

    Reads the session's ``LockedHint`` property, which desktop environments
    and lockers set via logind when the screen locks (GNOME, KDE Plasma, and
    others). Lockers that don't set it (e.g. plain i3lock) are not detected.

    Uses ``$XDG_SESSION_ID`` if set, else logind's ``auto`` session (the
    caller's session, or the user's display session). If a query fails, the
    last confirmed state is returned (False if there is none yet).
    """
    global _loginctl_available, _last_locked

    if not _loginctl_available:
        return False

    session = os.environ.get("XDG_SESSION_ID") or "auto"
    try:
        result = subprocess.run(
            ["loginctl", "show-session", session, "-p", "LockedHint", "--value"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except FileNotFoundError:
        logger.info("loginctl not found, screen lock detection disabled")
        _loginctl_available = False
        return False
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug(f"Failed to query screen lock state: {e}")
        return _last_locked

    if result.returncode != 0:
        logger.debug(f"loginctl failed: {result.stderr.strip()}")
        return _last_locked
    _last_locked = result.stdout.strip() == "yes"
    return _last_locked


if __name__ == "__main__":
    while True:
        sleep(1)
        print(seconds_since_last_input(), is_screen_locked())
