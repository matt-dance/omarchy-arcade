"""Overlay cache fallback + service lifecycle logging."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from arcade.model import parse_library_text, resolved_games

ROOT = Path(__file__).resolve().parent.parent


class TestParseLibraryText(unittest.TestCase):
    def test_empty_and_invalid(self):
        self.assertTrue(parse_library_text("")["empty"])
        self.assertTrue(parse_library_text(None)["empty"])
        bad = parse_library_text("{not json")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["games"], [])

    def test_reads_games_array(self):
        text = json.dumps(
            {
                "version": 1,
                "games": [{"id": "steam:1", "title": "Enshrouded"}, {"id": "gfn:2", "title": "Diablo IV"}],
                "errors": [],
            }
        )
        parsed = parse_library_text(text)
        self.assertTrue(parsed["ok"])
        self.assertEqual(len(parsed["games"]), 2)
        self.assertEqual(parsed["games"][0]["title"], "Enshrouded")

    def test_prefer_service_then_cache(self):
        cache = [{"id": "cached"}]
        self.assertEqual(resolved_games([{"id": "live"}], cache)[0]["id"], "live")
        self.assertEqual(resolved_games([], cache)[0]["id"], "cached")
        self.assertEqual(resolved_games(None, cache)[0]["id"], "cached")
        self.assertEqual(resolved_games(None, None), [])


class TestOverlayAndServiceSources(unittest.TestCase):
    def test_overlay_has_independent_cache_and_scan(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        js = (ROOT / "ArcadeModel.js").read_text(encoding="utf-8")
        self.assertIn("FileView", qml)
        self.assertIn("localGames", qml)
        self.assertIn("startLocalScan", qml)
        self.assertIn("loadLibraryFromDisk", qml)
        self.assertIn("library.json", qml)
        self.assertIn("/usr/bin/python3", qml)
        self.assertIn("omarchy-restart-shell", qml)
        self.assertIn("function parseLibraryText", js)
        self.assertIn("function resolvedGames", js)
        self.assertIn("function libraryFilePath", js)
        self.assertIn("function homeShelf", js)
        self.assertIn("function sourceBadges", js)
        self.assertIn("function alsoOnIsWrapper", js)
        self.assertIn("function isIconOnly", js)
        self.assertIn("function isSmallArt", js)
        self.assertIn("function hasPlayOn", js)
        self.assertIn("homeRow", qml)
        self.assertIn("focusZone", qml)
        self.assertIn("menuPinned", qml)
        self.assertIn('surface === "quickmenu"', qml)
        self.assertIn("showQuickMenu", qml)
        self.assertIn("persistQuickMenu", qml)
        self.assertIn("Image.Pad", qml)
        self.assertIn("isSmallArt", qml)
        self.assertIn("Do not set sourceSize", qml)

    def test_show_quick_menu_logs_and_persists(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        service = (ROOT / "Service.qml").read_text(encoding="utf-8")
        menu = (ROOT / "QuickMenu.qml").read_text(encoding="utf-8")
        self.assertIn('matt-dance.arcade: showQuickMenu persist=', qml)
        self.assertIn('matt-dance.arcade: open surface=quickmenu persist=', qml)
        self.assertIn('{"surface":"quickmenu","persist":true}', qml)
        self.assertIn("system menu stays pinned", qml)
        self.assertIn("summonQuickMenu", service)
        self.assertIn("persistQuickMenu", service)
        self.assertIn("service showQuickMenu", service)
        self.assertIn("openQuickMenu", service)
        self.assertIn("re-summoning system menu", service)
        self.assertIn("QuickMenu.open", menu)
        self.assertIn("signal dismissed", menu)

    def test_service_logs_and_starts_arcaded_via_python(self):
        qml = (ROOT / "Service.qml").read_text(encoding="utf-8")
        self.assertIn('matt-dance.arcade:', qml)
        self.assertIn("service loaded", qml)
        self.assertIn("starting arcaded", qml)
        self.assertIn("arcaded hello", qml)
        self.assertIn("arcaded exited", qml)
        self.assertIn("/usr/bin/python3", qml)
        self.assertIn("will retry", qml)

    def test_readme_documents_shell_restart(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("omarchy-restart-shell", readme)
        self.assertIn("journalctl --user", readme)
        self.assertIn("Recovering a dead service", readme)


class TestArcadedBanner(unittest.TestCase):
    def test_stderr_announces_start(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "arcaded"), "--plugin-dir", str(ROOT), "--exit-with-stdin"],
            input="",
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        self.assertIn("matt-dance.arcade: arcaded starting", proc.stderr)


if __name__ == "__main__":
    unittest.main()
