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

import logging
from abc import ABCMeta, abstractmethod

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

class BaseEventFactory(metaclass=ABCMeta):

    @abstractmethod
    def next_event(self):
        """Returns new event data"""
        raise NotImplementedError

    @abstractmethod
    def start(self):
        """Starts monitoring events in the background"""
        raise NotImplementedError

    @abstractmethod
    def has_new_event(self) -> bool:
        """Has new event data"""
        raise NotImplementedError

def main_test(listener):

    listener.start()

    while True:

        if listener.has_new_event():
            print(listener.next_event())
