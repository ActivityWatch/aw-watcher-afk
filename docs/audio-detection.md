# Audio-aware AFK detection (design note)

Status: prototype (Linux, opt-in). Tracks
[aw-watcher-afk#41](https://github.com/ActivityWatch/aw-watcher-afk/issues/41)
and [activitywatch#261](https://github.com/ActivityWatch/activitywatch/issues/261).

## Problem

AFK detection is driven purely by keyboard/mouse (and gamepad) input. Two
common cases are therefore mis-recorded:

- **Long calls / media without input.** Sitting in a video call (or watching a
  video) without touching input for `timeout` seconds is logged as AFK, even
  though the user is present.
- **Background media while away.** A browser tab streaming music keeps a
  *different* watcher "active"; a naive audio signal would repeat that mistake
  in the opposite direction.

## Two signals, two strengths

The two must not be conflated:

| Signal | Strength | Effect |
|---|---|---|
| Microphone capture in use | Strong — an active call means the user is present | May extend the not-AFK state |
| Audio output playing | Weak — may be background music while away | Reported only; never overrides AFK by default |

A **confirmed screen lock always wins**: capture may be a background recording,
so a locked session stays AFK even while the mic is in use.

## Per-OS APIs

- **Linux** (this prototype): PulseAudio/PipeWire via
  `pactl list short source-outputs` (recording streams) and
  `pactl list short sink-inputs` (playback streams). Monitor sources/sinks
  (`*.monitor`) are excluded — they are system-audio capture, not user
  activity. PipeWire-only systems without the PulseAudio compat layer
  (`pactl` absent) degrade to a no-op.
- **macOS** (future): CoreAudio
  `kAudioDevicePropertyDeviceIsRunningSomewhere`, or the TCC mic-in-use
  indicator; playback via `IAudioSessionManager2`-equivalent / CoreAudio
  running state.
- **Windows** (future): microphone use from
  `HKCU\...\CapabilityAccessManager\ConsentStore\microphone` `LastUsedTimeStart` /
  `LastUsedTimeStop` (Windows 10 1903+); playback via
  `IAudioSessionManager2` / `IAudioMeterInformation`.

## Privacy

Only stream **metadata** is read: a boolean "is there an active non-monitor
stream". No audio content, no device names beyond what `pactl` already prints on
the user's own machine, and no new OS permission beyond what the platform
already exposes to the user's own session. The feature is **opt-in and off by
default**.

## Configuration

```toml
[aw-watcher-afk]
detect_mic = false            # mic in use extends not-AFK (Linux)
detect_audio_playback = false # report playback state in the log (Linux)
```

Equivalent flags: `--detect-mic`, `--detect-audio-playback`.

## Behavior

- While `detect_mic` is on and a non-monitor source has an active stream, the
  watcher stays not-AFK even past `timeout`. When returning from AFK, the event
  is anchored at the moment capture was first observed, so the whole call is
  counted as present rather than just from the last input event.
- A locked session ignores the mic signal until unlock; on unlock with the mic
  still in use, presence resumes at unlock time (it must not back-date into the
  locked interval).
- With `detect_audio_playback`, playback transitions are logged only. Wiring
  playback into the event stream (e.g. a `data` flag or a separate bucket) is a
  follow-up, deliberately out of scope for this prototype.

## Known limitations

- A *corked* (paused) recording stream still counts as "in use"; distinguishing
  it needs `pactl list source-outputs` (verbose) and is left as a follow-up.
- An app holding the mic open in the background (e.g. a voice assistant) will
  keep the user marked present. This is the same trade-off #41 accepts for the
  "mic = strong signal" direction, and why the feature is opt-in.
- Linux only for now; `pactl` is resolved from `$PATH` and its absence is a
  silent no-op.
