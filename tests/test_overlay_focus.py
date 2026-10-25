"""Static checks for overlay focus handling (QML can't run in CI)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestOverlayFocus(unittest.TestCase):
    def setUp(self):
        self.qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")

    def test_hover_never_moves_focus_on_enter(self):
        self.assertIsNone(re.search(r"onEntered:[^\n]*(selectedIndex|playOnIndex|detailButton)", self.qml))
        self.assertNotIn("onEntered: {", self.qml)
        self.assertIn("function pointerMoved(scenePos)", self.qml)
        self.assertIn("root.pointerMoved(mapToItem(null, mouse.x, mouse.y))", self.qml)

    def test_focus_follows_game_identity(self):
        self.assertIn("property string selectedGameId", self.qml)
        self.assertIn("function showTab(screen, tabId)", self.qml)
        self.assertIn("root.tabSelection[root.tabKey()]", self.qml)
        refresh = self.qml[self.qml.index("  function refreshList() {"):]
        refresh = refresh[: refresh.index("\n  }\n")]
        self.assertIn("root.selectedGameId", refresh)

    def test_empty_tabs_explain_themselves(self):
        self.assertIn("function emptyMessage()", self.qml)
        self.assertIn("No favorites yet.", self.qml)
        self.assertIn("text: root.emptyMessage()", self.qml)


if __name__ == "__main__":
    unittest.main()
