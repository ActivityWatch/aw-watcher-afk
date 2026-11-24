"""Tests for listener health checking and auto-recovery."""

from unittest.mock import MagicMock, patch

from aw_watcher_afk.listeners import GamepadListener, KeyboardListener, MouseListener


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
@patch("aw_watcher_afk.unix.GamepadListener")
def test_unix_reinitializes_dead_listeners(MockGamepad, MockMouse, MockKeyboard):
    """When listeners die (e.g. X server restart), they should be restarted."""
    from aw_watcher_afk.unix import LastInputUnix

    # First call: listeners are alive
    mock_kb_instance = MockKeyboard.return_value
    mock_mouse_instance = MockMouse.return_value
    mock_gamepad_instance = MockGamepad.return_value
    mock_kb_instance.is_alive.return_value = True
    mock_mouse_instance.is_alive.return_value = True
    mock_gamepad_instance.is_alive.return_value = False  # no gamepad connected
    # No gamepad attached → needs_restart() should be False so we don't
    # reinitialize every poll on gamepad-less systems.
    mock_gamepad_instance.needs_restart.return_value = False
    mock_kb_instance.has_new_event.return_value = False
    mock_mouse_instance.has_new_event.return_value = False
    mock_gamepad_instance.has_new_event.return_value = False

    unix = LastInputUnix()
    unix.seconds_since_last_input()

    # Listeners should NOT have been restarted
    assert MockKeyboard.call_count == 1
    assert MockMouse.call_count == 1

    # Now simulate X server death
    mock_kb_instance.is_alive.return_value = False

    unix.seconds_since_last_input()

    # Only the dead keyboard listener is restarted; the healthy mouse listener
    # keeps its buffered events. No gamepad reader is running, so recovery also
    # rescans for a controller connected since the last scan.
    assert MockKeyboard.call_count == 2
    assert MockMouse.call_count == 1
    assert MockGamepad.call_count == 2


# ---------------------------------------------------------------------------
# GamepadListener tests
# ---------------------------------------------------------------------------


def test_gamepad_listener_not_alive_before_start():
    listener = GamepadListener()
    assert not listener.is_alive()


