"""Tests for listener health checking and auto-recovery."""

import threading
from unittest.mock import MagicMock, patch

from aw_watcher_afk.listeners import KeyboardListener, MouseListener


def test_keyboard_listener_is_alive_before_start():
    listener = KeyboardListener()
    assert not listener.is_alive()


def test_mouse_listener_is_alive_before_start():
    listener = MouseListener()
    assert not listener.is_alive()


def test_keyboard_listener_is_alive_with_mock():
    listener = KeyboardListener()
    # Simulate a started listener
    mock_pynput = MagicMock()
    mock_pynput.is_alive.return_value = True
    listener._listener = mock_pynput
    assert listener.is_alive()


def test_keyboard_listener_dead_after_x_restart():
    listener = KeyboardListener()
    # Simulate a dead listener (X server died)
    mock_pynput = MagicMock()
    mock_pynput.is_alive.return_value = False
    listener._listener = mock_pynput
    assert not listener.is_alive()


def test_mouse_listener_is_alive_with_mock():
    listener = MouseListener()
    mock_pynput = MagicMock()
    mock_pynput.is_alive.return_value = True
    listener._listener = mock_pynput
    assert listener.is_alive()


def test_mouse_listener_dead_after_x_restart():
    listener = MouseListener()
    mock_pynput = MagicMock()
    mock_pynput.is_alive.return_value = False
    listener._listener = mock_pynput
    assert not listener.is_alive()


@patch("aw_watcher_afk.unix.KeyboardListener")
@patch("aw_watcher_afk.unix.MouseListener")
def test_unix_reinitializes_dead_listeners(MockMouse, MockKeyboard):
    """When listeners die (e.g. X server restart), they should be restarted."""
    from aw_watcher_afk.unix import LastInputUnix

    # First call: listeners are alive
    mock_kb_instance = MockKeyboard.return_value
    mock_mouse_instance = MockMouse.return_value
    mock_kb_instance.is_alive.return_value = True
    mock_mouse_instance.is_alive.return_value = True
    mock_kb_instance.has_new_event.return_value = False
    mock_mouse_instance.has_new_event.return_value = False

    unix = LastInputUnix()
    unix.seconds_since_last_input()

    # Listeners should NOT have been restarted
    assert MockKeyboard.call_count == 1
    assert MockMouse.call_count == 1

    # Now simulate X server death
    mock_kb_instance.is_alive.return_value = False

    unix.seconds_since_last_input()

    # Listeners should have been restarted (new instances created)
    assert MockKeyboard.call_count == 2
    assert MockMouse.call_count == 2
