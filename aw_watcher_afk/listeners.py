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
import os
import platform

from .listeners_base import main_test

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

system = platform.system()

def use_evdev():
    """Use evdev backend"""
    return system == "Linux" and os.getenv("USE_EVDEV") == "true"

def use_libinput():
    """Use libinput backend"""
    return system == "Linux" and os.getenv("USE_LIBINPUT") == "true"

def KeyboardListener():

    """Returns keyboard listener using backends: evdev, libinput and pynput"""

    if use_evdev():
        # noreorder
        from .listeners_evdev import KeyboardListener
    # elif use_libinput():
    #     # noreorder
    #     from .listeners_libinput import KeyboardListener
    else:
        from .listeners_pynput import KeyboardListener

    return KeyboardListener()

def MouseListener():

    """Returns mouse listener using backends: evdev, libinput, pynput"""

    if use_evdev():
        # noreorder
        from .listeners_evdev import MouseListener  # fmt: skip
    # elif use_libinput():
    #     # noreorder
    #     from .listeners_libinput import MouseListener
    else:
        # noreorder
        from .listeners_pynput import MouseListener  # fmt: skip

    return MouseListener()

def MergedListener():

    """Returns mouse and keyboard listener using backends: evdev, libinput, pynput"""

    if use_evdev():
        # noreorder
        from .listeners_evdev import MergedListener
    # elif use_libinput():
    #     # noreorder
    #     from .listeners_libinput import MergedListener
    else:
        # noreorder
        from .listeners_pynput import MergedListener  # fmt: skip

    return MergedListener()

if __name__ == "__main__":
    main_test(MergedListener())
