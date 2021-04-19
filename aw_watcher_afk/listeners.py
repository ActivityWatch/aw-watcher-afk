import logging
import threading

logger = logging.getLogger(__name__)


class EventFactory:
    def next_event(self):
        """Returns an event and prepares the internal state so that it can start to build a new event"""
        raise NotImplementedError

    def has_new_event(self):
        raise NotImplementedError


class KeyboardListener(EventFactory):
    def __init__(self):
        self.logger = logger.getChild("keyboard")
        # self.logger.setLevel(logging.DEBUG)
        self.new_event = threading.Event()
        self._reset_data()

    def start(self):
        from pynput import keyboard

        listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        listener.start()

    def _reset_data(self):
        self.event_data = {"presses": 0}

    def on_press(self, key):
        print("press", key)
        self.logger.debug("Input received")
        self.event_data["presses"] += 1
        self.new_event.set()

    def on_release(self, key):
        print("release", key)

    def next_event(self):
        """Returns an event and prepares the internal state so that it can start to build a new event"""
        self.new_event.clear()
        data = self.event_data
        print(data)
        self._reset_data()
        return data

    def has_new_event(self):
        return self.new_event.is_set()


class MouseListener(EventFactory):
    def __init__(self):
        self.logger = logger.getChild("mouse")
        self.logger.setLevel(logging.INFO)
        self.new_event = threading.Event()
        self.pos = None
        self._reset_data()

    def _reset_data(self):
        self.event_data = {"clicks": 0, "deltaX": 0, "deltaY": 0}

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

        delta = tuple(abs(self.pos[i] - newpos[i]) for i in range(2))
        self.event_data["deltaX"] += delta[0]
        self.event_data["deltaY"] += delta[1]

        self.pos = newpos
        self.new_event.set()

    def on_click(self, *args):
        self.logger.debug(args)

    def click(self, x, y, button, press):
        # TODO: Differentiate between leftclick and rightclick?
        if press:
            self.logger.debug("Clicked mousebutton")
            self.event_data["clicks"] += 1
        self.new_event.set()

    def on_scroll(self, x, y, scrollx, scrolly):
        self.logger.debug(f"{scrollx}, {scrolly} at {(x, y)}")

    def has_new_event(self):
        answer = self.new_event.is_set()
        self.new_event.clear()
        return answer

    def next_event(self):
        self.new_event.clear()
        data = self.event_data
        print(data)
        self._reset_data()
        return data
