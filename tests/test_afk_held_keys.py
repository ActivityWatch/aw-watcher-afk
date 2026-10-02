"""Tests for held-key de-duplication in KeyboardListener.

The OS auto-repeats a held key as repeated ``on_press`` calls, which made
aw-watcher-input report ~25 presses per second while a key was held
(ActivityWatch/aw-watcher-input#16). These tests pin the two properties the
fix must keep in balance:

1. A held key is counted once, no matter how many auto-repeat presses fire.
2. A held key still counts as activity, so de-duplicating the *count* does not
   flip the user to AFK while a key is held down.

Plain strings are used as stand-in keys: the listener only uses them as set
members, and importing pynput requires an X connection (unavailable in CI).
"""

import unittest

from aw_watcher_afk.listeners import KeyboardListener


class HeldKeyCountTests(unittest.TestCase):
    def test_auto_repeat_counts_once(self):
        listener = KeyboardListener()
        # Simulate ~1s of auto-repeat on a held key.
        for _ in range(25):
            listener.on_press("a")
        self.assertEqual(listener.next_event()["presses"], 1)

    def test_release_allows_recount(self):
        listener = KeyboardListener()
        listener.on_press("a")
        listener.on_release("a")
        listener.on_press("a")
        self.assertEqual(listener.next_event()["presses"], 2)

    def test_distinct_keys_count_individually(self):
        listener = KeyboardListener()
        listener.on_press("a")
        listener.on_press("b")
        listener.on_press("a")  # still held, not a new press
        self.assertEqual(listener.next_event()["presses"], 2)

    def test_held_key_survives_event_windows(self):
        # next_event() resets the counters; the held-key set must not be reset
        # with it, or auto-repeat would be counted again after every poll.
        listener = KeyboardListener()
        listener.on_press("a")
        listener.next_event()
        for _ in range(10):
            listener.on_press("a")
        self.assertEqual(listener.next_event()["presses"], 0)
        listener.on_release("a")
        listener.on_press("a")
        self.assertEqual(listener.next_event()["presses"], 1)


class HeldKeyActivityTests(unittest.TestCase):
    def test_held_key_keeps_activity_signal(self):
        listener = KeyboardListener()
        listener.next_event()  # consume the initial empty event
        listener.on_press("a")
        listener.next_event()  # consume the press event
        # Key is still held: the listener must keep reporting activity even
        # though no new press is counted, so AFK detection does not trip.
        self.assertTrue(listener.has_new_event())
        listener.on_release("a")
        self.assertFalse(listener.has_new_event())

    def test_no_activity_without_input(self):
        listener = KeyboardListener()
        listener.next_event()
        self.assertFalse(listener.has_new_event())


if __name__ == "__main__":
    unittest.main()
