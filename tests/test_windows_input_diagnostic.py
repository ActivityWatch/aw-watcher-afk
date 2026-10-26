"""Pure diagnostic tests; no Windows hooks or display required."""

import importlib.util
import json
from pathlib import Path
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch


spec = importlib.util.spec_from_file_location(
    "diagnostic", Path(__file__).parents[1] / "misc" / "windows_input_diagnostic.py"
)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


class DiagnosticTests(unittest.TestCase):
    def test_keyboard_injection_bits(self):
        self.assertEqual(diagnostic.classify("keyboard", 0), "unflagged")
        self.assertEqual(diagnostic.classify("keyboard", 0x10), "injected")
        self.assertEqual(
            diagnostic.classify("keyboard", 0x12), "lower_integrity_injected"
        )
        self.assertEqual(diagnostic.classify("keyboard", 0x80), "unflagged")

    def test_mouse_injection_bits_differ(self):
        self.assertEqual(diagnostic.classify("mouse", 1), "injected")
        self.assertEqual(diagnostic.classify("mouse", 3), "lower_integrity_injected")
        self.assertEqual(diagnostic.classify("mouse", 0x10), "unflagged")

    def test_idle_wraparound_matches_windows_backend(self):
        self.assertEqual(diagnostic.idle_ms(2**32 + 25, 2**32 - 25), 50)
        self.assertEqual(diagnostic.idle_ms(5000, 3000), 2000)

    def test_counter_snapshot_is_interval_only(self):
        counts = diagnostic.EventCounts()
        counts.observe("mouse", 1)
        counts.observe("keyboard", 0)
        first = counts.snapshot()
        self.assertEqual(first["mouse_injected"], 1)
        self.assertEqual(first["keyboard_unflagged"], 1)
        self.assertTrue(all(value == 0 for value in counts.snapshot().values()))

    def test_idle_change_is_not_causality(self):
        counts = diagnostic.EventCounts()
        row = diagnostic.sample_row(1.0, 5000, 4900, 3000, counts.snapshot())
        self.assertEqual(row["idle_ms"], 100)
        self.assertTrue(row["last_input_tick_changed"])
        self.assertTrue(all(value == 0 for value in row["events"].values()))
        self.assertIsNone(
            diagnostic.sample_row(0, 5000, 4900, None, {})["last_input_tick_changed"]
        )
        self.assertNotIn("key", row)
        self.assertNotIn("coordinates", row)


