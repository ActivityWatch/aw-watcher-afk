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

settings = {
    "timeout": 30,
    "check_interval": 1,
    "server_enabled": True,
    "server_hostname": "localhost",
    "server_port": "5000",
    "client_hostname": socket.gethostname()
}

logger = logging.getLogger("afkwatcher")
logger.setLevel(logging.DEBUG)

# Mute requests logging output, unless serious
logging.getLogger("requests").setLevel(logging.WARNING)


def store_event(event):
    headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
    url = "http://{}:{}/api/0/activity/afkwatcher".format(settings["server_hostname"], settings["server_port"])
    requests.post(url, data=json.dumps(event), headers=headers)
    logger.debug("Sent event to server: {}".format(event))


def main():
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
    if settings["server_enabled"]:
        store_event({"label": "afkwatcher-started", "settings": settings})

    while True:
        try:
            sleep(settings["check_interval"])
            if mouseListener.has_new_activity() or keyboardListener.has_new_activity():
                # Check if there has been any activity on the mouse or keyboard and if so,
                # update last_activity to now and set is_afk to False if previously AFK
                now = datetime.now()
                if is_afk:
                    # If AFK, keyboard/mouse activity indicates the user is no longer AFK
                    logger.info("No longer AFK")
                    if settings["server_enabled"]:
                        # Store event with the ended AFK period
                        store_event({"label": "afk", "timestamp": now.isoformat()})
                    is_afk = False
                last_activity = now
            if not is_afk:
                # If not previously AFK, check if enough time has passed for it to now count as AFK
                now = datetime.now()
                passed_time = now - last_activity
                passed_afk = passed_time > timedelta(seconds=settings["timeout"])
                if passed_afk:
                    logger.info("Now AFK")
                    if settings["server_enabled"]:
                        # Store event with the ended non-AFK period
                        store_event({"label": "not-afk", "timestamp": last_activity.isoformat()})
                    is_afk = True
        except KeyboardInterrupt:
            logger.info("afkwatcher stopped by keyboard interrupt")
            store_event({"label": "afkwatcher-stopped"})
            break
        except Exception as e:
            logger.warning("afkwatcher stopped by unexpected exception")
            store_event({"label": "afkwatcher-stopped", "note": str(e)})
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