def test_gamepad_listener_not_alive_without_evdev(monkeypatch):
    """GamepadListener.start() should be a no-op when evdev is not installed."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "evdev":
            raise ImportError("No module named 'evdev'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    listener = GamepadListener()
    listener.start()
    assert not listener.is_alive()


def test_gamepad_listener_not_alive_without_devices():
    """GamepadListener.start() should be a no-op when no gamepads are found."""
    listener = GamepadListener()
    with patch.object(listener, "_find_gamepads", return_value=[]):
        listener.start()
    assert not listener.is_alive()


def test_gamepad_listener_starts_with_device():
    """GamepadListener.start() should launch a reader thread per device."""
    import sys
    from unittest.mock import MagicMock

    listener = GamepadListener()

    mock_device = MagicMock()
    mock_device.path = "/dev/input/event5"
    mock_device.name = "Xbox Controller"

    # evdev is an optional dependency; mock the import so the test runs without it
    mock_evdev = MagicMock()
    with (
        patch.dict(sys.modules, {"evdev": mock_evdev}),
        patch.object(listener, "_find_gamepads", return_value=[mock_device]),
        patch.object(listener, "_read_events"),
    ):
        listener.start()

    assert len(listener._threads) == 1
    listener.stop()


def test_gamepad_listener_detects_button_press():
    """Simulated button press should set has_new_event() and count the press."""
    listener = GamepadListener()
    assert not listener.has_new_event()

    # Simulate what _read_events does on BTN_SOUTH press
    listener.event_data["buttons"] += 1
    listener.new_event.set()

    assert listener.has_new_event()
    data = listener.next_event()
    assert data["buttons"] == 1
    # After next_event the counter is reset
    assert not listener.has_new_event()


@patch("aw_watcher_afk.unix.KeyboardListener")
@patch("aw_watcher_afk.unix.MouseListener")
@patch("aw_watcher_afk.unix.GamepadListener")
def test_unix_gamepad_event_resets_afk_timer(MockGamepad, MockMouse, MockKeyboard):
    """A gamepad button press should reset the AFK timer."""
    from aw_watcher_afk.unix import LastInputUnix

    mock_kb_instance = MockKeyboard.return_value
    mock_mouse_instance = MockMouse.return_value
    mock_gamepad_instance = MockGamepad.return_value

    mock_kb_instance.is_alive.return_value = True
    mock_mouse_instance.is_alive.return_value = True
    mock_gamepad_instance.is_alive.return_value = True
    mock_gamepad_instance.needs_restart.return_value = False

    # No keyboard/mouse events, but gamepad has an event
    mock_kb_instance.has_new_event.return_value = False
    mock_mouse_instance.has_new_event.return_value = False
    mock_gamepad_instance.has_new_event.return_value = True

    unix = LastInputUnix()
    seconds = unix.seconds_since_last_input()

    # Timer was just reset by the gamepad event → nearly 0 seconds since last input
    assert seconds < 1.0
    # Event was consumed
    mock_gamepad_instance.next_event.assert_called_once()


# ---------------------------------------------------------------------------
# GamepadListener.needs_restart()
# ---------------------------------------------------------------------------


def test_gamepad_needs_restart_false_before_start():
    """needs_restart() must be False before start() so we don't try to restart
    a listener that was never running (e.g. on systems with no gamepad)."""
    listener = GamepadListener()
    assert not listener.needs_restart()


def test_gamepad_needs_restart_false_when_start_was_noop():
    """If start() returns early (no evdev / no devices), needs_restart() must
    stay False to avoid an infinite restart loop on gamepad-less systems."""
    listener = GamepadListener()
    with patch.object(listener, "_find_gamepads", return_value=[]):
        listener.start()
    assert not listener.is_alive()
    assert not listener.needs_restart()


def test_gamepad_needs_restart_true_when_threads_died():
    """After start() spawned threads, needs_restart() should flip to True once
    all reader threads have exited (e.g. device unplugged)."""
    import sys
    from unittest.mock import MagicMock

    listener = GamepadListener()

    mock_device = MagicMock()
    mock_device.path = "/dev/input/event5"
    mock_device.name = "Xbox Controller"

    mock_evdev = MagicMock()
    with (
        patch.dict(sys.modules, {"evdev": mock_evdev}),
        patch.object(listener, "_find_gamepads", return_value=[mock_device]),
        patch.object(listener, "_read_events"),  # returns immediately
    ):
        listener.start()

    # Wait for the (no-op) reader thread to exit
    for t in listener._threads:
        t.join(timeout=2.0)

    assert not listener.is_alive()
    assert listener.needs_restart()


def test_gamepad_needs_restart_false_after_stop():
    """After an explicit stop(), needs_restart() must be False so the caller
    doesn't keep recreating a listener the user wanted shut down."""
    import sys
    from unittest.mock import MagicMock

    listener = GamepadListener()

    mock_device = MagicMock()
    mock_device.path = "/dev/input/event5"
    mock_device.name = "Xbox Controller"

    mock_evdev = MagicMock()
    with (
        patch.dict(sys.modules, {"evdev": mock_evdev}),
        patch.object(listener, "_find_gamepads", return_value=[mock_device]),
        patch.object(listener, "_read_events"),
    ):
        listener.start()
    listener.stop()
    assert not listener.needs_restart()


