import logging
import platform
from datetime import datetime, timedelta, timezone
from time import sleep
import os

from aw_core.models import Event
from aw_client import ActivityWatchClient

from .config import watcher_config

system = platform.system()

if system == "Windows":
    from .windows import seconds_since_last_input
elif system == "Darwin":
    from .macos import seconds_since_last_input
elif system == "Linux":
    from .unix import seconds_since_last_input
else:
    raise Exception("Unsupported platform: {}".format(system))


logger = logging.getLogger(__name__)


class Settings:
    def __init__(self, config_section):
        # Time without input before we're considering the user as AFK
        self.timeout = config_section.getfloat("timeout")
        # How often we should poll for input activity
        self.poll_time = config_section.getfloat("poll_time")

        assert self.timeout >= self.poll_time


class AFKWatcher:
    def __init__(self, testing=False):
        # Read settings from config
        configsection = "aw-watcher-afk" if not testing else "aw-watcher-afk-testing"
        self.settings = Settings(watcher_config[configsection])

        self.client = ActivityWatchClient("aw-watcher-afk", testing=testing)
        self.bucketname = "{}_{}".format(self.client.client_name, self.client.client_hostname)

    def ping(self, afk: bool, timestamp: datetime, duration: float = 0):
        data = {"status": "afk" if afk else "not-afk"}
        e = Event(timestamp=timestamp, duration=duration, data=data)
        pulsetime = self.settings.timeout + self.settings.poll_time
        self.client.heartbeat(self.bucketname, e, pulsetime=pulsetime, queued=True)

    def run(self):
        logger.info("aw-watcher-afk started")

        # Initialization
        sleep(1)

        eventtype = "afkstatus"
        self.client.create_bucket(self.bucketname, eventtype, queued=True)

        # Start afk checking loop
        with self.client:
            self.heartbeat_loop()

    def heartbeat_loop(self):
        afk = False
        while True:
            try:
                if system in ["Darwin", "Linux"] and os.getppid() == 1:
                    # TODO: This won't work with PyInstaller which starts a bootloader process which will become the parent.
                    #       There is a solution however.
                    #       See: https://github.com/ActivityWatch/aw-qt/issues/19#issuecomment-316741125
                    logger.info("afkwatcher stopped because parent process died")
                    break

                now = datetime.now(timezone.utc)
                seconds_since_input = seconds_since_last_input()
                last_input = now - timedelta(seconds=seconds_since_input)
                logger.debug("Seconds since last input: {}".format(seconds_since_input))

                # If no longer AFK
                if afk and seconds_since_input < self.settings.timeout:
                    logger.info("No longer AFK")
                    self.ping(afk, timestamp=last_input)
                    afk = False
                    self.ping(afk, timestamp=last_input)
                # If becomes AFK
                elif not afk and seconds_since_input >= self.settings.timeout:
                    logger.info("Became AFK")
                    self.ping(afk, timestamp=last_input)
                    afk = True
                    self.ping(afk, timestamp=last_input, duration=seconds_since_input)
                # Send a heartbeat if no state change was made
                else:
                    if afk:
                        self.ping(afk, timestamp=last_input, duration=seconds_since_input)
                    else:
                        self.ping(afk, timestamp=last_input)

                sleep(self.settings.poll_time)

            except KeyboardInterrupt:
                logger.info("aw-watcher-afk stopped by keyboard interrupt")
                break
