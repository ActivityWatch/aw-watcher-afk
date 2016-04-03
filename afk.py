import logging
import platform
from datetime import datetime, timedelta
from threading import Event, Thread

from pykeyboard import PyKeyboard, PyKeyboardEvent
from pymouse import PyMouse, PyMouseEvent

settings = {
    "timeout": 300
}


def _repeat_trigger(waiter: Event, trigger: Event, timeout):
    if waiter.wait(timeout+1):
        trigger.set()


def _wait_for_either(a: Event, b: Event, timeout=None):
    """Waits for any one of two events to happen"""
    # TODO: Reuse threads, don't recreate
    trigger = Event()
    ta = Thread(target=_repeat_trigger, args=(a, trigger, timeout))
    tb = Thread(target=_repeat_trigger, args=(b, trigger, timeout))
    ta.start()
    tb.start()
    # Now do the union waiting
    return trigger.wait(timeout)


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
        logging.warning("KeyboardListener is broken in OS X, will not use for detecting AFK state.")
    MouseListener(mouse_activity_event).start()

    while True:
        if _wait_for_either(keyboard_activity_event, mouse_activity_event, timeout=1):
            # Check if there has been any activity on the mouse or keyboard and if so,
            # update last_activity to now and set is_afk to False if previously AFK
            now = datetime.now()
            if is_afk:
                # If previously AFK, keyboard/mouse activity now indicates the user isn't AFK
                print("No longer AFK")
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
                print("Now AFK")
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
    main()
