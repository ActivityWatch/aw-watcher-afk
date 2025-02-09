"""
Listeners for aggregated keyboard and mouse events using evdev.

This is used for AFK detection on Linux, as well as used in aw-watcher-input to track input activity in general.

NOTE: Logging usage should be commented out before committed, for performance reasons.
"""

import asyncio
import threading
from abc import ABCMeta, abstractmethod
from typing import Generic, Iterable, TypeVar
from evdev import InputDevice, ecodes
import evdev
import logging

from .listeners_base import BaseEventFactory, main_test
from .evdev_devices import find_keyboards, find_mice

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

class AsyncioListener(BaseEventFactory):

    """Listener with an asyncio loop"""

    def __init__(self, loop=None) -> None:
        if loop is None:
            self.loop = asyncio.new_event_loop()
            # Ensures asyncio.Event() instances linked to this loop
            asyncio.set_event_loop(self.loop)
        else:
            self.loop = loop

    @abstractmethod
    def _create_tasks(self):
        """Schedule reading devices and monitoring tasks"""
        raise NotImplementedError

    def run(self):
        """Run asyncio loop"""
        self._create_tasks()
        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            self.loop.stop()

    def start(self):
        """Run asyncio loop on background thread"""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread

class AsyncCounter:
    def __init__(self, name, new_event) -> None:
        """
        Sychronised event counter
        """
        self.name: str = name # name of counter
        self.new_event: asyncio.Event = new_event
        self.value = 0
        self.lock = asyncio.Lock()
    async def add(self, increment):
        """Increment value and signal new event ready"""
        if increment == 0:
            return
        async with self.lock:
            self.value += increment
            self.new_event.set()
    async def get(self, next_event):
        """Return value and reset"""
        async with self.lock:
            val = self.value
            self.value = 0
            self.new_event = next_event
        return val

TData = TypeVar("TData", bound="AsyncData")

class AsyncData(metaclass=ABCMeta):
    """Stores counters and generates event"""
    def __init__(self) -> None:
        self._init_events()
        self.counters = self._init_counters()
        self._event_data = {
            ctr.name: None
            for ctr in self.counters
        }
    def _init_events(self):
        self.new_event = asyncio.Event()
        self.data_asked = asyncio.Event() # Signals that an event is requested
        self.data_ready = threading.Event() # Signals that the event is ready
    @abstractmethod
    def _init_counters(self) -> tuple:
        """Return tuple of counters"""
        raise NotImplementedError
    async def _prepare_event(self):
        """Prepare event data by moving counts into dictionary"""
        self._event_data = dict()
        self.new_event = asyncio.Event()
        for ctr in self.counters:
            val = await ctr.get(self.new_event)
            self._event_data[ctr.name] = val

    async def _prepare_data_loop(self):
        """Monitor requests for event data"""
        while True:
            await self.data_asked.wait() # Wait for event request
            await self._prepare_event()
            self.data_asked.clear()
            self.data_ready.set() # Signal event is ready
    def event_data(self):
        """Make request for event data"""
        self.data_asked.set() # Request event from loop
        self.data_ready.wait() # Wait until event is ready
        data = self._event_data
        self.data_ready.clear()
        return data

class DataListener(AsyncioListener, Generic[TData]):

    data: TData

    def __init__(self, loop=None, data=None) -> None:
        """Listener with async event data"""
        super().__init__(loop)
        if data is None:
            self.data = self._init_data()
        else:
            self.data = data

    @abstractmethod
    def _init_data(self) -> TData:
        raise NotImplementedError

    @abstractmethod
    def _create_tasks_read(self):
        """Schedule a reading devices for all relevant devices"""
        raise NotImplementedError

    #TODO: Discover new devices

    def _create_tasks_monitor(self):
        """Monitor requests for event data"""
        self.loop.create_task(self.data._prepare_data_loop())

    def _create_tasks(self):
        """Schedule tasks for reading input events"""
        self._create_tasks_read()
        self._create_tasks_monitor()

    def next_event(self):
        """Returns an event and resets the counters"""
        data = self.data.event_data()
        # self.logger.debug(f"Event: {data}")
        return data

    def has_new_event(self):
        return self.data.new_event.is_set()

