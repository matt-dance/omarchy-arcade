"""Chord recogniser for controller bindings.

Semantics (compatible with Omarchy Controller Control so users share one model):

* Bindings fire on press (or hold/repeat timers). A fired chord never fires its
  parts on release.
* When the held set could still grow into a longer binding, wait up to
  combo_window_ms. Otherwise fire immediately.
* A quick tap that could have started a longer chord fires on release if the
  window has not already produced a press-fire.
* Hold bindings fire after hold_ms; repeat bindings re-fire while held.
* A bare modifier with tap=True fires on release only if no chord used it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config import Binding


@dataclass(frozen=True)
class Activation:
    binding: Binding
    reason: str  # press | hold | repeat | tap


class ComboEngine:
    def __init__(self, bindings: Iterable[Binding], settings: dict):
        self.set_bindings(list(bindings), settings)
        self.held: set[str] = set()
        self._pending: tuple[Binding, float] | None = None
        self._latched: frozenset[str] | None = None
        self._hold_deadline: float | None = None
        self._hold_binding: Binding | None = None
        self._repeat_at: float | None = None
        self._repeat_binding: Binding | None = None
        self._tap_candidate: Binding | None = None
        self._chord_used_modifier = False

    def set_bindings(self, bindings: list[Binding], settings: dict) -> None:
        self.bindings = [b for b in bindings if b.enabled]
        self.combo_window = float(settings.get("combo_window_ms", 45)) / 1000.0
        self.hold_time = float(settings.get("hold_ms", 800)) / 1000.0
        self.repeat_delay = float(settings.get("repeat_delay_ms", 400)) / 1000.0
        self.repeat_interval = float(settings.get("repeat_interval_ms", 110)) / 1000.0
        self.modifier = str(settings.get("modifier", "GUIDE")).upper()
        self._combos = [frozenset(b.combo) for b in self.bindings]

    def reset(self) -> None:
        self.held.clear()
        self._pending = None
        self._latched = None
        self._hold_deadline = None
        self._hold_binding = None
        self._repeat_at = None
        self._repeat_binding = None
        self._tap_candidate = None
        self._chord_used_modifier = False

    def next_deadline(self) -> float | None:
        deadlines = [
            d
            for d in (
                self._pending[1] if self._pending else None,
                self._hold_deadline,
                self._repeat_at,
            )
            if d is not None
        ]
        return min(deadlines) if deadlines else None

    def _best_match(self, button: str) -> Binding | None:
        held = frozenset(self.held)
        candidates = [
            (binding, combo)
            for binding, combo in zip(self.bindings, self._combos)
            if button in combo and combo <= held and not binding.tap
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: len(item[1]))[0]

    def _could_grow(self, binding: Binding) -> bool:
        combo = frozenset(binding.combo)
        return any(combo < other for other in self._combos)

    def _tap_binding_for(self, button: str) -> Binding | None:
        for binding in self.bindings:
            if binding.tap and binding.combo == (button,):
                return binding
        return None

    def _fire(self, binding: Binding, reason: str, now: float) -> list[Activation]:
        if self.modifier in binding.combo and len(binding.combo) > 1:
            self._chord_used_modifier = True
            self._tap_candidate = None
        self._latched = frozenset(binding.combo)
        self._pending = None
        activations = [Activation(binding, reason)]
        hold_ms = binding.hold_ms if binding.hold_ms is not None else int(self.hold_time * 1000)
        if binding.hold and reason == "press":
            # Hold bindings don't fire on press — schedule hold instead.
            activations = []
            self._hold_binding = binding
            self._hold_deadline = now + (hold_ms / 1000.0)
            self._latched = None
            return activations
        if binding.repeat:
            self._repeat_binding = binding
            self._repeat_at = now + self.repeat_delay
        else:
            self._repeat_binding = None
            self._repeat_at = None
        return activations

    def on_press(self, button: str, now: float) -> list[Activation]:
        self.held.add(button)
        if self._latched and button in self._latched:
            return []

        if button == self.modifier:
            self._chord_used_modifier = False
            self._tap_candidate = self._tap_binding_for(button)

        match = self._best_match(button)
        if match is None:
            return []

        if self._could_grow(match):
            self._pending = (match, now + self.combo_window)
            if match.hold:
                hold_ms = match.hold_ms if match.hold_ms is not None else int(self.hold_time * 1000)
                self._hold_binding = match
                self._hold_deadline = now + (hold_ms / 1000.0)
            return []

        return self._fire(match, "press", now)

    def on_release(self, button: str, now: float) -> list[Activation]:
        activations: list[Activation] = []
        was_held = button in self.held
        self.held.discard(button)

        if self._latched and button in self._latched:
            self._latched = None
            self._repeat_binding = None
            self._repeat_at = None

        if self._hold_binding and button in self._hold_binding.combo:
            self._hold_deadline = None
            self._hold_binding = None

        if (
            self._pending
            and button in self._pending[0].combo
            and was_held
            and frozenset(self._pending[0].combo) <= (self.held | {button})
        ):
            # Quick tap of a chord that was waiting on the window
            pending_binding = self._pending[0]
            self._pending = None
            if not pending_binding.hold:
                activations.extend(self._fire(pending_binding, "press", now))

        if (
            button == self.modifier
            and self._tap_candidate
            and not self._chord_used_modifier
            and was_held
        ):
            activations.append(Activation(self._tap_candidate, "tap"))
        if button == self.modifier:
            self._tap_candidate = None
            self._chord_used_modifier = False

        return activations

    def tick(self, now: float) -> list[Activation]:
        activations: list[Activation] = []
        if self._pending and now >= self._pending[1]:
            binding = self._pending[0]
            if frozenset(binding.combo) <= frozenset(self.held):
                activations.extend(self._fire(binding, "press", now))
            else:
                self._pending = None

        if self._hold_binding and self._hold_deadline is not None and now >= self._hold_deadline:
            binding = self._hold_binding
            self._hold_deadline = None
            self._hold_binding = None
            if frozenset(binding.combo) <= frozenset(self.held):
                activations.extend(self._fire(binding, "hold", now))

        if self._repeat_binding and self._repeat_at is not None and now >= self._repeat_at:
            if frozenset(self._repeat_binding.combo) <= frozenset(self.held):
                activations.append(Activation(self._repeat_binding, "repeat"))
                self._repeat_at = now + self.repeat_interval
            else:
                self._repeat_binding = None
                self._repeat_at = None

        return activations
