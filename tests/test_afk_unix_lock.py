import subprocess
import unittest
from unittest.mock import patch

from aw_watcher_afk import unix


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


FAILED = completed(returncode=1, stderr="Failed to get path for session")
TIMEOUT = subprocess.TimeoutExpired("loginctl", 2)


class UnixScreenLockTests(unittest.TestCase):
    def setUp(self):
        self._reset()

    def tearDown(self):
        self._reset()

    @staticmethod
    def _reset():
        unix._loginctl_available = True
        unix._last_locked = False
        unix._failing_since = None

    def _run_at(self, outcomes_by_time):
        """Call is_screen_locked() once per (time, outcome) pair, return results."""
        results = []
        for now, outcome in outcomes_by_time:
            with patch("aw_watcher_afk.unix.monotonic", return_value=now), patch(
                "aw_watcher_afk.unix.subprocess.run", side_effect=[outcome]
            ):
                results.append(unix.is_screen_locked())
        return results

    def test_locked_hint_yes_is_locked(self):
        with patch(
            "aw_watcher_afk.unix.subprocess.run", return_value=completed("yes\n")
        ):
            self.assertTrue(unix.is_screen_locked())

    def test_locked_hint_no_is_unlocked(self):
        with patch(
            "aw_watcher_afk.unix.subprocess.run", return_value=completed("no\n")
        ):
            self.assertFalse(unix.is_screen_locked())

    def test_uses_xdg_session_id(self):
        with patch.dict("os.environ", {"XDG_SESSION_ID": "c2"}), patch(
            "aw_watcher_afk.unix.subprocess.run", return_value=completed("no\n")
        ) as run:
            unix.is_screen_locked()
        self.assertEqual(
            run.call_args.args[0],
            ["loginctl", "show-session", "c2", "-p", "LockedHint", "--value"],
        )

    def test_falls_back_to_auto_session(self):
        with patch.dict("os.environ", {}, clear=True), patch(
            "aw_watcher_afk.unix.subprocess.run", return_value=completed("no\n")
        ) as run:
            unix.is_screen_locked()
        self.assertEqual(run.call_args.args[0][2], "auto")

    def test_loginctl_error_with_no_prior_state_is_unlocked(self):
        # e.g. "Caller does not belong to any known session"
        with patch("aw_watcher_afk.unix.subprocess.run", return_value=FAILED):
            self.assertFalse(unix.is_screen_locked())
        self.assertTrue(unix._loginctl_available)

    def test_timeout_with_no_prior_state_is_unlocked(self):
        with patch("aw_watcher_afk.unix.subprocess.run", side_effect=TIMEOUT):
            self.assertFalse(unix.is_screen_locked())

    def test_failure_while_locked_keeps_locked(self):
        # Brief failures (error exit or timeout) must not read as an unlock.
        results = self._run_at(
            [
                (0, completed("yes\n")),
                (5, FAILED),
                (10, TIMEOUT),
                (15, completed("no\n")),
            ]
        )
        self.assertEqual(results, [True, True, True, False])

    def test_sustained_failure_while_locked_falls_back_to_unlocked(self):
        # A confirmed lock that can't be re-confirmed for the trust window must
        # not pin the watcher AFK after the user has unlocked.
        limit = unix._LOCK_STATE_TRUST_SECONDS
        with self.assertLogs("aw_watcher_afk.unix", level="WARNING") as cm:
            results = self._run_at(
                [
                    (0, completed("yes\n")),
                    (10, FAILED),
                    (10 + limit - 1, FAILED),
                    (10 + limit, FAILED),
                    (10 + limit + 5, FAILED),
                ]
            )
        self.assertEqual(results, [True, True, True, False, False])
        self.assertEqual(len(cm.output), 1)
        self.assertIn("no longer trusting", cm.output[0])

    def test_success_after_sustained_failure_recovers(self):
        limit = unix._LOCK_STATE_TRUST_SECONDS
        with self.assertLogs("aw_watcher_afk.unix", level="WARNING"):
            results = self._run_at(
                [
                    (0, completed("yes\n")),
                    (10, FAILED),
                    (10 + limit, FAILED),
                    (10 + limit + 5, completed("yes\n")),
                ]
            )
        # Locked again once loginctl answers, and the failure streak is reset.
        self.assertEqual(results, [True, True, False, True])
        self.assertIsNone(unix._failing_since)

    def test_success_resets_failure_window(self):
        # Intermittent failures must not accumulate across successful queries.
        limit = unix._LOCK_STATE_TRUST_SECONDS
        results = self._run_at(
            [
                (0, completed("yes\n")),
                (10, FAILED),
                (20, completed("yes\n")),
                (30, FAILED),
                (30 + limit - 1, FAILED),
            ]
        )
        self.assertEqual(results, [True] * 5)

    def test_failures_after_unlock_stay_unlocked(self):
        # Failures never synthesise a lock either: an unlocked user is not
        # reported AFK, however long loginctl keeps failing.
        results = self._run_at(
            [(0, completed("no\n"))] + [(t, FAILED) for t in (10, 400, 800)]
        )
        self.assertEqual(results, [False] * 4)

    def test_missing_loginctl_disables_further_checks(self):
        with patch(
            "aw_watcher_afk.unix.subprocess.run", side_effect=FileNotFoundError
        ) as run:
            self.assertFalse(unix.is_screen_locked())
            self.assertFalse(unix.is_screen_locked())
        self.assertEqual(run.call_count, 1)

    def test_missing_loginctl_does_not_keep_a_stale_lock(self):
        unix._last_locked = True
        with patch("aw_watcher_afk.unix.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(unix.is_screen_locked())
        self.assertFalse(unix.is_screen_locked())


if __name__ == "__main__":
    unittest.main()
