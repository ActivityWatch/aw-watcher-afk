import logging
from datetime import datetime, timedelta
import threading
from time import sleep

from pykeyboard import PyKeyboardEvent
from pymouse import PyMouseEvent

logger = logging.getLogger(__name__)


class EventFactory:
    def next_event(self):
        """Returns an event and prepares the internal state so that it can start to build a new event"""
        raise NotImplementedError

    def has_new_event(self):
        raise NotImplementedError


class KeyboardListener(PyKeyboardEvent, EventFactory):
    def __init__(self):
        PyKeyboardEvent.__init__(self)
        self.logger = logger.getChild("keyboard")
        # self.logger.setLevel(logging.DEBUG)
        self.new_event = threading.Event()
        self._reset_data()

    def _reset_data(self):
        self.event_data = {
            "presses": 0
        }

    def tap(self, keycode, character, press):
        # logging.debug("Clicked keycode: {}".format(keycode))
        self.logger.debug("Input received: {}, {}, {}".format(keycode, character, press))
        self.event_data["presses"] += 1
        self.new_event.set()

    def escape(self, event):
        # Always returns False so that listening is never stopped
        return False

    def next_event(self):
        """Returns an event and prepares the internal state so that it can start to build a new event"""
        self.new_event.clear()
        data = self.event_data
        self._reset_data()
        return data

    def has_new_event(self):
        return self.new_event.is_set()


class MouseListener(PyMouseEvent, EventFactory):
    def __init__(self):
        PyMouseEvent.__init__(self)
        self.logger = logger.getChild("mouse")
        self.logger.setLevel(logging.INFO)
        self.new_event = threading.Event()
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
        if press:
            self.logger.debug("Clicked mousebutton: {}".format(button))
            self.event_data["clicks"] += 1
        self.new_event.set()

    def move(self, x, y):
        newpos = (x, y)
        #self.logger.debug("Moved mouse to: {},{}".format(x, y))
        if not self.pos:
            self.pos = newpos

        delta = tuple(abs(self.pos[i] - newpos[i]) for i in range(2))
        self.event_data["deltaX"] += delta[0]
        self.event_data["deltaY"] += delta[1]

        self.pos = newpos
        self.new_event.set()

    def has_new_event(self):
        answer = self.new_event.is_set()
        self.new_event.clear()
        return answer

    def next_event(self):
        self.new_event.clear()
        data = self.event_data
        self._reset_data()
        return data
