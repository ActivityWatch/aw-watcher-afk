import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from aw_watcher_afk import windows
from aw_watcher_afk.afk import AFKWatcher


class WindowsIdleQueryTests(unittest.TestCase):
    def test_get_last_input_failure_raises(self):
        with patch.object(
            windows.ctypes, "WINFUNCTYPE", create=True
        ) as prototype_factory:
            with patch.object(windows.ctypes, "windll", create=True):
                prototype_factory.return_value.return_value.return_value = 0

                with self.assertRaisesRegex(OSError, "GetLastInputInfo failed"):
                    windows._getLastInputTick()


class HeartbeatFailureTests(unittest.TestCase):
    def make_watcher(self):
        watcher = object.__new__(AFKWatcher)
        watcher.settings = SimpleNamespace(timeout=10, poll_time=5)
        watcher._initial_ppid = os.getppid()
        return watcher

    def run_loop(self, watcher, samples, system_name="Windows"):
        with ExitStack() as stack:
            stack.enter_context(patch("aw_watcher_afk.afk.system", system_name))
            stack.enter_context(
                patch(
                    "aw_watcher_afk.afk.seconds_since_last_input",
                    side_effect=samples,
                )
            )
            ping = stack.enter_context(patch.object(watcher, "ping"))
            sleep = stack.enter_context(patch("aw_watcher_afk.afk.sleep"))
            log_exception = stack.enter_context(
                patch("aw_watcher_afk.afk.logger.exception")
            )
            watcher.heartbeat_loop()
        return ping, sleep, log_exception

    def test_failed_sample_preserves_afk_state_and_recovers(self):
        watcher = self.make_watcher()
        samples = [20.0, OSError("idle API unavailable"), 20.0, KeyboardInterrupt()]

        ping, sleep, log_exception = self.run_loop(watcher, samples)

        self.assertEqual(
            [record.args[0] for record in ping.call_args_list],
            [False, True, True],
        )
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual(log_exception.call_count, 1)

    def test_repeated_failures_sleep_without_emitting_heartbeats(self):
        watcher = self.make_watcher()
        samples = [
            OSError("idle API unavailable"),
            OSError("idle API unavailable"),
            KeyboardInterrupt(),
        ]

        ping, sleep, log_exception = self.run_loop(watcher, samples)

        ping.assert_not_called()
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(log_exception.call_count, 2)

    def test_non_windows_failure_reaches_supervisor(self):
        watcher = self.make_watcher()

        with self.assertRaisesRegex(OSError, "listener failed"):
            self.run_loop(watcher, [OSError("listener failed")], system_name="Linux")


if __name__ == "__main__":
    unittest.main()


class WindowsIdleTimeTests(unittest.TestCase):
    def idle(self, tick, last_input):
        with patch.object(windows, "_getTickCount64", return_value=tick):
            with patch.object(windows, "_getLastInputTick", return_value=last_input):
                return windows.seconds_since_last_input()

    def test_normal_idle(self):
        self.assertEqual(self.idle(5000, 3000), 2.0)

    def test_tick_wraparound(self):
        self.assertAlmostEqual(self.idle(2**32 + 25, 2**32 - 25), 0.05)

    def test_last_input_ahead_of_tick_is_fresh_input_not_49_days(self):
        # Input landing on the next ~15.6 ms tick between the two reads puts
        # dwTime 16 ms ahead of the sampled tick.
        self.assertEqual(self.idle(1_000_000, 1_000_016), 0.0)

    def test_last_input_ahead_of_tick_across_wraparound(self):
        self.assertEqual(self.idle(2**32 - 5, 10), 0.0)

    def test_last_input_read_before_tick(self):
        calls = []

        def last_input():
            calls.append("last")
            return 0

        def tick():
            calls.append("tick")
            return 0

        with patch.object(windows, "_getLastInputTick", side_effect=last_input):
            with patch.object(windows, "_getTickCount64", side_effect=tick):
                windows.seconds_since_last_input()
        self.assertEqual(calls, ["last", "tick"])
