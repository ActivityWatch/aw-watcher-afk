import logging
import platform
from datetime import datetime, timedelta
from time import sleep
from threading import Event, Thread
import json
import socket
import sys

import requests

from pykeyboard import PyKeyboard, PyKeyboardEvent
from pymouse import PyMouse, PyMouseEvent

from aw.client import ActivityWatchClient


settings = {
    "timeout": 60,
    "check_interval": 1,
    "server_enabled": True,
    "desktop_notify": True,
}

logger = logging.getLogger("aw-watcher-afk")
logger.setLevel(logging.DEBUG)

if settings["desktop_notify"]:
    from gi.repository import Notify
    Notify.init("afkwatcher")

def send_notification(msg):
    if settings["desktop_notify"]:
        # Can crash the application if the notification daemon disappears
        n = Notify.Notification.new("AFK state changed", msg)
        n.show()


def main():
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    client = ActivityWatchClient("afkwatcher")

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
    client.send_event({"label": "afkwatcher-started", "settings": settings})

    def change_to_afk(time: datetime):
        # End not-afk period
        client.send_event({"label": "not-afk", "timestamp": time.isoformat()})
        logger.info("Now AFK")
        send_notification("Now AFK")
        is_afk = True

    def change_to_not_afk():
        client.send_event({"label": "afk", "timestamp": now.isoformat()})
        logger.info("No longer AFK")
        send_notification("No longer AFK")
        is_afk = False

    while True:
        # FIXME: Doesn't work if computer is put to sleep since state is unlikely to be
        #        in is_afk when sleep is initiated by the user.
        try:
            sleep(settings["check_interval"])
            now = datetime.now()
            if mouseListener.has_new_activity() or keyboardListener.has_new_activity():
                # Check if there has been any activity on the mouse or keyboard and if so,
                # update last_activity to now and set is_afk to False if previously AFK
                if is_afk:
                    # No longer AFK
                    # If AFK, keyboard/mouse activity indicates the user is no longer AFK
                    change_to_not_afk(now)
                elif now - last_activity > timedelta(seconds=settings["timeout"]):
                    # is_afk=False, but loop has been interrupted so user might actually be afk
                    # Took longer than `timeout` since last loop, computer likely put to sleep
                    change_to_afk(time=last_activity)
                    change_to_not_afk(time=now)
                last_activity = now
            if not is_afk:
                # If not previously AFK, check if enough time has passed for it to now count as AFK
                passed_time = now - last_activity
                passed_afk = passed_time > timedelta(seconds=settings["timeout"])
                if passed_afk:
                    # Now AFK
                    # Store event with the ended non-AFK period
                    change_to_afk(last_activity)
        except KeyboardInterrupt:
            logger.info("afkwatcher stopped by keyboard interrupt")
            client.send_event({"label": "afkwatcher-stopped"})
            break
        except Exception as e:
            logger.warning("afkwatcher stopped by unexpected exception")
            client.send_event({"label": "afkwatcher-stopped", "note": str(e)})
            break


class KeyboardListener(PyKeyboardEvent):
    def __init__(self):
        PyKeyboardEvent.__init__(self)
        self.logger = logging.getLogger("afkwatcher.keyboard")
        self.logger.setLevel(logging.INFO)
        self.activity_event = Event()

    def tap(self, keycode, character, press):
        #logging.debug("Clicked keycode: {}".format(keycode))
        self.logger.debug("Input received: {}, {}, {}".format(keycode, character, press))
        self.activity_event.set()

    def escape(self, event):
        # Always returns False so that listening is never stopped
        return False

    def has_new_activity(self):
        answer = self.activity_event.is_set()
        self.activity_event.clear()
        return answer


class MouseListener(PyMouseEvent):
    def __init__(self):
        PyMouseEvent.__init__(self)
        self.logger = logging.getLogger("afkwatcher.mouse")
        self.logger.setLevel(logging.INFO)
        self.activity_event = Event()

    def click(self, x, y, button, press):
        self.logger.debug("Clicked mousebutton: {}".format(button))
        self.activity_event.set()

    def move(self, x, y):
        self.logger.debug("Moved mouse to: {},{}".format(x, y))
        self.activity_event.set()

    def has_new_activity(self):
        answer = self.activity_event.is_set()
        self.activity_event.clear()
        return answer

