import logging
import os
import subprocess
from datetime import datetime
from time import monotonic, sleep
from typing import Optional

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
# False, so a brief failure while locked doesn't read as an unlock.
_last_locked = False
# When the current streak of failed queries began (time.monotonic()), or None
# if the last query succeeded.
_failing_since: Optional[float] = None
# How long the last confirmed lock state is trusted while queries keep failing.
# Long enough to ride out a logind restart or a slow bus, short enough that a
# lock that can no longer be re-confirmed can't pin the watcher AFK forever
# after the user has unlocked and resumed activity.
_LOCK_STATE_TRUST_SECONDS = 300.0


def _after_failed_query() -> bool:
    """Return the screen-lock state to report after a failed loginctl query.

    A short failure streak keeps the last confirmed state, so a blip while
    locked doesn't emit a false ``not-afk`` transition and split the locked AFK
    interval. Once the streak has lasted ``_LOCK_STATE_TRUST_SECONDS`` the
    confirmed lock can no longer be trusted: we log one warning and fall back to
    unlocked, so real activity can bring the watcher back from AFK. Recovery is
    automatic on the first successful query.
    """
    global _last_locked, _failing_since

    now = monotonic()
    if _failing_since is None:
        _failing_since = now
    if _last_locked and now - _failing_since >= _LOCK_STATE_TRUST_SECONDS:
        logger.warning(
            "loginctl has been failing for %.0fs; no longer trusting the last "
            "confirmed locked state",
            now - _failing_since,
        )
        _last_locked = False
    return _last_locked


def is_screen_locked() -> bool:
    """Return True if the logind session reports the screen as locked.

    Reads the session's ``LockedHint`` property, which desktop environments
    and lockers set via logind when the screen locks (GNOME, KDE Plasma, and
    others). Lockers that don't set it (e.g. plain i3lock) are not detected.

    Uses ``$XDG_SESSION_ID`` if set, else logind's ``auto`` session (the
    caller's session, or the user's display session). If a query fails, the
    last confirmed state is returned (False if there is none yet) for up to
    ``_LOCK_STATE_TRUST_SECONDS``, after which it falls back to unlocked. The
    check recovers on the first successful query.
    """
    global _loginctl_available, _last_locked, _failing_since

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
        _last_locked = False
        return False
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug(f"Failed to query screen lock state: {e}")
        return _after_failed_query()

    if result.returncode != 0:
        logger.debug(f"loginctl failed: {result.stderr.strip()}")
        return _after_failed_query()
    _failing_since = None
    _last_locked = result.stdout.strip() == "yes"
    return _last_locked


if __name__ == "__main__":
    while True:
        sleep(1)
        print(seconds_since_last_input(), is_screen_locked())