@patch("aw_watcher_afk.unix.KeyboardListener")
@patch("aw_watcher_afk.unix.MouseListener")
@patch("aw_watcher_afk.unix.GamepadListener")
def test_unix_restarts_when_only_gamepad_dies(MockGamepad, MockMouse, MockKeyboard):
    """If the gamepad listener dies but mouse/keyboard are still alive, the
    gamepad listener should still be reinitialized so a reconnected gamepad
    starts being tracked again (regression for the original bug). The healthy
    mouse/keyboard listeners are left running so their buffered input is kept."""
    from aw_watcher_afk.unix import LastInputUnix

    mock_kb = MockKeyboard.return_value
    mock_mouse = MockMouse.return_value
    mock_gamepad = MockGamepad.return_value

    mock_kb.is_alive.return_value = True
    mock_mouse.is_alive.return_value = True
    mock_gamepad.is_alive.return_value = True
    mock_gamepad.needs_restart.return_value = False
    mock_kb.has_new_event.return_value = False
    mock_mouse.has_new_event.return_value = False
    mock_gamepad.has_new_event.return_value = False

    unix = LastInputUnix()
    unix.seconds_since_last_input()

    assert MockGamepad.call_count == 1  # not restarted yet

    # Now simulate the gamepad dying while mouse/keyboard stay alive
    mock_gamepad.is_alive.return_value = False
    mock_gamepad.needs_restart.return_value = True

    unix.seconds_since_last_input()

    # Only the gamepad listener is recreated
    assert MockKeyboard.call_count == 1
    assert MockMouse.call_count == 1
    assert MockGamepad.call_count == 2


def test_gamepad_needs_restart_true_when_one_of_two_threads_dies():
    """needs_restart() must be True if any thread dies, not only when all die.

    This covers multi-gamepad setups where one device is removed while another
    stays alive; without this the dead device goes silently unmonitored.

    Uses direct thread-state injection to avoid mock-revert races with
    background threads (see lessons/tools/mock-revert-race-background-threads.md).
    """
    import threading

    listener = GamepadListener()
    listener._was_started = True

    # dead_thread: simulates a gamepad that was unplugged (thread exited)
    dead_thread = threading.Thread(target=lambda: None, daemon=True)
    dead_thread.start()
    dead_thread.join(timeout=2.0)
    assert not dead_thread.is_alive()

    # live_thread: simulates a gamepad still connected (thread still running)
    keep_alive = threading.Event()
    live_thread = threading.Thread(target=keep_alive.wait, daemon=True)
    live_thread.start()

    listener._threads = [dead_thread, live_thread]

    try:
        # is_alive() should see the live thread; needs_restart() should fire on the dead one
        assert listener.is_alive()
        assert listener.needs_restart()
    finally:
        keep_alive.set()
        live_thread.join(timeout=2.0)


@patch("aw_watcher_afk.unix.KeyboardListener")
@patch("aw_watcher_afk.unix.MouseListener")
@patch("aw_watcher_afk.unix.GamepadListener")
def test_unix_log_message_when_gamepad_and_keyboard_die_together(
    MockGamepad, MockMouse, MockKeyboard, caplog
):
    """When gamepad AND mouse/keyboard die simultaneously, the log should say
    'All input listeners died' (XServer restart context), not just 'Gamepad
    listener died' (device-removal context).
    """
    import logging
    from aw_watcher_afk.unix import LastInputUnix

    mock_kb = MockKeyboard.return_value
    mock_mouse = MockMouse.return_value
    mock_gamepad = MockGamepad.return_value

    mock_kb.is_alive.return_value = True
    mock_mouse.is_alive.return_value = True
    mock_gamepad.is_alive.return_value = True
    mock_gamepad.needs_restart.return_value = False
    mock_kb.has_new_event.return_value = False
    mock_mouse.has_new_event.return_value = False
    mock_gamepad.has_new_event.return_value = False

    unix = LastInputUnix()
    unix.seconds_since_last_input()

    # Simulate all listeners dying at once (XServer crash)
    mock_kb.is_alive.return_value = False
    mock_mouse.is_alive.return_value = False
    mock_gamepad.is_alive.return_value = False
    mock_gamepad.needs_restart.return_value = True

    with caplog.at_level(logging.WARNING):
        unix.seconds_since_last_input()

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("All input listeners died" in m for m in warning_messages), (
        f"Expected 'All input listeners died' in log, got: {warning_messages}"
    )
    assert not any("Gamepad listener died" in m for m in warning_messages), (
        f"Should not say 'Gamepad listener died' when all died: {warning_messages}"
    )