class NativeLifecycleTests(unittest.TestCase):
    """API doubles exercise control flow, not Windows ABI/hook delivery."""

    def run_native(
        self,
        fail_hook=0,
        fail_query=False,
        callback_failure=False,
        interrupt=False,
        interrupt_on_pass=False,
        deliver_events=False,
        late_callback_failure=False,
        pass_through_failure=False,
    ):
        api = SimpleNamespace()
        api.SetWindowsHookExW = Mock(
            side_effect=[101, 0] if fail_hook == 2 else [101, 102]
        )
        api.UnhookWindowsHookEx = Mock(return_value=1)
        api.CallNextHookEx = Mock(
            side_effect=KeyboardInterrupt if interrupt_on_pass else None,
            return_value=99,
        )
        api.SetTimer = Mock(return_value=77)
        api.KillTimer = Mock(return_value=1)
        api.TranslateMessage = Mock(return_value=1)
        api.DispatchMessageW = Mock(return_value=0)
        api.GetLastInputInfo = Mock(return_value=not fail_query)
        api.GetMessageW = Mock(return_value=0)
        # Deterministic clock: the message loop's real-monotonic deadline must
        # not depend on wall-clock time under a loaded test runner.
        clock = {"now": 0.0}
        kernel = SimpleNamespace(
            GetTickCount64=Mock(return_value=5000),
            GetModuleHandleW=Mock(return_value=1),
        )
        output = StringIO()
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    diagnostic.ctypes, "WinDLL", side_effect=[api, kernel], create=True
                )
            )
            stack.enter_context(
                patch.object(
                    diagnostic.ctypes,
                    "WINFUNCTYPE",
                    return_value=lambda fn: fn,
                    create=True,
                )
            )
            stack.enter_context(
                patch.object(
                    diagnostic.ctypes, "get_last_error", return_value=5, create=True
                )
            )
            stack.enter_context(
                patch.object(
                    diagnostic.ctypes,
                    "WinError",
                    side_effect=lambda code: OSError(code),
                    create=True,
                )
            )
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(
                patch.object(
                    diagnostic,
                    "time",
                    SimpleNamespace(monotonic=lambda: clock["now"]),
                )
            )
            if callback_failure or interrupt:

                def deliver(msg, *args):
                    clock["now"] += 0.1
                    callback = api.SetWindowsHookExW.call_args_list[0].args[1]
                    # A classification exception must never suppress the event.
                    with patch.object(
                        diagnostic.ctypes,
                        "cast",
                        side_effect=KeyboardInterrupt if interrupt else ValueError,
                    ):
                        self.assertEqual(callback(0, 0, 0), 99)
                    # A negative hook code must pass straight through.
                    self.assertEqual(callback(-1, 0, 0), 99)
                    msg._obj.message = 0x0113
                    msg._obj.wParam = 77
                    return 1

                api.GetMessageW.side_effect = deliver
            elif interrupt_on_pass:

                def deliver(msg, *args):
                    clock["now"] += 0.1
                    callback = api.SetWindowsHookExW.call_args_list[0].args[1]
                    # Cancellation can surface on the pass-through call's return;
                    # it must be contained, not escape the ctypes callback.
                    try:
                        result = callback(-1, 0, 0)
                    except KeyboardInterrupt:
                        self.fail("KeyboardInterrupt escaped the ctypes callback")
                    self.assertEqual(result, 0)
                    msg._obj.message = 0x0113
                    msg._obj.wParam = 77
                    return 1

                api.GetMessageW.side_effect = deliver
            elif deliver_events:
                stack.enter_context(
                    patch.object(
                        diagnostic.ctypes,
                        "cast",
                        side_effect=[
                            SimpleNamespace(contents=SimpleNamespace(flags=0x00)),
                            SimpleNamespace(contents=SimpleNamespace(flags=0x01)),
                        ],
                        create=True,
                    )
                )
                pulses = [0]

                def deliver(msg, *args):
                    clock["now"] += 0.1
                    if pulses[0] >= 2:
                        return 0
                    if pulses[0] == 0:
                        # Successful events must reach the next emitted row.
                        keyboard = api.SetWindowsHookExW.call_args_list[0].args[1]
                        mouse = api.SetWindowsHookExW.call_args_list[1].args[1]
                        self.assertEqual(keyboard(0, 0, 0), 99)
                        self.assertEqual(mouse(0, 0, 0), 99)
                    msg._obj.message = 0x0113
                    msg._obj.wParam = 77
                    pulses[0] += 1
                    return 1

                api.GetMessageW.side_effect = deliver
            elif pass_through_failure:
                api.CallNextHookEx.side_effect = ValueError

                def deliver(msg, *args):
                    clock["now"] += 0.1
                    callback = api.SetWindowsHookExW.call_args_list[0].args[1]
                    # A non-interrupt pass-through failure must be contained and
                    # deferred, never escape the ctypes callback boundary.
                    try:
                        result = callback(-1, 0, 0)
                    except Exception:
                        self.fail("exception escaped the ctypes callback")
                    self.assertEqual(result, 0)
                    msg._obj.message = 0x0113
                    msg._obj.wParam = 77
                    return 1

                api.GetMessageW.side_effect = deliver
            elif late_callback_failure:

                def deliver(msg, *args):
                    clock["now"] += 0.1
                    callback = api.SetWindowsHookExW.call_args_list[0].args[1]
                    # Fail after the last sample, then quit the loop cleanly.
                    with patch.object(
                        diagnostic.ctypes, "cast", side_effect=ValueError
                    ):
                        self.assertEqual(callback(0, 0, 0), 99)
                    return 0

                api.GetMessageW.side_effect = deliver
            error = None
            try:
                diagnostic.run(1)
            except (OSError, RuntimeError, KeyboardInterrupt) as exc:
                error = exc
        return api, output.getvalue(), error

    def test_normal_exit_removes_both_hooks_and_timer(self):
        api, output, error = self.run_native()
        self.assertIsNone(error)
        self.assertIn('"status": "hooks_installed"', output)
        self.assertEqual(
            [call.args[0] for call in api.UnhookWindowsHookEx.call_args_list],
            [102, 101],
        )
        api.KillTimer.assert_called_once_with(None, 77)

    def test_partial_hook_install_failure_removes_first_hook(self):
        api, output, error = self.run_native(fail_hook=2)
        self.assertIsInstance(error, OSError)
        self.assertEqual(output, "")
        api.UnhookWindowsHookEx.assert_called_once_with(101)
        api.KillTimer.assert_not_called()

    def test_idle_query_failure_cleans_up(self):
        api, output, error = self.run_native(fail_query=True)
        self.assertIsInstance(error, OSError)
        self.assertEqual(api.UnhookWindowsHookEx.call_count, 2)
        api.KillTimer.assert_called_once_with(None, 77)
        self.assertNotIn('"idle_ms"', output)

    def test_callback_failure_passes_input_and_fails_next_sample(self):
        api, output, error = self.run_native(callback_failure=True)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(api.CallNextHookEx.call_count, 2)
        self.assertEqual(api.UnhookWindowsHookEx.call_count, 2)
        api.KillTimer.assert_called_once_with(None, 77)

    def test_callback_interrupt_passes_input_before_cancellation(self):
        api, output, error = self.run_native(interrupt=True)
        self.assertIsInstance(error, KeyboardInterrupt)
        self.assertEqual(api.CallNextHookEx.call_count, 2)
        self.assertEqual(api.UnhookWindowsHookEx.call_count, 2)
        api.KillTimer.assert_called_once_with(None, 77)

    def test_interrupt_on_pass_through_stops_without_escaping(self):
        api, output, error = self.run_native(interrupt_on_pass=True)
        self.assertIsInstance(error, KeyboardInterrupt)
        self.assertEqual(api.UnhookWindowsHookEx.call_count, 2)
        api.KillTimer.assert_called_once_with(None, 77)

    def test_pass_through_failure_is_deferred_not_escaped(self):
        api, output, error = self.run_native(pass_through_failure=True)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(api.UnhookWindowsHookEx.call_count, 2)
        api.KillTimer.assert_called_once_with(None, 77)

    def test_callback_failure_after_final_sample_still_surfaces(self):
        api, output, error = self.run_native(late_callback_failure=True)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(api.UnhookWindowsHookEx.call_count, 2)
        api.KillTimer.assert_called_once_with(None, 77)

    def test_successful_event_lands_in_next_row_and_resets(self):
        api, output, error = self.run_native(deliver_events=True)
        self.assertIsNone(error)
        rows = [json.loads(line) for line in output.splitlines() if '"events"' in line]
        self.assertEqual(len(rows), 3)
        # First row is emitted before any hook event.
        self.assertEqual(rows[0]["events"]["keyboard_unflagged"], 0)
        # The successful event is counted in the row emitted at the timer pulse.
        self.assertEqual(rows[1]["events"]["keyboard_unflagged"], 1)
        self.assertEqual(rows[1]["events"]["mouse_injected"], 1)
        # Counts are interval-only: the following row resets to zero.
        self.assertTrue(all(value == 0 for value in rows[2]["events"].values()))


if __name__ == "__main__":
    unittest.main()
