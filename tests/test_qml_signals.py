"""Regression: QML custom signals must not collide with property *Changed."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PROP_RE = re.compile(
    r"^\s*(?:readonly\s+)?property\s+\S+\s+(\w+)\b",
    re.MULTILINE,
)
_SIGNAL_RE = re.compile(r"^\s*signal\s+(\w+)\s*\(", re.MULTILINE)


class TestQmlSignals(unittest.TestCase):
    def test_no_property_change_signal_collisions(self):
        qml_files = list(ROOT.glob("*.qml")) + list((ROOT / "screens").glob("*.qml")) + list(
            (ROOT / "ui").glob("*.qml")
        )
        self.assertTrue(any(p.name == "Service.qml" for p in qml_files))
        collisions: list[str] = []
        for path in qml_files:
            text = path.read_text(encoding="utf-8")
            props = set(_PROP_RE.findall(text))
            signals = set(_SIGNAL_RE.findall(text))
            for prop in props:
                auto = f"{prop}Changed"
                if auto in signals:
                    collisions.append(f"{path.name}: signal {auto}() collides with property {prop}")
        self.assertEqual(collisions, [])

    def test_service_keeps_custom_library_and_session_signals(self):
        text = (ROOT / "Service.qml").read_text(encoding="utf-8")
        signals = set(_SIGNAL_RE.findall(text))
        self.assertIn("libraryChanged", signals)
        self.assertIn("sessionChanged", signals)
        self.assertNotIn("padsChanged", signals)
        self.assertIn("property var pads", text)

    def test_manifest_has_no_panel_kind(self):
        # Omarchy computePanelEntries() prefers panel over overlay. Declaring
        # both made Super+Ctrl+G open QuickMenu.qml instead of Arcade.qml.
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("overlay", manifest["kinds"])
        self.assertNotIn("panel", manifest["kinds"])
        self.assertNotIn("panel", manifest.get("entryPoints", {}))
        self.assertEqual(manifest["entryPoints"]["overlay"], "Arcade.qml")


if __name__ == "__main__":
    unittest.main()
