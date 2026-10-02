"""
Listeners for aggregated keyboard and mouse events.

This is used for AFK detection on Linux, as well as used in aw-watcher-input to track input activity in general.

NOTE: Logging usage should be commented out before committed, for performance reasons.
"""

import logging
import threading
from abc import ABCMeta, abstractmethod
from collections import defaultdict
from typing import Dict, Any, List

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


class EventFactory(metaclass=ABCMeta):
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
        self._listener = None
        # Keys currently held down. The OS auto-repeats a held key as repeated
        # on_press calls; this set lets us count each physical press once until
        # the key is released. It is intentionally not cleared by _reset_data(),
        # since it tracks physical key state rather than a single event window.
        self._held_keys: set = set()

    def start(self):
        from pynput import keyboard

        self._listener = keyboard.Listener(
            on_press=self.on_press, on_release=self.on_release
        )
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()

    def is_alive(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

    def _reset_data(self):
        self.event_data = {"presses": 0}

    def on_press(self, key):
        # self.logger.debug(f"Press: {key}")
        # Auto-repeat fires on_press repeatedly for a held key; only count the
        # first press of each key until it is released.
        if key not in self._held_keys:
            self._held_keys.add(key)
            self.event_data["presses"] += 1
        # Signal activity regardless of auto-repeat, so AFK detection still
        # sees a held key as input.
        self.new_event.set()

    def on_release(self, key):
        # Don't count releases, only presses
        # self.logger.debug(f"Release: {key}")
        self._held_keys.discard(key)

    def has_new_event(self) -> bool:
        # A held key is ongoing activity even though auto-repeat presses are
        # de-duplicated from the count. Without this, holding a modifier or a
        # game key (which may not auto-repeat at all) would let the user be
        # marked AFK while still holding a key down.
        return super().has_new_event() or bool(self._held_keys)


class MouseListener(EventFactory):
    def __init__(self):
        EventFactory.__init__(self)
        self.logger = logger.getChild("mouse")
        self.pos = None
        self._listener = None

    def _reset_data(self):
        self.event_data = defaultdict(int)
        self.event_data.update(
            {"clicks": 0, "deltaX": 0, "deltaY": 0, "scrollX": 0, "scrollY": 0}
        )

    def start(self):
        from pynput import mouse

        self._listener = mouse.Listener(
            on_move=self.on_move, on_click=self.on_click, on_scroll=self.on_scroll
        )
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()

    def is_alive(self) -> bool:
        return self._listener is not None and self._listener.is_alive()

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


class GamepadListener(EventFactory):
    """Listens for gamepad/joystick button events via evdev (Linux only, optional).

    Requires the ``evdev`` package and read access to ``/dev/input/`` device files.
    On most distros users in the ``input`` group have the required access.

    Only button press events are counted (not releases), so a held button does
    not continuously trigger "not AFK".  Analog axis events are intentionally
    ignored to avoid false positives from stick drift.
    """

    def __init__(self):
        EventFactory.__init__(self)
        self.logger = logger.getChild("gamepad")
        self._threads: List[threading.Thread] = []
        self._devices = []  # track open devices for cleanup in stop()
        self._stop_event = threading.Event()
        # True once start() has actually spawned at least one reader thread.
        # Used by callers to distinguish "no gamepad ever attached" (don't
        # restart) from "gamepad threads died after running" (do restart).
        self._was_started = False

    def _reset_data(self):
        self.event_data = {"buttons": 0}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        try:
            import evdev  # noqa: F401
        except ImportError:
            self.logger.debug(
                "evdev not installed; gamepad detection unavailable. "
                "Install it with: pip install evdev"
            )
            return

        devices = self._find_gamepads()
        if not devices:
            self.logger.debug("No gamepads/joysticks found in /dev/input/")
            return

        self.logger.info(
            "Gamepad listener started for %d device(s): %s",
            len(devices),
            [d.name for d in devices],
        )
        self._stop_event.clear()
        self._devices = list(devices)  # keep references for cleanup
        for device in devices:
            t = threading.Thread(
                target=self._read_events,
                args=(device,),
                name=f"gamepad-{device.path}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
        self._was_started = True

    def stop(self):
        self._stop_event.set()
        # Close devices to unblock threads stuck in read_loop()
        # (the blocking select() call is released when the FD is closed)
        for device in self._devices:
            try:
                device.close()
            except (OSError, IOError):
                pass
        self._devices.clear()
        # Wait briefly for threads to finish
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads.clear()
        self._was_started = False

    def is_alive(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def needs_restart(self) -> bool:
        """Return True if start() previously launched threads but any have died.

        Used to distinguish a system that simply has no gamepad attached (in
        which case start() returned early and no restart is needed) from one
        where one or more reader threads have exited unexpectedly (e.g. device
        removed or USB error). In the latter case the caller should reinitialize
        the listener so all gamepads start being tracked again.

        Detects partial failure (one of N gamepads removed) in addition to
        total failure (all gamepads removed), so multi-gamepad setups don't
        silently lose a device until the last one dies.
        """
        if not self._was_started:
            return False
        # Restart when any reader thread has died, not just when all have.
        return any(not t.is_alive() for t in self._threads)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _find_gamepads(self):
        """Return all readable /dev/input/ devices that look like gamepads."""
        import evdev

        gamepads = []
        for path in evdev.list_devices():
            try:
                device = evdev.InputDevice(path)
            except (OSError, PermissionError):
                continue
            if self._is_gamepad(device):
                gamepads.append(device)
            else:
                # Close non-gamepad devices to avoid FD leaks
                device.close()
        return gamepads

    @staticmethod
    def _is_gamepad(device) -> bool:
        """Return True if *device* appears to be a gamepad or joystick."""
        import evdev

        caps = device.capabilities()
        if evdev.ecodes.EV_KEY not in caps:
            return False
        # A subset of button codes that only appear on gamepads/joysticks
        # Note: BTN_GAMEPAD == BTN_SOUTH (both 0x130) in the Linux input subsystem;
        # BTN_SOUTH is kept as the more descriptive name and BTN_GAMEPAD omitted.
        gamepad_btns = {
            evdev.ecodes.BTN_SOUTH,  # Xbox A / PS Cross (also == BTN_GAMEPAD)
            evdev.ecodes.BTN_EAST,  # Xbox B / PS Circle
            evdev.ecodes.BTN_NORTH,  # Xbox Y / PS Triangle
            evdev.ecodes.BTN_WEST,  # Xbox X / PS Square
            evdev.ecodes.BTN_JOYSTICK,  # generic joystick button
            evdev.ecodes.BTN_TRIGGER,  # joystick trigger
            evdev.ecodes.BTN_THUMB,  # joystick thumb
            evdev.ecodes.BTN_TOP,  # joystick top
        }
        device_btns = set(caps[evdev.ecodes.EV_KEY])
        return bool(device_btns & gamepad_btns)

    def _read_events(self, device) -> None:
        """Read button events from *device* until stop() is called."""
        import evdev

        try:
            for event in device.read_loop():
                if self._stop_event.is_set():
                    break
                # Count button *press* events only (value == 1)
                if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                    # self.logger.debug(f"Gamepad button press: {event.code}")
                    self.event_data["buttons"] += 1
                    self.new_event.set()
        except (OSError, IOError):
            # Device disconnected or permission lost — stop quietly
            self.logger.debug("Gamepad device %s disconnected", device.path)
        finally:
            # Always close the device FD on thread exit
            try:
                device.close()
            except (OSError, IOError):
                pass
