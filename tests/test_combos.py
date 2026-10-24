"""Tests for the chord / combo engine."""

from __future__ import annotations

import unittest

from arcade.combos import ComboEngine
from arcade.config import Binding


def B(combo, **kwargs):
    return Binding(combo=tuple(combo.split("+")) if isinstance(combo, str) else tuple(combo), **kwargs)


class TestComboEngine(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "modifier": "GUIDE",
            "combo_window_ms": 45,
            "hold_ms": 800,
            "repeat_delay_ms": 400,
            "repeat_interval_ms": 110,
        }

    def test_simple_chord_fires_on_press(self):
        engine = ComboEngine(
            [B("GUIDE+START", action="arcade.toggle")],
            self.settings,
        )
        self.assertEqual(engine.on_press("GUIDE", 0.0), [])
        acts = engine.on_press("START", 0.01)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].binding.action, "arcade.toggle")
        self.assertEqual(acts[0].reason, "press")

    def test_longer_chord_wins(self):
        engine = ComboEngine(
            [
                B("GUIDE+SELECT", action="arcade.cheat_sheet"),
                B("GUIDE+SELECT+START", action="game.force_quit", hold=True, hold_ms=2000),
            ],
            self.settings,
        )
        engine.on_press("GUIDE", 0.0)
        engine.on_press("SELECT", 0.01)
        # Could still grow — pending
        self.assertEqual(engine.on_press("START", 0.02), [])
        # Hold fires later
        acts = engine.tick(2.03)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].binding.action, "game.force_quit")
        self.assertEqual(acts[0].reason, "hold")

    def test_a_and_a_plus_b_coexist(self):
        engine = ComboEngine(
            [
                B("A", action="arcade.toggle"),
                B("A+B", action="game.close"),
            ],
            self.settings,
        )
        # Tap A alone: pending then release fires
        self.assertEqual(engine.on_press("A", 0.0), [])
        acts = engine.on_release("A", 0.02)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].binding.action, "arcade.toggle")

        engine.reset()
        engine.on_press("A", 1.0)
        acts = engine.on_press("B", 1.01)
        # A+B cannot grow further — fires immediately
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].binding.action, "game.close")

    def test_guide_tap(self):
        engine = ComboEngine(
            [
                B("GUIDE", action="arcade.quick_menu", tap=True),
                B("GUIDE+START", action="arcade.toggle"),
            ],
            self.settings,
        )
        engine.on_press("GUIDE", 0.0)
        acts = engine.on_release("GUIDE", 0.05)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].reason, "tap")
        self.assertEqual(acts[0].binding.action, "arcade.quick_menu")

    def test_guide_tap_suppressed_by_chord(self):
        engine = ComboEngine(
            [
                B("GUIDE", action="arcade.quick_menu", tap=True),
                B("GUIDE+START", action="arcade.toggle"),
            ],
            self.settings,
        )
        engine.on_press("GUIDE", 0.0)
        acts = engine.on_press("START", 0.01)
        self.assertEqual(acts[0].binding.action, "arcade.toggle")
        acts = engine.on_release("START", 0.02)
        self.assertEqual(acts, [])
        acts = engine.on_release("GUIDE", 0.03)
        self.assertEqual(acts, [])

    def test_hold(self):
        engine = ComboEngine(
            [B("GUIDE+B", action="game.close", hold=True, hold_ms=800)],
            self.settings,
        )
        engine.on_press("GUIDE", 0.0)
        self.assertEqual(engine.on_press("B", 0.01), [])
        self.assertEqual(engine.tick(0.5), [])
        acts = engine.tick(0.82)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].reason, "hold")

    def test_hold_cancelled_on_release(self):
        engine = ComboEngine(
            [B("GUIDE+B", action="game.close", hold=True, hold_ms=800)],
            self.settings,
        )
        engine.on_press("GUIDE", 0.0)
        engine.on_press("B", 0.01)
        engine.on_release("B", 0.1)
        self.assertEqual(engine.tick(1.0), [])

    def test_repeat(self):
        engine = ComboEngine(
            [B("GUIDE+DPAD_UP", exec="vol+", repeat=True)],
            self.settings,
        )
        engine.on_press("GUIDE", 0.0)
        acts = engine.on_press("DPAD_UP", 0.01)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].reason, "press")
        self.assertEqual(engine.tick(0.2), [])
        acts = engine.tick(0.42)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].reason, "repeat")
        acts = engine.tick(0.53)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].reason, "repeat")


if __name__ == "__main__":
    unittest.main()
