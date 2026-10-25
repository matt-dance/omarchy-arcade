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

    def test_union_includes_cache_only_icon_games(self):
        cache = [
            {"id": "steam:1", "title": "Enshrouded"},
            {"id": "desktop:wow", "title": "World of Warcraft", "art": {"iconOnly": True}},
        ]
        live = [{"id": "steam:1", "title": "Enshrouded (live)"}]
        merged = resolved_games(live, cache)
        self.assertEqual([g["id"] for g in merged], ["steam:1", "desktop:wow"])
        self.assertEqual(merged[0]["title"], "Enshrouded")
        self.assertTrue(merged[1]["art"]["iconOnly"])
        self.assertEqual(resolved_games([], cache)[1]["id"], "desktop:wow")
        self.assertEqual(resolved_games(None, cache)[1]["id"], "desktop:wow")
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
        self.assertIn("function libraryEntries", js)
        self.assertIn("shelf=", qml)
        self.assertIn("cache=", qml)
        self.assertIn("function libraryFilePath", js)
        self.assertIn("function homeShelf", js)
        self.assertIn("function sourceBadges", js)
        self.assertIn("function alsoOnIsWrapper", js)
        self.assertIn("function isIconOnly", js)
        self.assertIn("function isSmallArt", js)
        self.assertIn("function hasMetaCover", js)
        self.assertIn("function lookupMeta", js)
        self.assertIn("function rememberMeta", js)
        self.assertIn("function rememberMetaMap", js)
        self.assertIn("hasMetaCover(meta)", js)
        self.assertIn("Model.lookupMeta(modelData, root.metaById)", qml)
        self.assertIn("metaById", qml)
        self.assertIn("loadCachedArt", qml)
        self.assertIn("--cached-art", qml)
        self.assertNotIn("index === root.selectedIndex ? root.selectedMeta : null", qml)
        self.assertNotIn("cover === game.art.icon", js)
        self.assertIn("function hasPlayOn", js)
        self.assertIn("homeRow", qml)
        self.assertIn("focusZone", qml)
        self.assertIn("menuPinned", qml)
        self.assertIn('surface === "quickmenu"', qml)
        self.assertIn("showQuickMenu", qml)
        self.assertIn("persistQuickMenu", qml)
        self.assertIn("Image.Pad", qml)
        self.assertIn("isSmallArt", qml)
        self.assertIn("clip: true", qml)
        self.assertIn("PreserveAspectCrop", qml)
        self.assertIn("function metaFilePath", js)
        self.assertIn("function parseMetaText", js)
        self.assertIn("function metaIsFresh", js)
        self.assertIn("function factsLine", js)
        self.assertIn("function protonLabel", js)
        self.assertIn("arcade-meta", qml)
        self.assertIn("selectedMeta", qml)
        self.assertIn("heroArt", qml)
        self.assertIn("homeDetail", qml)
        self.assertIn("BorderSurface", qml)
        self.assertIn("hyprlandActiveSpec", qml)
        self.assertIn("Border.flat", qml)
        self.assertIn("Commons.Color.accent", qml)
        self.assertIn("homeDetail.contentTopInset", qml)
        self.assertIn("homeDetailInner", qml)
        self.assertNotIn("#33ccff", qml)
        self.assertNotIn("rgba(33ccff", qml)
        self.assertIn("screenshots", qml)
        self.assertIn("chmod 600", qml)
        self.assertIn('text: "Play"', qml)
        self.assertIn('text: "Options"', qml)
        self.assertNotIn("steamgriddb_api_key", qml)

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
        self.assertIn("if (!text || !String(text).trim())", menu)

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

    def test_readme_documents_metadata_keys(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("~/.config/matt-dance.arcade/keys.json", readme)
        self.assertIn("chmod 600", readme)
        self.assertIn("steamgriddb_api_key", readme)
        self.assertIn("twitch_client_id", readme)
        self.assertIn("twitch_client_secret", readme)
        self.assertIn("ARCADE_STEAMGRIDDB_API_KEY", readme)
        self.assertIn("dev.twitch.tv/console/apps", readme)
        self.assertIn("steamgriddb.com/profile/preferences/api", readme)
        self.assertIn("arcade-meta", readme)
        arch = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("Game metadata", arch)
        self.assertIn("arcade-meta", arch)
        self.assertIn("hyprlandActiveSpec", arch)
        self.assertIn("Known launchers", arch)


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
