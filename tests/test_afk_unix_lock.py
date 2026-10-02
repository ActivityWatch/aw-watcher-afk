import subprocess
import unittest
from unittest.mock import patch

from aw_watcher_afk import unix


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class UnixScreenLockTests(unittest.TestCase):
    def setUp(self):
        unix._loginctl_available = True
        unix._last_locked = False
        unix._consecutive_failures = 0
        unix._warned_persistent_failure = False

    def tearDown(self):
        unix._loginctl_available = True
        unix._last_locked = False
        unix._consecutive_failures = 0
        unix._warned_persistent_failure = False

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

    def test_loginctl_error_is_unlocked(self):
        # e.g. "Caller does not belong to any known session"
        failed = completed(returncode=1, stderr="Failed to get path for session")
        with patch("aw_watcher_afk.unix.subprocess.run", return_value=failed):
            self.assertFalse(unix.is_screen_locked())
        self.assertTrue(unix._loginctl_available)

    def test_timeout_is_unlocked(self):
        with patch(
            "aw_watcher_afk.unix.subprocess.run",
            side_effect=subprocess.TimeoutExpired("loginctl", 2),
        ):
            self.assertFalse(unix.is_screen_locked())

    def test_failure_while_locked_keeps_locked(self):
        failed = completed(returncode=1, stderr="Failed to get path for session")
        with patch(
            "aw_watcher_afk.unix.subprocess.run",
            side_effect=[
                completed("yes\n"),
                failed,
                subprocess.TimeoutExpired("loginctl", 2),
                completed("no\n"),
            ],
        ):
            self.assertEqual(
                [unix.is_screen_locked() for _ in range(4)], [True, True, True, False]
            )

    def test_persistent_failure_while_locked_keeps_locked(self):
        # A confirmed lock must survive sustained query failures: returning
        # False would let a failure read as an unlock and could split the
        # locked AFK interval. Recovery only happens on a successful query.
        failed = completed(returncode=1, stderr="Failed to get path for session")
        with patch(
            "aw_watcher_afk.unix.subprocess.run",
            side_effect=[
                completed("yes\n"),
                failed,
                failed,
                failed,
                failed,
                completed("no\n"),
            ],
        ):
            self.assertEqual(
                [unix.is_screen_locked() for _ in range(6)],
                [True, True, True, True, True, False],
            )

    def test_success_resets_failure_counter(self):
        # Intermittent failures must not accumulate across successful queries.
        failed = completed(returncode=1, stderr="Failed to get path for session")
        with patch(
            "aw_watcher_afk.unix.subprocess.run",
            side_effect=[
                completed("yes\n"),
                failed,
                completed("yes\n"),
                failed,
                failed,
                failed,
                failed,
            ],
        ):
            self.assertEqual(
                [unix.is_screen_locked() for _ in range(7)],
                [True, True, True, True, True, True, True],
            )

    def test_persistent_failures_warn_once(self):
        # A broken logind must not produce a warning on every poll.
        failed = completed(returncode=1, stderr="Failed to get path for session")
        with (
            patch("aw_watcher_afk.unix.subprocess.run", return_value=failed),
            self.assertLogs("aw_watcher_afk.unix", level="WARNING") as cm,
        ):
            for _ in range(10):
                unix.is_screen_locked()
        self.assertEqual(len(cm.output), 1)
        self.assertIn("keeping the last confirmed screen-lock state", cm.output[0])

    def test_persistent_failure_after_unlock_stays_unlocked(self):
        # Failures never synthesise a lock either: the last confirmed state is
        # returned, so an unlocked user is not reported AFK.
        failed = completed(returncode=1, stderr="Failed to get path for session")
        with patch(
            "aw_watcher_afk.unix.subprocess.run",
            side_effect=[completed("no\n")] + [failed] * 5,
        ):
            self.assertEqual(
                [unix.is_screen_locked() for _ in range(6)],
                [False, False, False, False, False, False],
            )

    def test_missing_loginctl_disables_further_checks(self):
        with patch(
            "aw_watcher_afk.unix.subprocess.run", side_effect=FileNotFoundError
        ) as run:
            self.assertFalse(unix.is_screen_locked())
            self.assertFalse(unix.is_screen_locked())
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
