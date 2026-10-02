"""Best-effort detection of microphone capture and audio playback.

Linux only, built on PulseAudio/PipeWire's ``pactl`` when it is available.
Only stream *metadata* is read (which sources/sinks have an active stream);
no audio content is ever accessed.

The two signals are deliberately kept separate because they have very
different strengths:

* **Microphone in use** (an active call) is a strong signal that the user is
  present, and a candidate for extending the not-AFK state.
* **Audio output playing** is a weak signal (it may be background music), so
  it is reported but does not override the AFK state by default.

Every ``is_*`` method returns ``None`` when the query cannot be performed
(not Linux, no ``pactl``, or the command failed) so callers can fail safe.
"""

import logging
import platform
import shutil
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

# A hung pactl must never stall the watcher's poll loop.
_QUERY_TIMEOUT = 2.0


def _pactl_path() -> Optional[str]:
    if platform.system() != "Linux":
        return None
    return shutil.which("pactl")


def _parse_stream_targets(output: str) -> List[str]:
    """Return the source/sink name for each stream in ``pactl list short``.

    The short output of ``pactl list short source-outputs`` and
    ``... sink-inputs`` is tab-separated with the layout::

        <stream-index>  <driver>  <client-index>  <source-or-sink-name>  ...

    The **fourth** column (index 3) identifies the source (for a recording
    stream) or the sink (for a playback stream).  The third column
    (index 2) is a numeric client index, not a device name.

    Lines too short to parse still indicate that *a* stream exists, so they
    are returned as an empty target (which counts as a non-monitor stream).
    """
    targets: List[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = line.split("\t")
        targets.append(fields[3] if len(fields) >= 4 else "")
    return targets


def _has_non_monitor_stream(output: str) -> bool:
    """True if any stream targets a device that is not a monitor.

    Monitor sources/sinks (e.g. ``alsa_output....monitor``) represent system
    audio capture, not the microphone or real playback, so they must not be
    counted as user activity.
    """
    return any(".monitor" not in target for target in _parse_stream_targets(output))


def _run_pactl(pactl: str, kind: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [pactl, "list", "short", kind],
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("pactl %s query failed", kind, exc_info=True)
        return None
    if result.returncode != 0:
        logger.debug("pactl %s exited with %s", kind, result.returncode)
        return None
    return result.stdout


class AudioActivityDetector:
    """Queries ``pactl`` for active capture/playback streams.

    A ``pactl`` path can be injected for testing; otherwise it is resolved
    from ``$PATH`` on Linux.
    """

    def __init__(self, pactl: Optional[str] = None):
        self._pactl = pactl if pactl is not None else _pactl_path()

    def available(self) -> bool:
        return self._pactl is not None

    def _query(self, kind: str) -> Optional[str]:
        if self._pactl is None:
            return None
        return _run_pactl(self._pactl, kind)

    def is_microphone_in_use(self) -> Optional[bool]:
        """True while a non-monitor source has an active recording stream."""
        output = self._query("source-outputs")
        if output is None:
            return None
        return _has_non_monitor_stream(output)

    def is_audio_playing(self) -> Optional[bool]:
        """True while a non-monitor sink has an active playback stream."""
        output = self._query("sink-inputs")
        if output is None:
            return None
        return _has_non_monitor_stream(output)


_detector = AudioActivityDetector()


def is_microphone_in_use() -> Optional[bool]:
    return _detector.is_microphone_in_use()


def is_audio_playing() -> Optional[bool]:
    return _detector.is_audio_playing()
