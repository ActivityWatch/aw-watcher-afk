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
    from .windows import seconds_since_last_input as _seconds_since_last_input_winfail
elif system in ["Darwin", "Linux"]:
    from .unix import seconds_since_last_input as _seconds_since_last_input_unix

logger = logging.getLogger(__name__)


class Settings:
    def __init__(self, config_section):
        self.timeout = config_section.getfloat("timeout")
        self.update_interval = config_section.getfloat("update_interval")
        self.check_interval = config_section.getfloat("check_interval")
        # TODO: This is a better name for whichever variable above is this one
        self.polling_interval = 1


def get_seconds_since_last_input():
    if system in ["Darwin", "Linux"]:
        return _seconds_since_last_input_unix()
    elif system == "Windows":
        return _seconds_since_last_input_winfail()
    else:
        raise Exception("unknown platform")


class AFKWatcher:
    def __init__(self, testing=False, settings=None):
        # Read settings from config
        configsection = "aw-watcher-afk" if not testing else "aw-watcher-afk-testing"
        self.settings = Settings(watcher_config[configsection])

        self.client = ActivityWatchClient("aw-watcher-afk", testing=testing)
        self.bucketname = "{}_{}".format(self.client.client_name, self.client.client_hostname)

        eventtype = "afkstatus"
        self.client.setup_bucket(self.bucketname, eventtype)
        self.client.connect()

    def ping(self, afk, timestamp=None, duration=0):
        data = {"status": "afk" if afk else "not-afk"}
        if timestamp is None:
            timestamp = self.now
        e = Event(timestamp=self.now, duration=duration, data=data)
        self.client.heartbeat(self.bucketname, e, pulsetime=self.settings.timeout, queued=True)

    def run(self):
        logger.info("afkwatcher started")

        """ Initialization """
        sleep(1)

        """ Init variables """
        self.afk = False
        self.now = datetime.now(timezone.utc)

        """ Start afk checking loop """
        while True:
            try:
                if system in ["Darwin", "Linux"]:
                    if os.getppid() == 1:
                        # TODO: This won't work with PyInstaller which starts a bootloader process which will become the parent.
                        #       There is a solution however.
                        #       See: https://github.com/ActivityWatch/aw-qt/issues/19#issuecomment-316741125
                        logger.info("afkwatcher stopped because parent process died")
                        break

                self.now = datetime.now(timezone.utc)
                seconds_since_last_input = get_seconds_since_last_input()
                logger.debug("Seconds since last input: {}".format(seconds_since_last_input))

                # If no longer AFK
                if self.afk and seconds_since_last_input < self.settings.timeout:
                    logger.info("No longer AFK")
                    self.ping(self.afk)  # End afk period
                    self.afk = False
                    self.ping(self.afk)
                # If becomes AFK
                elif not self.afk and seconds_since_last_input >= self.settings.timeout:
                    logger.info("Became AFK")
                    self.afk = True
                    last_input = self.now - self.timedelta_since_last_input
                    self.ping(self.afk, timestamp=last_input, duration=seconds_since_last_input)
                # Send a heartbeat if no state change was made
                else:
                    self.ping(self.afk)

                sleep(self.settings.polling_interval)

            except KeyboardInterrupt:
                logger.info("afkwatcher stopped by keyboard interrupt")
                break
