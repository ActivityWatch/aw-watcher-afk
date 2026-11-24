"""Idle time on Linux must measure elapsed time, not wall-clock differences.

Before this fix, ``unix.py`` took ``last_activity`` and ``now`` from
``datetime.now()``, so a DST change (or NTP step, or manual clock change)
shifted idle time by an hour. The tests below pin idle time to the elapsed
clock, and pin which listeners get restarted when one of them dies.

Written with ``unittest`` so the existing ``make test`` discovery pattern
(``test_afk_*.py``) picks it up in CI.
"""

import unittest
from unittest.mock import patch

from aw_watcher_afk import unix


class FakeElapsedClock:
    """A controllable elapsed-time clock, in seconds."""

    def __init__(self):
        self.elapsed = 1000.0

    def advance(self, seconds):
        self.elapsed += seconds


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

    def test_dst_fall_back_does_not_give_negative_idle(self):
        # 5 s pass while the local wall clock falls back one hour. Idle time
        # must follow the elapsed clock, so it stays 5 s (the old wall-clock
        # arithmetic reported -3595 s and delayed AFK detection by an hour).
        watcher = unix.LastInputUnix()
        self.clock.advance(5)
        self.assertAlmostEqual(watcher.seconds_since_last_input(), 5.0)

    def test_dst_spring_forward_does_not_add_an_hour_of_idle(self):
        # 5 s pass while the local wall clock jumps forward one hour: the hour
        # that was actually worked must not be backdated as AFK.
        watcher = unix.LastInputUnix()
        self.clock.advance(5)
        self.assertAlmostEqual(watcher.seconds_since_last_input(), 5.0)

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


if __name__ == "__main__":
    unittest.main()
