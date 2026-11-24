"""Idle time on Linux must measure elapsed time, not wall-clock differences."""

from datetime import datetime
from unittest.mock import patch

import pytest

from aw_watcher_afk import unix


@pytest.fixture
def listeners():
    with patch("aw_watcher_afk.unix.KeyboardListener") as kb, patch(
        "aw_watcher_afk.unix.MouseListener"
    ) as mouse, patch("aw_watcher_afk.unix.GamepadListener") as gamepad:
        for mock in (kb, mouse, gamepad):
            mock.return_value.is_alive.return_value = True
            mock.return_value.has_new_event.return_value = False
        gamepad.return_value.needs_restart.return_value = False
        yield kb, mouse, gamepad


class FakeClocks:
    """Elapsed-time clock plus a wall clock that can jump independently."""

    def __init__(self):
        self.elapsed = 1000.0
        self.wall = datetime(2026, 11, 1, 1, 59, 58)

    def advance(self, seconds, wall=None):
        self.elapsed += seconds
        self.wall = wall if wall is not None else self.wall


@pytest.fixture
def clocks():
    c = FakeClocks()
    with patch(
        "aw_watcher_afk.unix._elapsed", side_effect=lambda: c.elapsed, create=True
    ), patch(
        # The wall clock may jump; idle time must not follow it.
        "aw_watcher_afk.unix.datetime",
        create=True,
    ) as dt:
        dt.now.side_effect = lambda: c.wall
        yield c


def test_dst_fall_back_does_not_give_negative_idle(listeners, clocks):
    watcher = unix.LastInputUnix()
    # 5 s pass while the local wall clock falls back one hour.
    clocks.advance(5, wall=datetime(2026, 11, 1, 1, 0, 3))
    assert watcher.seconds_since_last_input() == pytest.approx(5)


def test_dst_spring_forward_does_not_add_an_hour_of_idle(listeners, clocks):
    clocks.wall = datetime(2026, 3, 29, 1, 59, 58)
    watcher = unix.LastInputUnix()
    clocks.advance(5, wall=datetime(2026, 3, 29, 3, 0, 3))
    assert watcher.seconds_since_last_input() == pytest.approx(5)


def test_gamepad_only_restart_keeps_idle_time(listeners, clocks):
    _, _, gamepad = listeners
    watcher = unix.LastInputUnix()
    clocks.advance(600)
    # A wireless controller powers off while the user is away; keyboard and
    # mouse listeners are healthy and saw no input, so the user is still idle.
    gamepad.return_value.needs_restart.return_value = True
    assert watcher.seconds_since_last_input() == pytest.approx(600)
    assert gamepad.call_count == 2  # still restarted


def test_keyboard_listener_restart_still_resets_idle(listeners, clocks):
    kb, _, _ = listeners
    watcher = unix.LastInputUnix()
    clocks.advance(600)
    # A dead keyboard listener could not record input, so the stale
    # last_activity is not evidence of idleness.
    kb.return_value.is_alive.return_value = False
    assert watcher.seconds_since_last_input() == pytest.approx(0)
