"""
Listeners for aggregated keyboard and mouse events.

This is used for AFK detection on Linux, as well as used in aw-watcher-input to track input activity in general.

NOTE: Logging usage should be commented out before committed, for performance reasons.
"""


"""
Listeners for aggregated keyboard and mouse events.

This is used for AFK detection on Linux, as well as used in aw-watcher-input to track input activity in general.

NOTE: Logging usage should be commented out before committed, for performance reasons.
"""

from abc import ABCMeta, abstractmethod
import os
import platform

class BaseEventFactory(metaclass=ABCMeta):

    @abstractmethod
    def next_event(self):
        """Returns an event and prepares the internal state so that it can start to build a new event"""
        raise NotImplementedError

    @abstractmethod
    def start(self):
        """Starts monitoring events in the background"""
        raise NotImplementedError

    @abstractmethod
    def has_new_event(self) -> bool:
        """Has new event data"""
        raise NotImplementedError

class MergedListenerHelper(BaseEventFactory):

    """Merging events from keyboard and mouse instances that are started separately"""

    keyboard: BaseEventFactory
    mouse: BaseEventFactory

    def __init__(self, keyboard, mouse) -> None:
        self.keyboard = keyboard
        self.mouse = mouse

    def start(self):
        self.mouse.start()
        self.keyboard.start()

    def next_event(self):
        data = dict(**self.keyboard.next_event(), **self.mouse.next_event())
        # self.logger.debug(f"Event: {data}")
        return data

    def has_new_event(self):
        return self.keyboard.has_new_event() or self.mouse.has_new_event()

system = platform.system()

def use_evdev():
    return system == "Linux" and os.getenv("USE_EVDEV") == "true"

def use_libinput():
    return system == "Linux" and os.getenv("USE_LIBINPUT") == "true"

def KeyboardListener():

    if use_evdev():
        from .listeners_evdev import KeyboardListener
    elif use_libinput():
        from .listeners_libinput import KeyboardListener
    else:
        from .listeners_pynput import KeyboardListener

    return KeyboardListener()

def MouseListener():

    if use_evdev():
        from .listeners_evdev import MouseListener
    elif use_libinput():
        from .listeners_libinput import MouseListener
    else:
        from .listeners_pynput import MouseListener

    return MouseListener()

def MergedListener():

    if use_evdev():
        from .listeners_evdev import MergedListener
    elif use_libinput():
        from .listeners_libinput import MergedListener
    else:
        from .listeners_pynput import MergedListener

    return MergedListener()

def main_test_helper(listener):

    listener.start()

    while True:

        if listener.has_new_event():
            print(listener.next_event())

if __name__ == "__main__":
    main_test_helper(MergedListener())
