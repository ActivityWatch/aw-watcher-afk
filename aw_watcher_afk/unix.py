import logging
from datetime import datetime
from time import sleep


class LastInputUnix:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # self.logger.setLevel(logging.DEBUG)

        from .listeners import MergedListener

        self.listener = MergedListener()

        self.last_activity = datetime.now()

    def seconds_since_last_input(self) -> float:
        # TODO: This has a delay of however often it is called.
        #       Could be solved by creating a custom listener.
        now = datetime.now()
        if self.listener.has_new_event():
            self.logger.debug("New event")
            self.last_activity = now
            # Get/clear events
            self.listener.next_event()
        return (now - self.last_activity).total_seconds()


_last_input_unix = None


def seconds_since_last_input():
    global _last_input_unix

    if _last_input_unix is None:
        _last_input_unix = LastInputUnix()

    return _last_input_unix.seconds_since_last_input()


if __name__ == "__main__":
    while True:
        sleep(1)
        print(seconds_since_last_input())
