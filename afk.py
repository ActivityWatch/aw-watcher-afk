import logging
import platform
from datetime import datetime, timedelta
from time import sleep
from threading import Event, Thread

from pykeyboard import PyKeyboard, PyKeyboardEvent
from pymouse import PyMouse, PyMouseEvent

settings = {
    "timeout": 1,
    "check_interval": 1
}

logger = logging.getLogger("afkwatcher")


def main():
    mouse = PyMouse()
    keyboard = PyKeyboard()

    last_activity = None
    now = datetime.now()

    is_afk = True
    afk_state_last_changed = datetime.now()

    now = datetime.now()
    last_activity = now
    afk_state_last_changed = now

    keyboard_activity_event = Event()
    mouse_activity_event = Event()

    # OS X doesn't seem to like the KeyboardListener... segfaults
    if platform.system() != "Darwin":
        KeyboardListener(keyboard_activity_event).start()
    else:
        logger.warning("KeyboardListener is broken in OS X, will not use for detecting AFK state.")
    MouseListener(mouse_activity_event).start()

    while True:
        sleep(settings["check_interval"])
        if mouse_activity_event.is_set() or keyboard_activity_event.is_set():
            # Check if there has been any activity on the mouse or keyboard and if so,
            # update last_activity to now and set is_afk to False if previously AFK
            now = datetime.now()
            if is_afk:
                # If previously AFK, keyboard/mouse activity now indicates the user isn't AFK
                logger.info("No longer AFK")
                is_afk = False
            last_activity = now
            keyboard_activity_event.clear()
            mouse_activity_event.clear()

        if not is_afk:
            # If not previously AFK, check if enough time has passed for it to now count as AFK
            now = datetime.now()
            passed_time = now - last_activity
            passed_afk = passed_time > timedelta(seconds=settings["timeout"])
            if passed_afk:
                logger.info("Now AFK")
                is_afk = True


class KeyboardListener(PyKeyboardEvent):
    def __init__(self, keyboard_activity_event):
        PyKeyboardEvent.__init__(self)
        self.keyboard_activity_event = keyboard_activity_event

    def tap(self, keycode, character, press):
        #logging.debug("Clicked keycode: {}".format(keycode))
        self.keyboard_activity_event.set()


class MouseListener(PyMouseEvent):
    def __init__(self, mouse_activity_event):
        PyMouseEvent.__init__(self)
        self.mouse_activity_event = mouse_activity_event

    def click(self, x, y, button, press):
        #logging.debug("Clicked mousebutton: {}".format(button))
        self.mouse_activity_event.set()

    def move(self, x, y):
        #logging.debug("Moved mouse to: {},{}".format(x, y))
        self.mouse_activity_event.set()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
