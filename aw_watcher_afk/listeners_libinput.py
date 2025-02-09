# import logging
# import threading
# import libinput
# from abc import abstractmethod
# from collections import defaultdict
# from typing import Dict, Any

# from .listeners import BaseEventFactory, MergedListenerHelper, main_test_helper

# logger = logging.getLogger(__name__)
# # logger.setLevel(logging.DEBUG)


# class EventFactory(BaseEventFactory):
#     def __init__(self) -> None:
#         self.new_event = threading.Event()
#         self._reset_data()
#         self.libinput_context = libinput.LibInput(udev=True)
#         self.libinput_context.udev_assign_seat("seat0")

#     @abstractmethod
#     def _reset_data(self) -> None:
#         self.event_data: Dict[str, Any] = {}

#     def next_event(self) -> dict:
#         self.new_event.clear()
#         data = self.event_data
#         self._reset_data()
#         return data

#     def start(self):
#         # threading.Thread(target=self._listen, daemon=True).start()
#         self._listen()

#     def _get_events(self):
#         while True:
#             try:
#                 for event in self.libinput_context.get_event():
#                     # not sure how to flush queue
#                     yield event
#             except ValueError as e:
#                 pass

#     @abstractmethod
#     def _read_event(self, event):
#         raise NotImplementedError

#     def _listen(self):
#         for event in self._get_events():
#             self._read_event(event)
#             # print(self.event_data)

#     def has_new_event(self) -> bool:
#         return self.new_event.is_set()

# class KeyboardListener(EventFactory):

#     def _reset_data(self):
#         self.event_data = defaultdict(int)
#         self.event_data.update(
#             {"presses": 0}
#         )

#     def _read_event(self, event):
#         if event.type == libinput.event.enumEvent.KEYBOARD_KEY:
#             if event.get_keyboard_event().get_key_state() == libinput.constant.KeyState.PRESSED:
#                 self.event_data["presses"] += 1
#                 self.new_event.set()


# class MouseListener(EventFactory):
#     def __init__(self):
#         super().__init__()
#         self.pos = None

#     def _reset_data(self):
#         self.event_data = defaultdict(int)
#         self.event_data.update(
#             {"clicks": 0, "deltaX": 0, "deltaY": 0, "scrollX": 0, "scrollY": 0}
#         )

#     def _read_event(self, event):

#         if event.type == libinput.event.enumEvent.POINTER_MOTION:
#             dx, dy = event.get_pointer_event().get_dx(), event.get_pointer_event().get_dy()
#             self.event_data["deltaX"] += abs(dx)
#             self.event_data["deltaY"] += abs(dy)
#             self.new_event.set()

#         elif event.type == libinput.event.enumEvent.POINTER_BUTTON:
#             if event.get_pointer_event().get_button_state() == libinput.constant.ButtonState.PRESSED:
#                 self.event_data["clicks"] += 1
#                 self.new_event.set()
#         elif event.type == libinput.event.enumEvent.POINTER_AXIS:
#             if event.get_pointer_event().has_axis(libinput.constant.PointerAxis.SCROLL_HORIZONTAL):
#                 self.event_data["scrollX"] += abs(event.get_pointer_event().get_axis_value(libinput.event.PointerAxis.SCROLL_HORIZONTAL))
#                 self.new_event.set()
#             if event.get_pointer_event().has_axis(libinput.constant.PointerAxis.SCROLL_VERTICAL):
#                 self.event_data["scrollY"] += abs(event.get_pointer_event().get_axis_value(libinput.event.PointerAxis.SCROLL_VERTICAL))
#                 self.new_event.set()

# class MergedListener(EventFactory):
#     def __init__(self):
#         super().__init__()
#         self.pos = None

#     def _reset_data(self):
#         self.event_data = defaultdict(int)
#         self.event_data.update(
#             {"presses": 0, "clicks": 0, "deltaX": 0, "deltaY": 0, "scrollX": 0, "scrollY": 0}
#         )

#     def _read_event(self, event):
#         KeyboardListener._read_event(self, event)
#         MouseListener._read_event(self, event)

# if __name__ == "__main__":
#     main_test_helper(MergedListener())
