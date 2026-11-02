"""Tests for [appearance] parse, persist, and overlay wiring."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arcade.appearance import replace_table, set_appearance
from arcade.config import load_config

ROOT = Path(__file__).resolve().parent.parent


class TestAppearanceWrite(unittest.TestCase):
    def test_replace_table_preserves_other_sections(self):
        src = (
            "# keep me\n"
            "[input]\n"
            "hold_ms = 800\n"
            "\n"
            "[appearance]\n"
            "blur = true\n"
            "\n"
            "[sources]\n"
            "steam = true\n"
        )
        out = replace_table(src, "appearance", "blur = false\n")
        self.assertIn("# keep me", out)
        self.assertIn("[input]", out)
        self.assertIn("hold_ms = 800", out)
        self.assertIn("[sources]", out)
        self.assertIn("steam = true", out)
        self.assertIn("blur = false", out)
        self.assertEqual(out.count("[appearance]"), 1)

    def test_set_appearance_creates_user_file_and_round_trips(self):
        root = ROOT
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "arcade.toml"
            keys = Path(tmp) / "keys.json"
            keys.write_text('{"steamgriddb_api_key":"secret"}\n', encoding="utf-8")
            written = set_appearance(
                {"background_opacity": 0.35, "blur": False},
                user_path=path,
                plugin_dir=root,
            )
            self.assertEqual(written["background_opacity"], 0.35)
            self.assertFalse(written["blur"])
            self.assertTrue(written["dynamic_tint"])
            text = path.read_text(encoding="utf-8")
            self.assertIn("[appearance]", text)
            self.assertIn("background_opacity = 0.35", text)
            self.assertIn("blur = false", text)
            cfg = load_config(plugin_dir=root, user_path=path)
            self.assertEqual(cfg.appearance["background_opacity"], 0.35)
            self.assertFalse(cfg.appearance["blur"])
            self.assertEqual(keys.read_text(encoding="utf-8"), '{"steamgriddb_api_key":"secret"}\n')

    def test_set_appearance_does_not_touch_keys_json(self):
        src = (ROOT / "arcade" / "appearance.py").read_text(encoding="utf-8")
        cli = (ROOT / "bin" / "arcade-config").read_text(encoding="utf-8")
        self.assertNotIn("keys.json", src)
        self.assertNotIn("keys.json", cli)


class TestOverlayAppearanceWiring(unittest.TestCase):
    def test_overlay_uses_transparent_backdrop_and_namespace(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        backdrop = (ROOT / "ArcadeBackdrop.qml").read_text(encoding="utf-8")
        self.assertIn("ArcadeBackdrop", qml)
        self.assertIn("WlrLayershell.namespace: root.layerNamespace", qml)
        self.assertIn('readonly property string layerNamespace: "matt-dance-arcade"', qml)
        self.assertIn("root.appearance.backgroundOpacity", qml)
        self.assertIn("root.appearance.dynamicTint", qml)
        self.assertIn("function writeAppearance", qml)
        self.assertIn("function activateSettings", qml)
        self.assertIn("settingsRows", qml)
        self.assertIn("Hyprland blur", qml)
        self.assertIn("Dynamic game tint", qml)
        self.assertIn("bin/arcade-config", qml)
        self.assertIn("heroKen", qml)
        self.assertIn("homeCardGlow", qml)
        self.assertIn("applyLayerBlur", qml)
        self.assertIn("logLayerNamespace", qml)
        self.assertIn("bin/arcade-hypr", qml)
        self.assertIn("effectiveOpacity", qml)
        self.assertNotIn("steamgriddb_api_key", qml)
        self.assertIn("themeBackground", backdrop)
        self.assertIn("sourceSize.width: 48", backdrop)
        self.assertIn("grain.png", backdrop)
        self.assertIn("assets/grain.png", str(ROOT / "assets" / "grain.png"))
        self.assertTrue((ROOT / "assets" / "grain.png").is_file())

    def test_service_forwards_appearance(self):
        service = (ROOT / "Service.qml").read_text(encoding="utf-8")
        daemon = (ROOT / "arcade" / "daemon.py").read_text(encoding="utf-8")
        self.assertIn("property var appearance", service)
        self.assertIn("Model.appearanceFromAny(msg.appearance)", service)
        self.assertIn('"appearance": pub["appearance"]', daemon)

    def test_defaults_document_appearance(self):
        toml = (ROOT / "default" / "arcade.toml").read_text(encoding="utf-8")
        self.assertIn("[appearance]", toml)
        self.assertIn("background_opacity = 0.4", toml)
        self.assertIn("animations = \"full\"", toml)


class TestArcadeConfigCli(unittest.TestCase):
    def test_show_and_set(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "arcade.toml"
            show = subprocess.run(
                [sys.executable, str(ROOT / "bin" / "arcade-config"), "show",
                 "--plugin-dir", str(ROOT), "--path", str(path)],
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(show.stdout)
            self.assertEqual(data["appearance"]["background_opacity"], 0.4)
            subprocess.run(
                [sys.executable, str(ROOT / "bin" / "arcade-config"), "set",
                 "animations", "off", "--plugin-dir", str(ROOT), "--path", str(path)],
                capture_output=True,
                text=True,
                check=True,
            )
            again = subprocess.run(
                [sys.executable, str(ROOT / "bin" / "arcade-config"), "show",
                 "--plugin-dir", str(ROOT), "--path", str(path)],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.loads(again.stdout)["appearance"]["animations"], "off")
            self.assertIn("[appearance]", path.read_text(encoding="utf-8"))
