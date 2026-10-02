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

# Real ``pactl list short source-outputs`` layout:
#   <stream-index>  <driver>  <client-index(numeric)>  <source-name>  ...
# Column 2 is a numeric client id; column 3 is the source/sink device name.
MIC_STREAM = (
    "5\tmodule-null-sink.c\t22\talsa_input.pci-0000_00_1f.3.analog-stereo\n"
)
PLAYBACK_STREAM = (
    "9\tmodule-always-sink.c\t33\talsa_output.pci-0000_00_1f.3.analog-stereo\n"
)
MONITOR_STREAM = (
    "3\tmodule-loopback.c\t8\t"
    "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor\n"
)


class ParserTests(unittest.TestCase):
    def test_parse_targets_from_fourth_column(self):
        # Column 3 (0-indexed) is the source/sink name; column 2 is numeric client id.
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

    def test_heartbeat_not_backdated_when_mic_active_from_first_poll(self):
        # When the watcher starts not-AFK and the mic is already active (no
        # prior AFK->not-AFK transition that would set present_anchor), the
        # not-AFK heartbeat must not timestamp at last_input (seconds_since_input
        # in the past) but at mic_active_since (first seen active).
        # Regression: without the fix, poll 2 would emit timestamp=NOW+5s-400s.
        calls = self.run_loop([(10.0, False, True, False), (400.0, False, True, False)])
        # Second heartbeat must not predate the first poll (NOW).
        self.assertGreaterEqual(calls[1].kwargs["timestamp"], NOW)

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
        # The heartbeat must carry a positive duration so the AW event covers
        # the ongoing call, not just a zero-duration point at the mic anchor.
        self.assertGreater(calls[4].kwargs.get("duration", 0), 0)

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

    def test_query_failure_preserves_mic_presence(self):
        # A failed pactl query (None) must not interrupt an active call.
        # The watcher must stay not-AFK even when one poll returns None.
        calls = self.run_loop(
            [
                (200.0, False, False, False),  # idle -> AFK
                (205.0, False, True, False),   # mic starts -> resume
                (210.0, False, None, False),   # query fails -> stays not-AFK
            ]
        )
        # No second AFK event should fire at t=10.
        self.assertEqual([c.args[0] for c in calls], [False, True, True, False, False])
        self.assertFalse(calls[-1].args[0])

    def test_afk_start_anchored_at_now_when_call_ends_while_idle(self):
        # When the mic ends after the idle timeout has already passed, the new
        # AFK interval must start at detection time (NOW+10s), not at
        # last_input (NOW-200s), which would overlap the call's presence event.
        calls = self.run_loop(
            [
                (200.0, False, False, False),  # t=0: idle -> AFK
                (205.0, False, True, False),   # t=5: mic starts -> resume at t5
                (210.0, False, False, False),  # t=10: mic ends, still idle -> AFK
            ]
        )
        self.assertEqual(
            [c.args[0] for c in calls], [False, True, True, False, False, True]
        )
        # The second AFK transition (calls[5]) must anchor at NOW+10s, not at
        # last_input which predates the call.
        self.assertGreaterEqual(
            calls[5].kwargs["timestamp"],
            NOW + timedelta(seconds=10),
        )

    def assert_events_do_not_overlap(self, calls):
        # Replay the pings through aw-server's heartbeat merge and check that
        # the stored events are ordered and disjoint (see aw-watcher-afk#61).
        pulsetime = timedelta(seconds=180 + POLL_TIME)
        events = []  # [afk, start, end]
        for c in calls:
            afk, ts = c.args[0], c.kwargs["timestamp"]
            end = ts + timedelta(seconds=c.kwargs.get("duration", 0))
            last = events[-1] if events else None
            if last and last[0] == afk and last[1] <= ts <= last[2] + pulsetime:
                last[2] = max(last[2], end)
            else:
                events.append([afk, ts, end])
        for prev, nxt in zip(events, events[1:]):
            self.assertGreaterEqual(nxt[1], prev[2], f"{prev} overlaps {nxt}")

    def test_idle_timeout_does_not_overlap_presence(self):
        # Default config (no mic): not-AFK heartbeats must stay at last_input,
        # or the not-AFK event extends past the AFK start at last_input.
        samples = [(10.0 + POLL_TIME * k, False, None, False) for k in range(36)]
        calls = self.run_loop(samples, detect_mic=False)

        self.assertTrue(calls[-1].args[0])
        self.assert_events_do_not_overlap(calls)

    def test_call_ending_before_timeout_does_not_overlap_later_afk(self):
        # Mic stops while idle is still below the timeout; AFK trips later.
        # The AFK interval must start after the call's presence, not at
        # last_input (which predates the call).
        samples = [(10.0, False, True, False)] + [
            (10.0 + POLL_TIME * k, False, False, False) for k in range(1, 36)
        ]
        calls = self.run_loop(samples)

        self.assertTrue(calls[-1].args[0])
        self.assert_events_do_not_overlap(calls)
        # AFK starts where the call was seen to end (t=5s).
        self.assertEqual(
            calls[-1].kwargs["timestamp"],
            NOW + timedelta(seconds=5, milliseconds=1),
        )

    def test_mic_sequences_do_not_overlap(self):
        for samples in (
            [(200.0, False, False, False), (205.0, False, True, False), (210.0, False, False, False)],
            [(10.0, False, True, False), (400.0, False, True, False), (405.0, False, False, False)],
            [(10.0, False, True, False), (15.0, True, None, False), (400.0, True, None, False)],
        ):
            with self.subTest(samples=samples):
                self.assert_events_do_not_overlap(self.run_loop(samples))


if __name__ == "__main__":
    unittest.main()
