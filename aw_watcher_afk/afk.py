import logging
import os
import platform
from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Optional

from aw_client import ActivityWatchClient
from aw_core.models import Event

from .audio import is_audio_playing, is_microphone_in_use
from .config import load_config

system = platform.system()

if system == "Windows":
    # noreorder
    from .windows import seconds_since_last_input, is_screen_locked  # fmt: skip
elif system == "Darwin":
    # noreorder
    from .macos import seconds_since_last_input, is_screen_locked  # fmt: skip
elif system == "Linux":
    # noreorder
    from .unix import seconds_since_last_input, is_screen_locked  # fmt: skip
else:
    raise Exception(f"Unsupported platform: {system}")


logger = logging.getLogger(__name__)
td1ms = timedelta(milliseconds=1)


class Settings:
    def __init__(
        self,
        config_section,
        timeout=None,
        poll_time=None,
        detect_mic=None,
        detect_audio_playback=None,
    ):
        # Time without input before we're considering the user as AFK
        self.timeout = timeout or config_section["timeout"]
        # How often we should poll for input activity
        self.poll_time = poll_time or config_section["poll_time"]
        # Treat an active microphone (e.g. a call) as not-AFK
        self.detect_mic = (
            config_section.get("detect_mic", False)
            if detect_mic is None
            else detect_mic
        )
        # Report audio playback state in the logs (does not affect AFK state)
        self.detect_audio_playback = (
            config_section.get("detect_audio_playback", False)
            if detect_audio_playback is None
            else detect_audio_playback
        )

        assert self.timeout >= self.poll_time


