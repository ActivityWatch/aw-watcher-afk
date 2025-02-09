"""
Listeners for aggregated keyboard and mouse events.

This is used for AFK detection on Linux, as well as used in aw-watcher-input to track input activity in general.

NOTE: Logging usage should be commented out before committed, for performance reasons.
"""

import logging
import threading
from abc import abstractmethod
from collections import defaultdict
from typing import Dict, Any

from .listeners_base import BaseEventFactory, main_test

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


class EventFactory(BaseEventFactory):
    def __init__(self) -> None:
        self.new_event = threading.Event()
        self._reset_data()

    @abstractmethod
    def _reset_data(self) -> None:
        self.event_data: Dict[str, Any] = {}

    def next_event(self) -> dict:
        """Returns an event and prepares the internal state so that it can start to build a new event"""
        self.new_event.clear()
        data = self.event_data
        # self.logger.debug(f"Event: {data}")
        self._reset_data()
        return data

    def has_new_event(self) -> bool:
        return self.new_event.is_set()


class KeyboardListener(EventFactory):
    def __init__(self):
        EventFactory.__init__(self)
        self.logger = logger.getChild("keyboard")

    def start(self):
        from pynput import keyboard

        listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        listener.start()

    def _reset_data(self):
        self.event_data = {"presses": 0}

    def on_press(self, key):
        # self.logger.debug(f"Press: {key}")
        self.event_data["presses"] += 1
        self.new_event.set()

    def on_release(self, key):
        # Don't count releases, only clicks
        # self.logger.debug(f"Release: {key}")
        pass


class MouseListener(EventFactory):
    def __init__(self):
        EventFactory.__init__(self)
        self.logger = logger.getChild("mouse")
        self.pos = None

    def _reset_data(self):
        self.event_data = defaultdict(int)
        self.event_data.update(
            {"clicks": 0, "deltaX": 0, "deltaY": 0, "scrollX": 0, "scrollY": 0}
        )

    def start(self):
        from pynput import mouse

        listener = mouse.Listener(
            on_move=self.on_move, on_click=self.on_click, on_scroll=self.on_scroll
        )
        listener.start()

    def on_move(self, x, y):
        newpos = (x, y)
        # self.logger.debug("Moved mouse to: {},{}".format(x, y))
        if not self.pos:
            self.pos = newpos

        delta = tuple(self.pos[i] - newpos[i] for i in range(2))
        self.event_data["deltaX"] += abs(delta[0])
        self.event_data["deltaY"] += abs(delta[1])

        self.pos = newpos
        self.new_event.set()

    def on_click(self, x, y, button, down):
        # self.logger.debug(f"Click: {button} at {(x, y)}")
        # Only count presses, not releases
        if down:
            self.event_data["clicks"] += 1
            self.new_event.set()

    def on_scroll(self, x, y, scrollx, scrolly):
        # self.logger.debug(f"Scroll: {scrollx}, {scrolly} at {(x, y)}")
        self.event_data["scrollX"] += abs(scrollx)
        self.event_data["scrollY"] += abs(scrolly)
        self.new_event.set()

class MergedListener(BaseEventFactory):

    """Merges events from keyboard and mouse listeners that start() seperately"""

    keyboard: BaseEventFactory
    mouse: BaseEventFactory

    def __init__(self) -> None:
        self.keyboard = KeyboardListener()
        self.mouse = MouseListener()

    def start(self):
        """Starts monitoring events in both listeners"""
        self.mouse.start()
        self.keyboard.start()

    def next_event(self):
        """Merges results"""
        data = dict(**self.keyboard.next_event(), **self.mouse.next_event())
        # self.logger.debug(f"Event: {data}")
        return data

    def has_new_event(self):
        return self.keyboard.has_new_event() or self.mouse.has_new_event()

if __name__ == "__main__":
    main_test(MergedListener())
