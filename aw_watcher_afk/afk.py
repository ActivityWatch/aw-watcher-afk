import logging
import platform
from datetime import datetime, timedelta, timezone
from time import sleep

from aw_core.models import Event
from aw_client import ActivityWatchClient

from .config import watcher_config

if platform.system() == "Windows":
    from .windows import seconds_since_last_input as _seconds_since_last_input_winfail
elif platform.system() in ["Darwin", "Linux"]:
    from .unix import seconds_since_last_input as _seconds_since_last_input_unix


class Settings:
    def __init__(self, config_section):
        self.timeout = config_section.getfloat("timeout")
        self.update_interval = config_section.getfloat("update_interval")
        self.check_interval = config_section.getfloat("check_interval")
        # TODO: This is a better name for whichever variable above is this one
        self.polling_interval = 1


def get_seconds_since_last_input():
    system = platform.system()
    if system in ["Darwin", "Linux"]:
        return _seconds_since_last_input_unix()
    elif system == "Windows":
        return _seconds_since_last_input_winfail()
    else:
        raise Exception("unknown platform")


class AFKWatcher:
    def __init__(self, testing=False, settings=None):
        self.logger = logging.getLogger("aw.watcher.afk")

        # Read settings from config
        configsection = "aw-watcher-afk" if not testing else "aw-watcher-afk-testing"
        self.settings = Settings(watcher_config[configsection])

        self.client = ActivityWatchClient("aw-watcher-afk", testing=testing)
        self.bucketname = "{}_{}".format(self.client.client_name, self.client.client_hostname)

        eventtype = "afkstatus"
        self.client.setup_bucket(self.bucketname, eventtype)
        self.client.connect()

    def set_state(self, status, duration, timestamp=None):
        data = {"status": status}
        if timestamp == None:
            timestamp = self.now
        e = Event(data=data, timestamp=timestamp, duration=duration)
        self.client.send_event(self.bucketname, e)

    def ping(self, afk):
        data = {"status": "afk" if afk else "not-afk"}
        e = Event(data=data, timestamp=self.now)
        self.client.heartbeat(self.bucketname, e, pulsetime=self.settings.timeout)

    def run(self):
        # TODO: All usage of last_input can probably be replaced the self.seconds_since_last_input equivalent

        self.logger.info("afkwatcher started")

        """ Initialization """
        sleep(1)

        """ Init variables """
        self.afk = False
        self.now = datetime.now(timezone.utc)
        self.last_check = self.now
        self.seconds_since_last_input = 0

        """ Start afk checking loop """
        while True:
            try:
                self.last_check = self.now
                self.now = datetime.now(timezone.utc)

                self.seconds_since_last_input = get_seconds_since_last_input()
                self.timedelta_since_last_input = timedelta(seconds=self.seconds_since_last_input)
                self.last_input = self.now - self.timedelta_since_last_input
                self.logger.debug("Time since last input: {}".format(self.timedelta_since_last_input))

                # If program is not allowed to run for more than polling_interval+10s it will assume that the computer has gone into suspend/hibernation
                if self.now > self.last_check + timedelta(seconds=10 + self.settings.polling_interval):
                    self.logger.debug("Woke up from suspend/hibernation")
                    time_since_last_check = self.now - self.last_check
                    self.set_state("hibernating", timedelta(seconds=time_since_last_check.total_seconds()), self.last_check)
                # If no longer AFK
                elif self.afk and self.seconds_since_last_input < self.settings.timeout:
                    self.logger.info("No longer AFK")
                    self.ping(self.afk) # End afk period
                    self.afk = False
                    self.set_state("not-afk", timedelta())
                # If becomes AFK
                elif not self.afk and self.seconds_since_last_input > self.settings.timeout:
                    self.logger.info("Became AFK")
                    self.afk = True
                    self.set_state("afk", self.timedelta_since_last_input, self.last_input)
                # Send a heartbeat if no state change was made
                else:
                    if self.afk:
                        self.ping(self.afk)
                    elif self.seconds_since_last_input < self.settings.polling_interval:
                        self.ping(self.afk)

                sleep(self.settings.polling_interval)

            except KeyboardInterrupt:
                self.logger.info("afkwatcher stopped by keyboard interrupt")
                self.ping(self.afk)
                break
