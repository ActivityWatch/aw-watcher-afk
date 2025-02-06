import logging
import threading
import libinput
from abc import ABCMeta, abstractmethod
from collections import defaultdict
from typing import Dict, Any

from .listeners import BaseEventFactory, MergedListenerHelper, main_test_helper

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
        self.new_event.clear()
        data = self.event_data
        self._reset_data()
        return data

    def has_new_event(self) -> bool:
        return self.new_event.is_set()


class KeyboardListener(EventFactory):
    def __init__(self):
        super().__init__()
        self.logger = logger.getChild("keyboard")
        self.libinput_context = libinput.LibInput(udev=True)
        self.libinput_context.udev_assign_seat("seat0")

    def _reset_data(self):
        self.event_data = {"presses": 0}

    def start(self):
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        for event in self.libinput_context.get_event():
            if event.type == libinput.event.type.KEYBOARD_KEY:
                if event.get_keyboard_key().key_state == libinput.KeyState.PRESSED:
                    self.event_data["presses"] += 1
                    self.new_event.set()


class MouseListener(EventFactory):
    def __init__(self):
        super().__init__()
        self.logger = logger.getChild("mouse")
        self.pos = None
        self.libinput_context = libinput.LibInput(udev=True)
        self.libinput_context.udev_assign_seat("seat0")

    def _reset_data(self):
        self.event_data = defaultdict(int)
        self.event_data.update(
            {"clicks": 0, "deltaX": 0, "deltaY": 0, "scrollX": 0, "scrollY": 0}
        )

    def start(self):
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        for event in self.libinput_context.get_event():
            if event.type == libinput.event.type.POINTER_MOTION:
                dx, dy = event.get_pointer_motion().dx, event.get_pointer_motion().dy
                self.event_data["deltaX"] += abs(dx)
                self.event_data["deltaY"] += abs(dy)
                self.new_event.set()

            elif event.type == libinput.event.type.POINTER_BUTTON:
                if event.get_pointer_button().button_state == libinput.ButtonState.PRESSED:
                    self.event_data["clicks"] += 1
                    self.new_event.set()

            elif event.type == libinput.event.type.POINTER_SCROLL:
                scrollX, scrollY = event.get_pointer_scroll().dx, event.get_pointer_scroll().dy
                self.event_data["scrollX"] += abs(scrollX)
                self.event_data["scrollY"] += abs(scrollY)
                self.new_event.set()

def MergedListener():
    return MergedListenerHelper(KeyboardListener(), MouseListener())

if __name__ == "__main__":
    main_test_helper(MergedListener())
