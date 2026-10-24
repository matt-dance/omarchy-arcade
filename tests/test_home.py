"""Home shelf, badges, playtime, and hero helpers."""

from __future__ import annotations

import unittest

from arcade.home import (
    cover_url,
    format_last_played,
    format_playtime,
    hero_url,
    home_shelf,
    play_meta,
    play_on_choices,
    source_badges,
    source_label,
)


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

    def test_source_label_case(self):
        self.assertEqual(source_label("Steam"), "Steam")
        self.assertEqual(source_label("gfn"), "GeForce NOW")


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


if __name__ == "__main__":
    unittest.main()