class AFKWatcher:
    def __init__(self, args, testing=False):
        # Read settings from config
        self.settings = Settings(
            load_config(testing),
            timeout=args.timeout,
            poll_time=args.poll_time,
            detect_mic=args.detect_mic,
            detect_audio_playback=args.detect_audio_playback,
        )

        self.client = ActivityWatchClient(
            "aw-watcher-afk", host=args.host, port=args.port, testing=testing
        )
        self.bucketname = "{}_{}".format(
            self.client.client_name, self.client.client_hostname
        )

        # Store initial parent PID for orphan detection
        self._initial_ppid = os.getppid()

    def ping(self, afk: bool, timestamp: datetime, duration: float = 0):
        data = {"status": "afk" if afk else "not-afk"}
        e = Event(timestamp=timestamp, duration=duration, data=data)
        pulsetime = self.settings.timeout + self.settings.poll_time
        self.client.heartbeat(self.bucketname, e, pulsetime=pulsetime, queued=True)

    def run(self):
        logger.info("aw-watcher-afk started")

        # Initialization
        self.client.wait_for_start()

        eventtype = "afkstatus"
        self.client.create_bucket(self.bucketname, eventtype, queued=True)

        # Start afk checking loop
        with self.client:
            self.heartbeat_loop()

    def heartbeat_loop(self):
        afk = False
        # When the current AFK period started (set on each transition to AFK)
        afk_start: Optional[datetime] = None
        # When the current not-afk period started (set on each transition out
        # of AFK). After an unlock without HID input this is later than
        # last_input, which still predates the lock.
        not_afk_start: Optional[datetime] = None
        # When the microphone was first seen in use in the current presence
        # spell; anchors a mic-driven not-AFK transition so the whole call is
        # counted as present, not just from the last input event.
        mic_active_since: Optional[datetime] = None
        # Anchor for not-AFK heartbeats while the microphone keeps us present.
        present_anchor: Optional[datetime] = None
        # How far mic-kept presence has been reported. A later AFK interval
        # must not start before this, or it overlaps the presence event.
        present_until: Optional[datetime] = None
        # Last reported audio-playback state (None until first observed).
        playback_reported: Optional[bool] = None
        while True:
            try:
                if system in ["Darwin", "Linux"] and os.getppid() != self._initial_ppid:
                    logger.info(
                        "afkwatcher stopped because parent process died "
                        f"(ppid changed from {self._initial_ppid} to {os.getppid()})"
                    )
                    break

                now = datetime.now(timezone.utc)
                try:
                    seconds_since_input = seconds_since_last_input()
                except OSError:
                    if system != "Windows":
                        raise
                    logger.exception(
                        "seconds_since_last_input() failed; "
                        "retrying without changing AFK state"
                    )
                    sleep(self.settings.poll_time)
                    continue
                locked = is_screen_locked()
                last_input = now - timedelta(seconds=seconds_since_input)
                # An event starting before the not-afk event it follows cannot
                # merge into it and is stored separately (see aw-watcher-afk#61).
                # After an unlock without HID input, last_input still predates
                # the not-afk period, so anchor on that period's start instead.
                if not_afk_start is not None and last_input < not_afk_start:
                    last_input = not_afk_start
                logger.debug(f"Seconds since last input: {seconds_since_input}")
                logger.debug(f"Screen locked: {locked}")

                # Microphone capture (e.g. a call) is a strong signal that the
                # user is present even without keyboard/mouse input, so it can
                # extend the not-AFK state. While the screen is locked we keep
                # a confirmed locked state instead (capture may be a background
                # recording), so the signal is ignored until unlock.
                #
                mic_active = False
                if self.settings.detect_mic and not locked:
                    in_use = is_microphone_in_use()
                    if in_use:
                        if mic_active_since is None:
                            mic_active_since = now
                            logger.info("Microphone in use; treating as not-AFK")
                        mic_active = True
                    elif in_use is False:
                        # Confirmed stop — clear the anchor.
                        if mic_active_since is not None:
                            logger.info("Microphone no longer in use")
                            mic_active_since = None
                            # The call lasted until (at most) now.
                            present_until = now
                        mic_active = False
                    else:
                        # in_use is None: query failed — preserve last known state
                        # so a transient pactl timeout does not interrupt an ongoing call.
                        mic_active = mic_active_since is not None

                # Audio output is a weak signal (it may be background music),
                # so it is only reported, never used to change the AFK state.
                if self.settings.detect_audio_playback:
                    playing = is_audio_playing()
                    if (
                        playing is not None
                        and playback_reported is not None
                        and playing != playback_reported
                    ):
                        logger.info(
                            "Audio playback %s", "started" if playing else "stopped"
                        )
                    if playing is not None:
                        playback_reported = playing

                # Screen lock means the user is away even if HID idle time is
                # low (e.g. mouse jiggle, background audio). While locked we
                # must not transition back to not-afk based on synthetic input.
                # If no longer AFK
                if (
                    afk
                    and not locked
                    and (seconds_since_input < self.settings.timeout or mic_active)
                ):
                    logger.info(
                        "No longer AFK" + (" (microphone in use)" if mic_active else "")
                    )
                    if mic_active:
                        present_anchor = mic_active_since or now
                        resume_at = present_anchor
                    else:
                        # If the last input predates the AFK period (unlock without
                        # HID input, e.g. face/fingerprint unlock), end it at unlock
                        # detection: events starting before the AFK event would be
                        # stored out of order (see aw-watcher-afk#61).
                        resume_at = (
                            now
                            if afk_start is not None and last_input <= afk_start
                            else last_input
                        )
                        present_anchor = None
                        present_until = None
                    afk_start = None
                    not_afk_start = resume_at
                    self.ping(afk, timestamp=resume_at)
                    afk = False
                    # ping with timestamp+1ms with the next event (to ensure the latest event gets retrieved by get_event)
                    self.ping(afk, timestamp=resume_at + td1ms)
                # If becomes AFK
                elif not afk and (
                    locked
                    or (seconds_since_input >= self.settings.timeout and not mic_active)
                ):
                    # A locked state (or idle AFK period) ends the presence
                    # spell; the mic anchor must not survive it, or a later
                    # unlock would back-date presence into the AFK interval.
                    logger.info("Became AFK" + (" (screen locked)" if locked else ""))
                    # When the lock is the trigger and HID idle is still below
                    # the timeout, AFK starts at lock detection, not last_input,
                    # so pre-lock (unlocked) idle time isn't counted as AFK.
                    lock_triggered = (
                        locked and seconds_since_input < self.settings.timeout
                    )
                    if lock_triggered:
                        afk_start = now
                    else:
                        # last_input predates a mic-kept presence spell; start
                        # AFK where that spell's reported presence ended so the
                        # two events don't overlap (see aw-watcher-afk#61).
                        afk_start = max(last_input, present_until or last_input)
                    present_anchor = None
                    present_until = None
                    mic_active_since = None
                    not_afk_start = None
                    afk_duration = (now - afk_start).total_seconds()
                    self.ping(afk, timestamp=afk_start)
                    afk = True
                    # ping with timestamp+1ms with the next event (to ensure the latest event gets retrieved by get_event)
                    self.ping(afk, timestamp=afk_start + td1ms, duration=afk_duration)
                # Send a heartbeat if no state change was made
                else:
                    if afk:
                        # we need the +1ms here too, to make sure we don't "miss" the last heartbeat
                        # (if last_input hasn't changed)
                        # Anchor on the AFK start, not last_input: after a
                        # lock-triggered transition last_input predates the
                        # lock, and an earlier-starting heartbeat wouldn't
                        # merge into the AFK event but be stored separately.
                        start = afk_start or last_input
                        self.ping(
                            afk,
                            timestamp=start + td1ms,
                            duration=(now - start).total_seconds(),
                        )
                    else:
                        start = last_input
                        if mic_active:
                            # Bootstrap the anchor when the mic was already
                            # active at watcher start (no AFK->not-AFK
                            # transition set it), so the heartbeat isn't
                            # back-dated to a last_input far in the past.
                            if present_anchor is None:
                                present_anchor = mic_active_since or now
                            start = max(start, present_anchor)
                            # The mic is evidence of presence up to now, so
                            # extend the event over the ongoing call.
                            present_until = now
                            self.ping(
                                afk,
                                timestamp=start,
                                duration=(now - start).total_seconds(),
                            )
                        else:
                            # Without mic evidence, presence ends at the last
                            # input: a zero-duration heartbeat, as on master.
                            if present_anchor is not None:
                                start = max(start, present_anchor)
                            self.ping(afk, timestamp=start)

                sleep(self.settings.poll_time)

            except KeyboardInterrupt:
                logger.info("aw-watcher-afk stopped by keyboard interrupt")
                break