class DataListenerDevices(DataListener[TData]):

    @abstractmethod
    async def _read_device(self, dev):
        """Read data from a device"""
        raise NotImplementedError

    async def reconnect_wait(self):
        """Wait before attempting reconnect to input device"""
        await asyncio.sleep(2)

    async def _read_device_reconnect(self, dev):

        """Update self.data by reading evdev events"""

        while True:
            try:
                dev = InputDevice(dev)
                logger.debug(f"Connected to {dev.name}")
                await self._read_device(dev)
            except OSError as e:
                logger.warning(f"Device {dev.path} disconnected: {e}")
                await self.reconnect_wait()
            except Exception as e:
                logger.error(f"Unexpected error in event loop: {e}", exc_info=True)

    @abstractmethod
    def _find_devices(self) -> Iterable[str]:
        """Find relevant devices"""
        raise NotImplementedError

    def _create_tasks_read(self):
        """Schedule reading all relevant devices"""
        devices = list(self._find_devices())
        assert len(devices), "You may need to add your user to the 'input' group"
        for dev in devices:
            self.loop.create_task(self._read_device_reconnect(dev))

class KeyboardData(AsyncData):
    def _init_counters(self):
        self.presses = AsyncCounter("presses", self.new_event)
        return (self.presses,)

class KeyboardListener(DataListenerDevices[KeyboardData]):

    def _init_data(self):
        return KeyboardData()

    async def _read_device(self, dev):

        async for event in dev.async_read_loop():
            # logger.debug(f"Evdev event ({dev.name}): {evdev.categorize(event)}")
            if event.type == ecodes.EV_KEY and event.value == 1:
                await self.data.presses.add(1)

    def _find_devices(self) -> Iterable[str]:
        return find_keyboards()

class MouseData(AsyncData):
    def _init_counters(self):
        self.clicks = AsyncCounter("clicks", self.new_event)
        self.delta_x = AsyncCounter("deltaX", self.new_event)
        self.delta_y = AsyncCounter("deltaY", self.new_event)
        self.scroll_x = AsyncCounter("scrollX", self.new_event)
        self.scroll_y = AsyncCounter("scrollY", self.new_event)
        return (self.delta_x, self.delta_y, self.clicks, self.scroll_x, self.scroll_y)

class MouseListener(DataListenerDevices[MouseData]):
    #NOTE: Can't interpret touch scrolling

    def _init_data(self):
        return MouseData()

    async def _read_device(self, dev):

        """Update self.data by reading evdev events"""

        old_x = None
        old_y = None

        async for event in dev.async_read_loop():
            # logger.debug(f"Evdev event ({dev.name}): {evdev.categorize(event)}")
            if event.type == ecodes.EV_KEY:
                if event.value == 1:
                    await self.data.clicks.add(1)
            elif event.type == ecodes.EV_ABS:
                if event.code == ecodes.ABS_X:
                    if old_x is not None:
                        await self.data.delta_x.add(abs(event.value - old_x))
                    old_x = event.value
                elif event.code == ecodes.ABS_Y:
                    if old_y is not None:
                        await self.data.delta_y.add(abs(event.value - old_y))
                    old_y = event.value
            else:
                if event.code == ecodes.REL_X:
                    await self.data.delta_x.add(abs(event.value))
                elif event.code == ecodes.REL_Y:
                    await self.data.delta_y.add(abs(event.value))
                elif event.code == ecodes.REL_WHEEL:
                    await self.data.scroll_y.add(abs(event.value))
                elif event.code == ecodes.REL_HWHEEL:
                    await self.data.scroll_x.add(abs(event.value))


    def _find_devices(self) -> Iterable[str]:
        return find_mice()

class MergedData(AsyncData):
    def _init_counters(self) -> tuple:
        self.presses = AsyncCounter("presses", self.new_event)
        self.clicks = AsyncCounter("clicks", self.new_event)
        self.delta_x = AsyncCounter("deltaX", self.new_event)
        self.delta_y = AsyncCounter("deltaY", self.new_event)
        self.scroll_x = AsyncCounter("scrollX", self.new_event)
        self.scroll_y = AsyncCounter("scrollY", self.new_event)
        return (self.presses, self.delta_x, self.delta_y, self.clicks, self.scroll_x, self.scroll_y)

class MergedListener(DataListener):

    def __init__(self, data=None) -> None:
        """ Delegates scheduling device reading to keyboard and mouse listener"""
        super().__init__()
        self.keyboard = KeyboardListener(self.loop, self.data)
        self.mouse = MouseListener(self.loop, self.data)

    def _init_data(self):
        return MergedData()

    def _create_tasks_read(self):
        self.keyboard._create_tasks_read()
        self.mouse._create_tasks_read()

if __name__ == "__main__":
    main_test()
