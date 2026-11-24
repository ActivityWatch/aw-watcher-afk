"""Idle time on Linux must measure elapsed time, not wall-clock differences.

Before this fix, ``unix.py`` took ``last_activity`` and ``now`` from
``datetime.now()``, so a DST change (or NTP step, or manual clock change)
shifted idle time by an hour. The tests below pin idle time to the elapsed
clock, and pin which listeners get restarted when one of them dies.

Written with ``unittest`` so the existing ``make test`` discovery pattern
(``test_afk_*.py``) picks it up in CI.
"""

import sys
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from aw_watcher_afk import unix


class FakeElapsedClock:
    """A controllable elapsed-time clock, in seconds."""

    def __init__(self):
        self.elapsed = 1000.0

    def advance(self, seconds):
        self.elapsed += seconds


def _listener_mock():
    listener = MagicMock()
    listener.is_alive.return_value = True
    listener.has_new_event.return_value = False
    listener.needs_restart.return_value = False
    return listener


class FakeClocks:
    """Elapsed clock plus a local wall clock that can jump independently."""

    def __init__(self, wall):
        self.elapsed = 1000.0
        self.wall = wall

    def advance(self, seconds, wall):
        self.elapsed += seconds
        self.wall = wall


class WallClockJumpTests(unittest.TestCase):
    """Idle time must follow elapsed time while the wall clock jumps.

    ``_elapsed()`` is left unpatched: the OS clocks behind it are faked, with
    the wall clock (``time.time()`` and a naive ``datetime.now()``, which the
    pre-fix code used) jumping independently. A regression back to wall-clock
    arithmetic makes these tests fail.
    """

    def _run(self, wall_before, wall_after):
        clocks = FakeClocks(wall_before)
        fake_datetime = MagicMock(wraps=datetime)
        fake_datetime.now.side_effect = lambda *a, **kw: clocks.wall
        patchers = [
            patch("aw_watcher_afk.unix.MouseListener", side_effect=_listener_mock),
            patch("aw_watcher_afk.unix.KeyboardListener", side_effect=_listener_mock),
            patch("aw_watcher_afk.unix.GamepadListener", side_effect=_listener_mock),
            patch("aw_watcher_afk.unix.datetime", fake_datetime, create=True),
            patch.object(
                unix.time, "clock_gettime", side_effect=lambda _clk: clocks.elapsed
            ),
            patch.object(unix.time, "monotonic", side_effect=lambda: clocks.elapsed),
            patch.object(
                unix.time, "time", side_effect=lambda: clocks.wall.timestamp()
            ),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            watcher = unix.LastInputUnix()
            clocks.advance(5, wall=wall_after)
            return watcher.seconds_since_last_input()
        finally:
            for patcher in reversed(patchers):
                patcher.stop()

    def test_dst_fall_back_does_not_give_negative_idle(self):
        # 5 s pass while the local wall clock falls back one hour. The old
        # wall-clock arithmetic reported -3595 s and delayed AFK detection by
        # an hour.
        idle = self._run(
            datetime(2026, 11, 1, 1, 59, 58), datetime(2026, 11, 1, 1, 0, 3)
        )
        self.assertAlmostEqual(idle, 5.0)

    def test_dst_spring_forward_does_not_add_an_hour_of_idle(self):
        # 5 s pass while the local wall clock jumps forward one hour: the hour
        # that was actually worked must not be backdated as AFK (+3605 s).
        idle = self._run(
            datetime(2026, 3, 29, 1, 59, 58), datetime(2026, 3, 29, 3, 0, 3)
        )
        self.assertAlmostEqual(idle, 5.0)


class UnixIdleClockTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeElapsedClock()
        self.patchers = [
            patch("aw_watcher_afk.unix.MouseListener"),
            patch("aw_watcher_afk.unix.KeyboardListener"),
            patch("aw_watcher_afk.unix.GamepadListener"),
            patch(
                "aw_watcher_afk.unix._elapsed",
                side_effect=lambda: self.clock.elapsed,
            ),
        ]
        self.mouse, self.kb, self.gamepad, _ = [p.start() for p in self.patchers]
        for mock in (self.mouse, self.kb, self.gamepad):
            mock.return_value.is_alive.return_value = True
            mock.return_value.has_new_event.return_value = False
        self.gamepad.return_value.needs_restart.return_value = False
        self.addCleanup(self._stop_patchers)

    def _stop_patchers(self):
        for patcher in self.patchers:
            patcher.stop()

    def test_gamepad_only_restart_keeps_idle_time(self):
        watcher = unix.LastInputUnix()
        self.clock.advance(600)
        # A wireless controller powers off while the user is away; keyboard and
        # mouse listeners are healthy and saw no input, so the user is still
        # idle.
        self.gamepad.return_value.needs_restart.return_value = True
        self.assertAlmostEqual(watcher.seconds_since_last_input(), 600.0)
        # The gamepad is restarted, but healthy listeners are left alone so
        # their buffered events are not discarded.
        self.assertEqual(self.gamepad.call_count, 2)
        self.assertEqual(self.mouse.call_count, 1)
        self.assertEqual(self.kb.call_count, 1)

    def test_gamepad_only_restart_with_pending_gamepad_input_counts_it(self):
        # A button press lands on the controller just before it disconnects.
        # The dead gamepad listener is replaced before the poll reads events,
        # so its pending input must be harvested first, not dropped.
        old_gamepad, new_gamepad = _listener_mock(), _listener_mock()
        self.gamepad.side_effect = [old_gamepad, new_gamepad]
        watcher = unix.LastInputUnix()
        self.clock.advance(600)
        old_gamepad.has_new_event.return_value = True
        old_gamepad.needs_restart.return_value = True
        self.assertAlmostEqual(watcher.seconds_since_last_input(), 0.0)
        self.assertIs(watcher.gamepadListener, new_gamepad)

    def test_gamepad_only_restart_keeps_pending_mouse_input(self):
        # A click is buffered on the healthy mouse listener when the controller
        # disconnects: the mouse listener is not replaced, so the click counts.
        watcher = unix.LastInputUnix()
        self.clock.advance(600)
        self.gamepad.return_value.needs_restart.return_value = True
        self.mouse.return_value.has_new_event.return_value = True
        self.assertAlmostEqual(watcher.seconds_since_last_input(), 0.0)
        self.assertEqual(self.mouse.call_count, 1)
        self.mouse.return_value.next_event.assert_called_once()

    def test_keyboard_recovery_rescans_for_gamepad_when_none_running(self):
        # No controller was connected at the last scan, so needs_restart() is
        # False. Recovering the keyboard listener (e.g. after an X restart)
        # must still rescan, so a controller connected since then is tracked.
        self.gamepad.return_value.is_alive.return_value = False
        watcher = unix.LastInputUnix()
        self.clock.advance(600)
        self.kb.return_value.is_alive.return_value = False
        watcher.seconds_since_last_input()
        self.assertEqual(self.gamepad.call_count, 2)

    def test_keyboard_listener_restart_still_resets_idle(self):
        watcher = unix.LastInputUnix()
        self.clock.advance(600)
        # A dead keyboard listener could not record input, so the stale
        # last_activity is not evidence of idleness.
        self.kb.return_value.is_alive.return_value = False
        self.assertAlmostEqual(watcher.seconds_since_last_input(), 0.0)
        self.assertEqual(self.kb.call_count, 2)
        self.assertEqual(self.mouse.call_count, 1)
        self.assertEqual(self.gamepad.call_count, 1)

    def test_mouse_listener_restart_still_resets_idle(self):
        watcher = unix.LastInputUnix()
        self.clock.advance(600)
        self.mouse.return_value.is_alive.return_value = False
        self.assertAlmostEqual(watcher.seconds_since_last_input(), 0.0)
        self.assertEqual(self.mouse.call_count, 2)
        self.assertEqual(self.kb.call_count, 1)
        self.assertEqual(self.gamepad.call_count, 1)

    def test_no_restart_when_all_listeners_alive(self):
        watcher = unix.LastInputUnix()
        self.clock.advance(30)
        self.assertAlmostEqual(watcher.seconds_since_last_input(), 30.0)
        self.assertEqual(self.mouse.call_count, 1)
        self.assertEqual(self.kb.call_count, 1)
        self.assertEqual(self.gamepad.call_count, 1)


class ElapsedClockChoiceTests(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform.startswith("linux"), "CLOCK_BOOTTIME is Linux-only"
    )
    def test_elapsed_uses_boottime_on_linux(self):
        # CLOCK_BOOTTIME keeps counting during suspend, so a resume without
        # input still reports the time away. CLOCK_MONOTONIC would reset idle
        # time on every resume and mark an away user as active.
        with patch(
            "aw_watcher_afk.unix.time.clock_gettime", return_value=123.0
        ) as clock_gettime:
            self.assertEqual(unix._elapsed(), 123.0)
        clock_gettime.assert_called_once_with(time.CLOCK_BOOTTIME)


if __name__ == "__main__":
    unittest.main()
