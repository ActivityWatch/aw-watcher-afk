import os
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from aw_watcher_afk.afk import AFKWatcher
from aw_watcher_afk.audio import (
    AudioActivityDetector,
    _has_non_monitor_stream,
    _parse_stream_targets,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
POLL_TIME = 5

MIC_STREAM = (
    "5\tmodule-null-sink.c\talsa_input.pci-0000_00_1f.3.analog-stereo\tFirefox\n"
)
PLAYBACK_STREAM = (
    "9\tmodule-always-sink.c\talsa_output.pci-0000_00_1f.3.analog-stereo\tSpotify\n"
)
MONITOR_STREAM = (
    "3\tmodule-loopback.c\t"
    "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tChromium\n"
)


class ParserTests(unittest.TestCase):
    def test_parse_targets_from_third_column(self):
        self.assertEqual(
            _parse_stream_targets(MIC_STREAM),
            ["alsa_input.pci-0000_00_1f.3.analog-stereo"],
        )

    def test_empty_output_has_no_streams(self):
        self.assertEqual(_parse_stream_targets(""), [])
        self.assertFalse(_has_non_monitor_stream(""))

    def test_non_monitor_stream_detected(self):
        self.assertTrue(_has_non_monitor_stream(MIC_STREAM))

    def test_monitor_stream_is_not_user_activity(self):
        self.assertFalse(_has_non_monitor_stream(MONITOR_STREAM))

    def test_mixed_streams_count_when_any_is_non_monitor(self):
        self.assertTrue(_has_non_monitor_stream(MONITOR_STREAM + MIC_STREAM))

    def test_short_malformed_line_counts_as_a_stream(self):
        # A line too short to parse still means some stream exists.
        self.assertTrue(_has_non_monitor_stream("7\n"))


class DetectorTests(unittest.TestCase):
    def test_unavailable_without_pactl(self):
        detector = AudioActivityDetector(pactl=None)
        self.assertFalse(detector.available())
        self.assertIsNone(detector.is_microphone_in_use())
        self.assertIsNone(detector.is_audio_playing())

    def test_microphone_in_use(self):
        detector = AudioActivityDetector(pactl="/usr/bin/pactl")
        with patch("aw_watcher_afk.audio._run_pactl", return_value=MIC_STREAM) as run:
            self.assertIs(detector.is_microphone_in_use(), True)
        self.assertEqual(run.call_args.args[1], "source-outputs")

    def test_microphone_monitor_only_is_not_in_use(self):
        detector = AudioActivityDetector(pactl="/usr/bin/pactl")
        with patch("aw_watcher_afk.audio._run_pactl", return_value=MONITOR_STREAM):
            self.assertIs(detector.is_microphone_in_use(), False)

    def test_audio_playing(self):
        detector = AudioActivityDetector(pactl="/usr/bin/pactl")
        with patch(
            "aw_watcher_afk.audio._run_pactl", return_value=PLAYBACK_STREAM
        ) as run:
            self.assertIs(detector.is_audio_playing(), True)
        self.assertEqual(run.call_args.args[1], "sink-inputs")

    def test_query_failure_is_unknown(self):
        detector = AudioActivityDetector(pactl="/usr/bin/pactl")
        with patch("aw_watcher_afk.audio._run_pactl", return_value=None):
            self.assertIsNone(detector.is_microphone_in_use())


class SteppingDatetime(datetime):
    """datetime whose now() starts at NOW and advances one poll per call."""

    calls = 0

    @classmethod
    def now(cls, tz=None):
        cls.calls += 1
        return NOW + timedelta(seconds=POLL_TIME * (cls.calls - 1))


class MicLoopTests(unittest.TestCase):
    def make_watcher(self, detect_mic=True, detect_audio_playback=False):
        watcher = object.__new__(AFKWatcher)
        watcher.settings = SimpleNamespace(
            timeout=180,
            poll_time=POLL_TIME,
            detect_mic=detect_mic,
            detect_audio_playback=detect_audio_playback,
        )
        watcher._initial_ppid = os.getppid()
        return watcher

    def run_loop(self, samples, detect_mic=True, detect_audio_playback=False):
        """Drive heartbeat_loop over (seconds_since_input, locked, mic, playing).

        Playing is only consumed when detect_audio_playback is enabled.
        """
        SteppingDatetime.calls = 0
        watcher = self.make_watcher(
            detect_mic=detect_mic, detect_audio_playback=detect_audio_playback
        )
        idle = [s[0] for s in samples] + [KeyboardInterrupt()]
        locked = [s[1] for s in samples]
        mic = [s[2] for s in samples]
        playing = [s[3] for s in samples]
        with ExitStack() as stack:
            stack.enter_context(patch("aw_watcher_afk.afk.datetime", SteppingDatetime))
            stack.enter_context(
                patch("aw_watcher_afk.afk.seconds_since_last_input", side_effect=idle)
            )
            stack.enter_context(
                patch("aw_watcher_afk.afk.is_screen_locked", side_effect=locked)
            )
            stack.enter_context(
                patch("aw_watcher_afk.afk.is_microphone_in_use", side_effect=mic)
            )
            stack.enter_context(
                patch("aw_watcher_afk.afk.is_audio_playing", side_effect=playing)
            )
            stack.enter_context(patch("aw_watcher_afk.afk.sleep"))
            ping = stack.enter_context(patch.object(watcher, "ping"))
            watcher.heartbeat_loop()
        return ping.call_args_list

    def test_mic_prevents_afk_after_idle_timeout(self):
        # Active call: no input for a long time, but the mic keeps us present.
        calls = self.run_loop([(10.0, False, True, False), (400.0, False, True, False)])

        self.assertTrue(all(not c.args[0] for c in calls))

    def test_mic_returns_from_afk_anchored_at_capture_start(self):
        # Idle timeout trips AFK, then the microphone is picked up.
        calls = self.run_loop(
            [(200.0, False, False, False), (205.0, False, True, False)]
        )

        self.assertEqual([c.args[0] for c in calls], [False, True, True, False])
        # The AFK interval must close at the moment capture started (NOW + 5s),
        # not back at last_input (NOW - 200s).
        self.assertEqual(calls[2].kwargs["timestamp"], NOW + timedelta(seconds=5))

    def test_heartbeats_while_mic_active_stay_anchored(self):
        calls = self.run_loop(
            [
                (200.0, False, False, False),
                (205.0, False, True, False),
                (210.0, False, True, False),
            ]
        )

        self.assertEqual([c.args[0] for c in calls], [False, True, True, False, False])
        # The trailing not-afk heartbeat must not go behind the transition.
        self.assertEqual(calls[4].kwargs["timestamp"], NOW + timedelta(seconds=5))

    def test_lock_overrides_mic(self):
        # Locked while the mic is in use -> stays AFK; resumes on unlock.
        calls = self.run_loop([(90.0, True, True, False), (95.0, True, True, False)])

        self.assertEqual([c.args[0] for c in calls], [False, True, True])

    def test_unlock_with_mic_resumes_at_unlock(self):
        calls = self.run_loop([(90.0, True, True, False), (0.1, False, True, False)])

        self.assertEqual([c.args[0] for c in calls], [False, True, True, False])
        # Unlock resumes presence at unlock time, not during the locked spell.
        self.assertEqual(calls[2].kwargs["timestamp"], NOW + timedelta(seconds=5))

    def test_mic_disabled_still_goes_afk(self):
        calls = self.run_loop(
            [(10.0, False, True, False), (400.0, False, True, False)],
            detect_mic=False,
        )

        self.assertEqual([c.args[0] for c in calls], [False, False, True])

    def test_audio_playback_does_not_change_afk_state(self):
        calls = self.run_loop(
            [(200.0, False, False, True)],
            detect_mic=False,
            detect_audio_playback=True,
        )

        self.assertEqual([c.args[0] for c in calls], [False, True])


if __name__ == "__main__":
    unittest.main()
