
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
import logging

from .evdev_devices import find_keyboards, find_mice

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

class AsyncioListener:

    @abstractmethod
    def next_event(self):
        raise NotImplementedError

    @abstractmethod
    def _create_tasks(self, loop):
        """Schedule asyncio tasks"""
        raise NotImplementedError

    @abstractmethod
    def has_new_event(self):
        raise NotImplementedError

    def run(self):
        """Run event loop"""
        loop = asyncio.new_event_loop()
        self._create_tasks(loop)
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            loop.stop()

    def start(self):
        thread = threading.Thread(target=self.run)
        thread.start()
        return thread

TData = TypeVar("TData", bound="BaseData")

class BaseData(metaclass=ABCMeta):
    """Stores event data"""
    @abstractmethod
    def as_dict(self):
        raise NotImplementedError
    @abstractmethod
    def nonzero(self):
        raise NotImplementedError

class DataListener(AsyncioListener, Generic[TData]):

    data: TData

    def __init__(self) -> None:
        self.data = self._init_data()

    @abstractmethod
    async def _read_loop(self, dev):
        """Read data from a device"""
        raise NotImplementedError

    @abstractmethod
    def _init_data(self) -> TData:
        raise NotImplementedError

    @abstractmethod
    def _find_devices(self) -> Iterable[str]:
        """Find relevant devices"""
        raise NotImplementedError

    def _create_tasks(self, loop):
        """Schedule a read loop for all relevant devices"""
        devices = list(self._find_devices())
        assert len(devices), "You may need to add your user to the 'input' group"
        for dev in devices:
            loop.create_task(self._read_loop(dev))

    def run(self):
        loop = asyncio.new_event_loop()
        self._create_tasks(loop)
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            loop.stop()

    def next_event(self):
        data = self.data.as_dict()
        # self.logger.debug(f"Event: {data}")
        self.data = self._init_data()
        return data

    def has_new_event(self):
        return self.data.nonzero()

class AsyncCounter:
    def __init__(self) -> None:
        self.value = 0
        self.lock = asyncio.Lock()
    async def add(self, increment):
        async with self.lock:
            self.value += increment
    def nonzero(self):
        return self.value != 0

class KeyboardData(BaseData):
    def __init__(self) -> None:
        self.presses = AsyncCounter()
    def as_dict(self):
        return dict(presses=self.presses.value)
    def nonzero(self):
        return self.presses.nonzero()

class KeyboardListener(DataListener[KeyboardData]):

    def __init__(self) -> None:
        super().__init__()

    def _init_data(self):
        return KeyboardData()

    def _find_devices(self) -> Iterable[str]:
        return find_keyboards()

    async def _read_loop(self, dev):

        """Update self.data by reading evdev events"""

        dev = InputDevice(dev)

        async for event in dev.async_read_loop():
            # logger.debug(f"Evdev event ({dev.name}): {evdev.categorize(event)}")
            if event.type == ecodes.EV_KEY and event.value == 1:
                await self.data.presses.add(1)

class MouseData(BaseData):
    def __init__(self) -> None:
        self.clicks = AsyncCounter()
        self.delta_x = AsyncCounter()
        self.delta_y = AsyncCounter()
        self.scroll_x = AsyncCounter()
        self.scroll_y = AsyncCounter()
    def as_dict(self):
        return dict(
            clicks=self.clicks.value,
            delta_x=self.delta_x.value,
            delta_y=self.delta_y.value,
            scroll_x=self.scroll_x.value,
            scroll_y=self.scroll_y.value
        )
    def counters(self):
        return (
            self.delta_x,
            self.delta_y,
            self.clicks,
            self.scroll_x,
            self.scroll_y
        )

    def nonzero(self):
        return any(ctr.nonzero() for ctr in self.counters())

class MouseListener(DataListener[MouseData]):

    def __init__(self) -> None:
        super().__init__()

    def _init_data(self):
        return MouseData()

    def _find_devices(self) -> Iterable[str]:
        return find_mice()

    async def _read_loop(self, dev):

        """Update self.data by reading evdev events"""

        dev = InputDevice(dev)

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

class MergedListener(AsyncioListener):

    def __init__(self) -> None:
        self.keyboard = KeyboardListener()
        self.mouse = MouseListener()

    def next_event(self):
        data = dict(**self.keyboard.next_event(), **self.mouse.next_event())
        # self.logger.debug(f"Event: {data}")
        return data

    def _create_tasks(self, loop):
        self.keyboard._create_tasks(loop)
        self.mouse._create_tasks(loop)

    def has_new_event(self):
        return self.keyboard.has_new_event() or self.mouse.has_new_event()

def main_test():

    listener = MergedListener()

    listener.start()

    while True:

        if listener.has_new_event():
            print(listener.next_event())


if __name__ == "__main__":
    main_test()
