"""Home shelf, badges, playtime, and hero helpers."""

from __future__ import annotations

import unittest

from pathlib import Path

from arcade.home import (
    cache_stem,
    cover_url,
    format_last_played,
    format_playtime,
    has_play_on,
    hero_url,
    home_shelf,
    is_icon_only,
    is_small_art,
    lookup_meta,
    play_meta,
    play_on_choices,
    remember_meta,
    source_badges,
    source_label,
)
from arcade.meta.cache import cache_stem as meta_cache_stem, meta_json_path

ROOT = Path(__file__).resolve().parent.parent


class TestHomeShelf(unittest.TestCase):
    def test_recent_first_then_rest_by_title(self):
        games = [
            {"id": "c", "title": "Celeste", "sortTitle": "celeste"},
            {"id": "b", "title": "Hades", "sortTitle": "hades", "lastPlayed": "2026-01-01T00:00:00Z"},
            {"id": "a", "title": "Apex", "sortTitle": "apex", "lastPlayed": "2026-10-20T12:00:00Z"},
            {"id": "d", "title": "Dwarf Fortress", "sortTitle": "dwarf fortress"},
        ]
        shelf = home_shelf(games)
        self.assertEqual([g["id"] for g in shelf], ["a", "b", "c", "d"])

    def test_empty(self):
        self.assertEqual(home_shelf(None), [])
        self.assertEqual(home_shelf([]), [])

    def test_icon_only_games_stay_on_the_shelf(self):
        games = [
            {"id": "desktop:wow", "title": "World of Warcraft", "art": {"iconOnly": True, "cover": "file:///wow.png"}},
            {"id": "steam:1", "title": "Enshrouded", "art": {"cover": "file:///c.jpg"}},
        ]
        shelf = home_shelf(games)
        self.assertEqual({g["id"] for g in shelf}, {"desktop:wow", "steam:1"})


class TestBadgesAndPlayOn(unittest.TestCase):
    def test_source_and_play_on_badges(self):
        game = {
            "id": "steam:1",
            "source": "steam",
            "store": "steam",
            "alsoOn": [{"id": "gfn:2", "source": "gfn", "launch": {"kind": "desktop", "value": "/tmp/x"}}],
        }
        self.assertEqual(source_badges(game), ["Steam", "Play on GeForce NOW"])
        choices = play_on_choices(game)
        self.assertEqual(len(choices), 2)
        self.assertEqual(choices[1]["label"], "GeForce NOW")

    def test_store_badge_for_heroic(self):
        game = {"id": "heroic:gog:1", "source": "heroic", "store": "gog", "alsoOn": []}
        self.assertEqual(source_badges(game), ["Heroic", "GOG"])

    def test_steam_desktop_wrapper_hidden_from_play_on(self):
        game = {
            "id": "steam:1203620",
            "source": "steam",
            "alsoOn": [
                {
                    "id": "desktop:steam:1203620",
                    "source": "desktop",
                    "launch": {"kind": "desktop", "value": "/tmp/enshrouded.desktop"},
                    "track": {"steamAppId": 1203620},
                },
                {
                    "id": "gfn:gfn-107820252",
                    "source": "gfn",
                    "launch": {"kind": "desktop", "value": "/tmp/gfn.desktop"},
                },
            ],
        }
        self.assertEqual(source_badges(game), ["Steam", "Play on GeForce NOW"])
        choices = play_on_choices(game)
        self.assertEqual([c["source"] for c in choices], ["steam", "gfn"])
        self.assertTrue(has_play_on(game))
        wrapper_only = {
            "id": "steam:1",
            "source": "steam",
            "alsoOn": [
                {
                    "id": "desktop:foo",
                    "source": "desktop",
                    "launch": {"kind": "uri", "value": "steam://rungameid/1"},
                }
            ],
        }
        self.assertEqual(source_badges(wrapper_only), ["Steam"])
        self.assertFalse(has_play_on(wrapper_only))

    def test_source_label_case(self):
        self.assertEqual(source_label("Steam"), "Steam")
        self.assertEqual(source_label("gfn"), "GeForce NOW")


class TestMetaFilename(unittest.TestCase):
    def test_id_to_filename_stem(self):
        cases = {
            "steam:1203620": "steam_1203620",
            "gfn:gfn-107820252": "gfn_gfn-107820252",
            "desktop:wow": "desktop_wow",
            "steam:shortcut:123": "steam_shortcut_123",
        }
        for game_id, stem in cases.items():
            self.assertEqual(cache_stem(game_id), stem)
            self.assertEqual(meta_cache_stem(game_id), stem)
            self.assertTrue(str(meta_json_path(game_id)).endswith(f"{stem}.json"))

    def test_js_uses_the_same_mapping(self):
        js = (ROOT / "ArcadeModel.js").read_text(encoding="utf-8")
        self.assertIn('id.replace(/[^A-Za-z0-9._-]+/g, "_")', js)
        self.assertIn('"/meta/" + stem + ".json"', js)
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        self.assertIn("function metaFilePath", js)
        self.assertIn("root.focusedGame ? root.focusedGame.id", qml)
        self.assertIn("applyMetaStdout", qml)


class TestPlayMeta(unittest.TestCase):
    def test_last_played_wins(self):
        game = {"lastPlayed": "2026-10-20T21:14:00Z", "playtimeMinutes": 90}
        self.assertEqual(play_meta(game), "Last played Oct 20, 2026")
        self.assertEqual(format_last_played("2026-10-20T21:14:00Z"), "Oct 20, 2026")

    def test_playtime_fallback(self):
        self.assertEqual(format_playtime(12), "12 min")
        self.assertEqual(format_playtime(90), "1.5 h")
        self.assertEqual(format_playtime(600), "10 h")
        self.assertEqual(play_meta({"playtimeMinutes": 90}), "1.5 h played")
        self.assertEqual(play_meta({}), "")

    def test_art_urls(self):
        game = {"art": {"cover": "file:///c.jpg", "hero": "file:///h.jpg"}}
        self.assertEqual(hero_url(game), "file:///h.jpg")
        self.assertEqual(cover_url(game), "file:///c.jpg")
        self.assertEqual(hero_url({}), "")

    def test_icon_only_flag(self):
        self.assertTrue(is_icon_only({"art": {"iconOnly": True, "cover": "file:///i.png"}}))
        self.assertFalse(is_icon_only({"art": {"cover": "file:///c.jpg"}}))
        self.assertFalse(is_icon_only({}))

    def test_unfocused_card_prefers_meta_cover(self):
        game = {
            "id": "desktop:wow",
            "title": "World of Warcraft",
            "art": {"iconOnly": True, "cover": "file:///ba.png", "icon": "file:///ba.png"},
        }
        meta = {"id": "desktop:wow", "art": {"cover": "file:///meta/desktop_wow/cover.jpg"}}
        by_id = remember_meta({}, meta)
        found = lookup_meta(game, by_id)
        self.assertEqual(cover_url(game, found), "file:///meta/desktop_wow/cover.jpg")
        self.assertFalse(is_small_art(game, 0, 0, found))
        self.assertTrue(is_small_art(game, 0, 0, None))
        self.assertEqual(cover_url(game, None), "file:///ba.png")
        other = {"id": "desktop:battle.net", "art": {"iconOnly": True, "cover": "file:///ba.png"}}
        self.assertIsNone(lookup_meta(other, by_id))
        self.assertTrue(is_small_art(other, 0, 0, lookup_meta(other, by_id)))


if __name__ == "__main__":
    unittest.main()
