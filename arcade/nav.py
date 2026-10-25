"""UI navigation from the D-pad and the left stick, with hold-to-repeat.

Both inputs feed one repeater so a held D-pad and a tilted stick never emit
interleaved directions. The most recent direction wins; releasing it falls
back to any direction still held.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DPAD_DIRS = {
    "DPAD_UP": "up",
    "DPAD_DOWN": "down",
    "DPAD_LEFT": "left",
    "DPAD_RIGHT": "right",
}


@dataclass
class NavRepeater:
    repeat_delay: float = 0.4
    repeat_interval: float = 0.11
    # source ("dpad" / "stick:<path>") -> direction, in press order
    _held: dict[str, str] = field(default_factory=dict)
    _active: tuple[str, str] | None = None
    _next_at: float | None = None

    def configure(self, settings: dict) -> None:
        self.repeat_delay = float(settings.get("repeat_delay_ms", 400)) / 1000.0
        self.repeat_interval = max(0.03, float(settings.get("repeat_interval_ms", 110)) / 1000.0)

    def reset(self) -> None:
        self._held.clear()
        self._active = None
        self._next_at = None

    def press(self, source: str, direction: str, now: float) -> str | None:
        """Start (or switch) a held direction. Returns the direction to emit now."""
        if self._held.get(source) == direction:
            return None
        self._held.pop(source, None)
        self._held[source] = direction
        self._active = (source, direction)
        self._next_at = now + self.repeat_delay
        return direction

    def release(self, source: str, now: float) -> None:
        if source not in self._held:
            return
        del self._held[source]
        if self._active and self._active[0] == source:
            if self._held:
                last_source = next(reversed(self._held))
                self._active = (last_source, self._held[last_source])
                self._next_at = now + self.repeat_delay
            else:
                self._active = None
                self._next_at = None

    def release_direction(self, source: str, direction: str, now: float) -> None:
        if self._held.get(source) == direction:
            self.release(source, now)

    def next_deadline(self) -> float | None:
        return self._next_at

    def tick(self, now: float) -> str | None:
        """Return a repeated direction when one is due."""
        if self._active is None or self._next_at is None or now < self._next_at:
            return None
        self._next_at = now + self.repeat_interval
        return self._active[1]


def stick_direction(x: float, y: float, deadzone: float) -> str | None:
    """Map a normalized stick position (-1..1, y down) to a direction or None."""
    ax, ay = abs(x), abs(y)
    if max(ax, ay) < deadzone:
        return None
    if ax >= ay:
        return "right" if x > 0 else "left"
    return "down" if y > 0 else "up"


def normalize_axis(value: int, lo: int, hi: int) -> float:
    """Scale a raw axis reading to -1..1 around the centre of [lo, hi]."""
    if hi <= lo:
        return 0.0
    centre = (lo + hi) / 2.0
    half = (hi - lo) / 2.0
    return max(-1.0, min(1.0, (value - centre) / half))
