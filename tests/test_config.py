"""Tests for arcade.toml loading and binding parse."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arcade.config import load_config, parse_combo


FIXTURES = Path(__file__).parent / "fixtures"


class TestParseCombo(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(parse_combo("GUIDE + A"), ("GUIDE", "A"))
        self.assertEqual(parse_combo("ps + cross"), ("GUIDE", "A"))
        self.assertEqual(parse_combo("SELECT + START"), ("SELECT", "START"))

    def test_unknown(self):
        with self.assertRaises(ValueError):
            parse_combo("GUIDE + Q")


class TestLoadConfig(unittest.TestCase):
    def test_defaults(self):
        root = Path(__file__).resolve().parent.parent
        cfg = load_config(plugin_dir=root, user_path=Path("/nonexistent"))
        self.assertTrue(any(b.action == "arcade.toggle" for b in cfg.bindings))
        guide_tap = [b for b in cfg.bindings if b.tap and b.combo == ("GUIDE",)]
        self.assertEqual(len(guide_tap), 1)
        self.assertEqual(guide_tap[0].action, "arcade.quick_menu")

    def test_user_override_and_disable(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp) / "arcade.toml"
            user.write_text(
                '''
                [input]
                hold_ms = 1000
                [bindings]
                "GUIDE + Y" = false
                "GUIDE + X" = { action = "arcade.cheat_sheet", description = "override" }
                ''',
                encoding="utf-8",
            )
            cfg = load_config(plugin_dir=root, user_path=user)
            self.assertEqual(cfg.input["hold_ms"], 1000)
            self.assertFalse(any(b.combo == ("GUIDE", "Y") for b in cfg.bindings))
            cheat = [b for b in cfg.bindings if b.combo == ("GUIDE", "X")]
            self.assertEqual(len(cheat), 1)
            self.assertEqual(cheat[0].action, "arcade.cheat_sheet")

    def test_bad_binding_reports_error(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp) / "arcade.toml"
            user.write_text(
                '''
                [bindings]
                "GUIDE + Q" = { action = "arcade.toggle" }
                "GUIDE + A" = { action = "not.a.thing" }
                ''',
                encoding="utf-8",
            )
            cfg = load_config(plugin_dir=root, user_path=user)
            self.assertTrue(cfg.errors)
            self.assertTrue(any("unknown button" in e for e in cfg.errors))
            self.assertTrue(any("unknown action" in e for e in cfg.errors))
            # Defaults still load
            self.assertTrue(cfg.bindings)


if __name__ == "__main__":
    unittest.main()
