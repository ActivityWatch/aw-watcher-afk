import logging
import os
import platform
from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Optional

from aw_client import ActivityWatchClient
from aw_core.models import Event

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
    def __init__(self, config_section, timeout=None, poll_time=None):
        # Time without input before we're considering the user as AFK
        self.timeout = timeout or config_section["timeout"]
        # How often we should poll for input activity
        self.poll_time = poll_time or config_section["poll_time"]

        assert self.timeout >= self.poll_time


class AFKWatcher:
    def __init__(self, args, testing=False):
        # Read settings from config
        self.settings = Settings(
            load_config(testing), timeout=args.timeout, poll_time=args.poll_time
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

                # Screen lock means the user is away even if HID idle time is
                # low (e.g. mouse jiggle, background audio). While locked we
                # must not transition back to not-afk based on synthetic input.
                # If no longer AFK
                if afk and not locked and seconds_since_input < self.settings.timeout:
                    logger.info("No longer AFK")
                    # If the last input predates the AFK period (unlock without
                    # HID input, e.g. face/fingerprint unlock), end it at unlock
                    # detection: events starting before the AFK event would be
                    # stored out of order (see aw-watcher-afk#61).
                    afk_end = (
                        now
                        if afk_start is not None and last_input <= afk_start
                        else last_input
                    )
                    afk_start = None
                    not_afk_start = afk_end
                    self.ping(afk, timestamp=afk_end)
                    afk = False
                    # ping with timestamp+1ms with the next event (to ensure the latest event gets retrieved by get_event)
                    self.ping(afk, timestamp=afk_end + td1ms)
                # If becomes AFK
                elif not afk and (
                    seconds_since_input >= self.settings.timeout or locked
                ):
                    logger.info("Became AFK" + (" (screen locked)" if locked else ""))
                    # When the lock is the trigger and HID idle is still below
                    # the timeout, AFK starts at lock detection, not last_input,
                    # so pre-lock (unlocked) idle time isn't counted as AFK.
                    lock_triggered = (
                        locked and seconds_since_input < self.settings.timeout
                    )
                    afk_start = now if lock_triggered else last_input
                    not_afk_start = None
                    afk_duration = (
                        0.0 if lock_triggered else (now - afk_start).total_seconds()
                    )
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
                        self.ping(afk, timestamp=last_input)

                sleep(self.settings.poll_time)

            except KeyboardInterrupt:
                logger.info("aw-watcher-afk stopped by keyboard interrupt")
                break
