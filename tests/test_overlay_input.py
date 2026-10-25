"""Static checks for overlay input wiring (QML can't run in CI)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestOverlayInput(unittest.TestCase):
    def setUp(self):
        self.qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")

    def test_osk_component_and_routing(self):
        osk = (ROOT / "Osk.qml").read_text(encoding="utf-8")
        for sig in ("signal typed", "signal backspace", "signal cleared", "signal done"):
            self.assertIn(sig, osk)
        self.assertIn("function move(dir)", osk)
        self.assertIn("function activate()", osk)
        self.assertIn("Osk {", self.qml)
        self.assertIn("osk.move(dir)", self.qml)
        self.assertIn("root.handleOskIntent(name)", self.qml)
        self.assertIn("root.openOsk()", self.qml)

    def test_search_field_forwards_navigation_keys(self):
        self.assertIn("function handleKey(event)", self.qml)
        self.assertIn("Keys.onPressed: function(event) { root.handleKey(event) }", self.qml)
        field = self.qml[self.qml.index("id: searchInput"):]
        field = field[: field.index("// Settings pane")]
        self.assertIn("Keys.onPressed", field)
        self.assertIn("Qt.Key_Return", field)
        self.assertIn("Qt.Key_Escape", field)
        self.assertIn("root.handleKey(event)", field)

    def test_s_key_is_not_swallowed(self):
        self.assertIsNone(re.search(r"Qt\.Key_S\b", self.qml))

    def test_meta_fetch_is_debounced(self):
        self.assertIn("id: metaDebounce", self.qml)
        self.assertIn("metaDebounce.restart()", self.qml)
        update = self.qml[self.qml.index("function updateFocused()"):]
        update = update[: update.index("function loadMetaFromDisk()")]
        self.assertNotIn("ensureMeta", update)

    def test_service_reloads_config_on_change(self):
        service = (ROOT / "Service.qml").read_text(encoding="utf-8")
        self.assertIn("omarchy/arcade/arcade.toml", service)
        self.assertIn('t: "reload"', service)


if __name__ == "__main__":
    unittest.main()
