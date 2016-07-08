import logging
import platform
from datetime import datetime, timedelta
from time import sleep
import threading
import json
import socket
import sys

import requests

from pykeyboard import PyKeyboard, PyKeyboardEvent
from pymouse import PyMouse, PyMouseEvent

from aw_core.models import Event
from aw_client import ActivityWatchClient

# TODO: Move to argparse
settings = {
    "timeout": 60,
    "check_interval": 1,
}

logger = logging.getLogger("aw-watcher-afk")
logger.setLevel(logging.DEBUG)


def main():
    import argparse

    parser = argparse.ArgumentParser("A watcher for keyboard and mouse input to detect AFK state")
    parser.add_argument("--testing", action="store_true")
    parser.add_argument("--desktop-notify", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.testing else logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    client = ActivityWatchClient("afkwatcher", testing=args.testing)

    if args.desktop_notify:
        from gi.repository import Notify
        Notify.init("afkwatcher")

    def send_notification(msg):
        if args.desktop_notify:
            # Can crash the application if the notification daemon disappears
            n = Notify.Notification.new("AFK state changed", msg)
            n.show()

    now = datetime.now()
    last_activity = now
    is_afk = True

    mouseListener = MouseListener()
    mouseListener.start()

    keyboardListener = KeyboardListener()
    # OS X doesn't seem to like the KeyboardListener, segfaults
    if platform.system() != "Darwin":
        keyboardListener.start()
    else:
        logger.warning("KeyboardListener is broken in OS X, will not use for detecting AFK state.")

    logger.info("afkwatcher started")

    def change_to_afk(dt: datetime):
        # This function should be called when user becomes AFK
        # The argument dt should be the time when the last activity was detected,
        # which should be: change_to_afk(dt=last_activity)
        client.send_event(Event(label="not-afk", timestamp=dt))
        logger.info("Now AFK")
        send_notification("Now AFK")
        nonlocal is_afk
        is_afk = True

    def change_to_not_afk(dt: datetime):
        # This function should be called when user is no longer AFK
        # The argument dt should be the time when the at-keyboard indicating activity was detected,
        # which should be: change_to_not_afk(dt=now)
        client.send_event(Event(label="afk", timestamp=dt))
        logger.info("No longer AFK")
        send_notification("No longer AFK")
        nonlocal is_afk
        is_afk = False

    while True:
        # FIXME: Doesn't work if computer is put to sleep since state is unlikely to be
        #        in is_afk when sleep is initiated by the user.
        try:
            sleep(settings["check_interval"])
            now = datetime.now()
            if mouseListener.has_new_event() or keyboardListener.has_new_event():
                # Check if there has been any activity on the mouse or keyboard and if so,
                # update last_activity to now and set is_afk to False if previously AFK
                if is_afk:
                    # No longer AFK
                    # If AFK, keyboard/mouse activity indicates the user is no longer AFK
                    change_to_not_afk(now)
                elif now - last_activity > timedelta(seconds=settings["timeout"]):
                    # is_afk=False, but loop has been interrupted so user might actually be afk
                    # Took longer than `timeout` since last loop, computer likely put to sleep
                    change_to_afk(dt=last_activity)
                    change_to_not_afk(dt=now)
                last_activity = now
            if not is_afk:
                # If not previously AFK, check if enough time has passed for user to now be considered AFK
                passed_time = now - last_activity
                passed_afk = passed_time > timedelta(seconds=settings["timeout"])
                if passed_afk:
                    # Now AFK
                    # Store event with the ended non-AFK period
                    change_to_afk(dt=last_activity)

        except KeyboardInterrupt:
            logger.info("afkwatcher stopped by keyboard interrupt")
            break
        except Exception as e:
            logger.warning("afkwatcher stopped by unexpected exception:\n{}".format(str(e))
            break


class EventFactory:
    def next_event(self):
        """Returns an event and prepares the internal state so that it can start to build a new event"""
        raise NotImplementedError

    def has_new_event(self):
        answer = self.new_activity.is_set()
        return answer


class KeyboardListener(PyKeyboardEvent, EventFactory):
    def __init__(self):
        PyKeyboardEvent.__init__(self)
        self.logger = logging.getLogger("aw.watchers.afk.keyboard")
        self.logger.setLevel(logging.INFO)
        self.new_activity = threading.Event()
        self._reset_data()

    def _reset_data(self):
        self.event_data = {
            "presses": 0
        }

    def tap(self, keycode, character, press):
        #logging.debug("Clicked keycode: {}".format(keycode))
        self.logger.debug("Input received: {}, {}, {}".format(keycode, character, press))
        self.event_data["presses"] += 1
        self.new_activity.set()

    def escape(self, event):
        # Always returns False so that listening is never stopped
        return False

    def next_event(self):
        """Returns an event and prepares the internal state so that it can start to build a new event"""
        self.new_activity.clear()
        data = self.event_data
        self._reset_data()
        return data


class MouseListener(PyMouseEvent, EventFactory):
    def __init__(self):
        PyMouseEvent.__init__(self)
        self.logger = logging.getLogger("aw.watchers.afk.mouse")
        self.logger.setLevel(logging.INFO)
        self.new_activity = threading.Event()
        self.pos = None
        self._reset_data()

    def _reset_data(self):
        self.event_data = {
            "clicks": 0,
            "deltaX": 0,
            "deltaY": 0
        }

    def click(self, x, y, button, press):
        # TODO: Differentiate between leftclick and rightclick?
        self.logger.debug("Clicked mousebutton: {}".format(button))
        self.event_data["clicks"] += 1
        self.new_activity.set()

    def move(self, x, y):
        newpos = (x, y)
        if not self.pos:
            self.pos = newpos
        delta = tuple(abs(self.pos[i] - newpos[i]) for i in range(2))
        self.event_data["deltaX"] += newpos[0] + delta[0]
        self.event_data["deltaY"] += newpos[1] + delta[1]
        self.logger.debug("Moved mouse to: {},{}".format(x, y))
        self.new_activity.set()

    def has_new_activity(self):
        answer = self.new_activity.is_set()
        self.new_activity.clear()
        return answer

    def next_event(self):
        self.new_activity.clear()
        data = self.event_data
        self._reset_data()
        return data

