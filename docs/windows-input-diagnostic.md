# Windows controller / unexpected activity diagnostic

Windows AFK status uses `GetLastInputInfo`, not the pynput listeners used on
Linux/macOS. This opt-in script compares that idle counter with aggregate
low-level mouse/keyboard injection flags. It does **not** change ActivityWatch,
suppress input, write to its server, or identify a controller as the cause.

## Run (Windows, Python 3.8+)

Download `misc/windows_input_diagnostic.py` from the diagnostic PR, or use this
checkout. The standalone script needs only Python's standard library; no watcher
installation or administrator privileges are required. Run in your normal
interactive Windows session (not a service or another user's session).

In PowerShell, from the directory containing the downloaded script:

```powershell
py -3 .\windows_input_diagnostic.py --duration 120
```

The script exits after 120 seconds. Ctrl+C also stops it and removes its hooks.
Duration is bounded to 1–600 seconds. Failed hook installation or idle queries
produce an error on stderr and a nonzero exit; do not interpret a failed run as
no activity. Avoid elevation: it changes which integrity levels you can observe.

## Comparison procedure

1. Record the actual Windows version/build (`winver`), ActivityWatch version,
   controller model and connection type, and any mapper/virtual-controller
   software you use (including its version). Do not assume a particular mapper.
2. With the controller **disconnected**, start a 120-second run. Move the mouse
   and press/release one harmless key at the start to confirm nonzero
   `mouse_unflagged` / `keyboard_unflagged` counts. Then leave mouse and keyboard
   untouched for at least 60 seconds. Do not type passwords during this test.
3. Repeat with the controller **connected but untouched**, using the same game
   and mapper state as when the problem occurs. Leave all input devices alone.
4. Optionally repeat with the game or mapper stopped, changing only one factor
   per run. Do not install/disable drivers merely for this test.
5. Share whether idle time grew during each idle period, whether it reset,
   and which event-count categories appeared near resets. Small output excerpts
   suffice. Include errors and whether the initial mouse/key check worked.

To retain output locally, append `> disconnected.jsonl` or `> connected.jsonl`
to the command. Stderr is intentionally separate so failures remain visible.
Review output before sharing; the observations reveal approximate activity timing.
The script never captures key values, text, cursor coordinates, window titles,
process names, device identifiers or raw event timestamps.

## Reading the output

One JSON row per approximately one-second interval contains:

- `elapsed_s`: monotonic elapsed time since this diagnostic started.
- `idle_ms`: the DWORD-wrap-safe difference between `GetTickCount64` and
  `GetLastInputInfo.dwTime`, matching the watcher's idle calculation.
- `last_input_tick_changed`: whether the idle API's last-input value changed
  since the previous sample (`null` for the first sample).
- `events`: counts of mouse and keyboard events since the previous sample,
  partitioned into `unflagged`, `injected` and `lower_integrity_injected`.
  Lower-integrity counts are exclusive, not counted again as ordinary injected.

An idle-counter change near injected events is correlation, not proof that a
controller produced those events. Accessibility tools, macro tools and remote
desktop can also inject legitimate input. **Unflagged does not prove physical
input**: a driver can synthesize unflagged activity. This does not observe raw
HID/gamepad events or identify the originating device/application.

An idle reset without hook counts is still useful evidence. Hooks may not see
input on other desktops/integrity levels, and Windows can silently remove a
slow low-level hook; successful installation does not prove continued coverage.
Avoid slow output pipes and do the harmless mouse/key check again near the end
of each run. A missing end check or missing counts makes hook coverage uncertain,
not proof of no input. Input messages may be sampled on opposite sides of an
interval boundary. `GetLastInputInfo` itself can return non-increasing tick
values; a changed value is not automatically a new physical input event.

## Verification limits

Pure tests cover flag classification, idle wraparound and interval aggregation.
The native integration requires an actual Windows run; Linux unit tests do not
validate Windows hook delivery or reproduce the reported Bluetooth problem.
Keep the production AFK backend unchanged until measured evidence supports a
specific repair. A blanket injected-input filter would also ignore legitimate
accessibility/remote-control activity and is not a controller-specific fix.
