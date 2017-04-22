import logging
import platform
from datetime import datetime, timedelta, timezone
from time import sleep

from aw_core.models import Event
from aw_client import ActivityWatchClient

from .config import watcher_config

if platform.system() == "Windows":
    from .windows import time_since_last_input as _time_since_last_input_winfail
elif platform.system() in ["Darwin", "Linux"]:
    from .unix import time_since_last_input as _time_since_last_input_unix


class Settings:
    def __init__(self, config_section):
        self.timeout = config_section.getfloat("timeout")
        self.update_interval = config_section.getfloat("update_interval")
        self.check_interval = config_section.getfloat("check_interval")
        # TODO: This is a better name for whichever variable above is this one
        self.polling_interval = 1


def get_time_since_last_input():
    system = platform.system()
    if system in ["Darwin", "Linux"]:
        return _time_since_last_input_unix()
    elif system == "Windows":
        return _time_since_last_input_winfail()
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

        self.afk = True
        self.now = datetime.now(timezone.utc)  # Will update every poll
        self.last_update = self.now
        self.last_change = self.now

    def _report_state(self, afk, duration, timestamp, update=False):
        # Report AFK state to aw-server
        try:
            assert duration >= timedelta()
        except:
            self.logger.warning("Duration was negative: {}s".format(duration.total_seconds()))

        label = "afk" if afk else "not-afk"
        e = Event(label=label, timestamp=timestamp, duration=duration)

        if update:
            self.client.replace_last_event(self.bucketname, e)
        else:
            self.client.send_event(self.bucketname, e)

    def change_state(self, when):
        self._report_state(afk=self.afk, duration=when - self.last_change, timestamp=self.last_change, update=True)
        self.afk = not self.afk
        self.last_change = when
        self.last_update = self.now
        self._report_state(afk=self.afk, duration=self.now - when, timestamp=self.last_change, update=False)

    def update_unchanged(self, when):
        self.last_update = self.now
        duration = self.now - self.last_change
        self._report_state(self.afk, duration=duration, timestamp=self.last_change, update=True)

    def set_state(self, new_afk, when):
        if self.afk == new_afk:
            self.update_unchanged(when)
        else:
            self.change_state(when)

    def run(self):
        # TODO: All usage of last_activity can probably be replaced the time_since_last_input equivalent

        self.logger.info("afkwatcher started")

        """ Initialization """
        sleep(1)
        self._report_state(afk=self.afk, duration=timedelta(), timestamp=self.now)

        while True:
            try:
                self.last_check = self.now
                self.now = datetime.now(timezone.utc)

                if self.now > self.last_check + timedelta(seconds=2 * self.settings.polling_interval):
                    """
                    Computer has been woken up from sleep/hibernation
                    (or has hang for longer than the timeout, which is unlikely)
                    """
                    if self.afk:
                        self._report_state(afk=True, duration=self.now - self.second_last_activity, timestamp=self.second_last_activity, update=True)
                    else:
                        self.change_state(self.second_last_activity)

                    # NOTE: Kind of iffy. Gives incorrect behavior in case of stall,
                    #       but it's the easiest solution we found to an annoying problem.
                    self.last_activity = self.now
                    self.afk = False
                else:
                    time_since_last_input = get_time_since_last_input()
                    self.logger.debug("Time since last input:", time_since_last_input)

                    if self.afk and time_since_last_input < self.settings.timeout:
                        self.logger.info("No longer AFK")
                        self.change_state(self.now)
                    elif not self.afk and time_since_last_input > self.settings.timeout:
                        self.logger.info("Became AFK")
                        self.change_state(self.last_activity)
                    elif self.now > self.last_update + timedelta(seconds=self.settings.update_interval):
                        self.update_unchanged(self.now)

                sleep(self.settings.polling_interval)
            except KeyboardInterrupt:
                self.logger.info("afkwatcher stopped by keyboard interrupt")
                break
