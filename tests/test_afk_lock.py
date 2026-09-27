import os
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from aw_watcher_afk.afk import AFKWatcher

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
POLL_TIME = 5


class SteppingDatetime(datetime):
    """datetime whose now() starts at NOW and advances one poll per call."""

    calls = 0

    @classmethod
    def now(cls, tz=None):
        cls.calls += 1
        return NOW + timedelta(seconds=POLL_TIME * (cls.calls - 1))


class ScreenLockTests(unittest.TestCase):
    def make_watcher(self):
        watcher = object.__new__(AFKWatcher)
        watcher.settings = SimpleNamespace(timeout=180, poll_time=POLL_TIME)
        watcher._initial_ppid = os.getppid()
        return watcher

    def run_loop(self, samples):
        """Drive heartbeat_loop over (seconds_since_input, locked) samples.

        The clock starts at NOW and advances POLL_TIME seconds per sample.
        """
        SteppingDatetime.calls = 0
        watcher = self.make_watcher()
        idle = [s[0] for s in samples] + [KeyboardInterrupt()]
        locked = [s[1] for s in samples]
        with ExitStack() as stack:
            stack.enter_context(patch("aw_watcher_afk.afk.datetime", SteppingDatetime))
            stack.enter_context(
                patch("aw_watcher_afk.afk.seconds_since_last_input", side_effect=idle)
            )
            stack.enter_context(
                patch("aw_watcher_afk.afk.is_screen_locked", side_effect=locked)
            )
            stack.enter_context(patch("aw_watcher_afk.afk.sleep"))
            ping = stack.enter_context(patch.object(watcher, "ping"))
            watcher.heartbeat_loop()
        return ping.call_args_list

    def test_lock_below_timeout_becomes_afk_at_lock_detection(self):
        calls = self.run_loop([(90.0, True)])

        self.assertEqual([c.args[0] for c in calls], [False, True])
        # Pre-lock idle time stays not-afk: the transition starts at `now`,
        # not at last_input (90s earlier).
        self.assertEqual(calls[0].kwargs["timestamp"], NOW)
        self.assertEqual(calls[1].kwargs["timestamp"], NOW + timedelta(milliseconds=1))
        self.assertEqual(calls[1].kwargs["duration"], 0.0)

    def test_heartbeats_while_locked_stay_anchored_at_lock_detection(self):
        # Locked after 90s of idle, then no input (idle keeps growing) and
        # then a mouse jiggle while still locked.
        calls = self.run_loop([(90.0, True), (95.0, True), (100.0, True), (0.1, True)])

        afk_pings = [c for c in calls if c.args[0]]
        self.assertEqual(len(afk_pings), 4)
        # A heartbeat starting before the transition event wouldn't merge into
        # it, so it would label the pre-lock idle time as AFK again.
        for c in afk_pings:
            self.assertEqual(c.kwargs["timestamp"], NOW + timedelta(milliseconds=1))
        self.assertEqual(
            [c.kwargs["duration"] for c in afk_pings], [0.0, 5.0, 10.0, 15.0]
        )

    def test_input_while_locked_does_not_leave_afk(self):
        calls = self.run_loop([(0.5, True), (0.1, True), (0.1, True)])

        self.assertEqual([c.args[0] for c in calls], [False, True, True, True])

    def test_unlock_with_input_leaves_afk(self):
        calls = self.run_loop([(0.5, True), (0.1, False)])

        self.assertEqual([c.args[0] for c in calls], [False, True, True, False])

    def test_idle_timeout_still_starts_afk_at_last_input(self):
        calls = self.run_loop([(200.0, False)])

        last_input = NOW - timedelta(seconds=200)
        self.assertEqual([c.args[0] for c in calls], [False, True])
        self.assertEqual(calls[0].kwargs["timestamp"], last_input)
        self.assertEqual(
            calls[1].kwargs["timestamp"], last_input + timedelta(milliseconds=1)
        )
        self.assertEqual(calls[1].kwargs["duration"], 200.0)


if __name__ == "__main__":
    unittest.main()
