"""Scanner tests against fixtures."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arcade.model import merge_games
from arcade.scanners import bottles, desktop, heroic, itch, lutris, steam

FIXTURES = Path(__file__).parent / "fixtures"


class TestSteamScanner(unittest.TestCase):
    def test_manifests_and_tools_filtered(self):
        root = FIXTURES / "steam"
        with mock.patch("arcade.scanners.steam.steam_roots", return_value=[root]):
            games, errors = steam.scan()
        self.assertEqual(errors, [])
        ids = {g.id for g in games}
        self.assertIn("steam:570", ids)
        self.assertIn("steam:1245620", ids)
        self.assertNotIn("steam:228980", ids)
        elden = next(g for g in games if g.id == "steam:1245620")
        self.assertEqual(elden.title, "ELDEN RING")
        self.assertEqual(elden.launch.value, "steam://rungameid/1245620")
        self.assertEqual(elden.track.window_class, "steam_app_1245620")


class TestDesktopScanner(unittest.TestCase):
    def test_gfn_and_native_skip_steam_launcher(self):
        apps = FIXTURES / "applications"
        with mock.patch("arcade.scanners.desktop.application_dirs", return_value=[apps]):
            games, errors = desktop.scan()
        self.assertEqual(errors, [])
        ids = {g.id for g in games}
        self.assertTrue(any(g.source == "gfn" for g in games))
        gfn = next(g for g in games if g.source == "gfn")
        self.assertEqual(gfn.title, "Diablo IV")
        self.assertEqual(gfn.runner, "cloud")
        self.assertIn("desktop:super-meat-boy", ids)
        # Bare Steam launcher skipped
        self.assertFalse(any("steam" == g.id.split(":")[-1] for g in games if g.source == "desktop"))


class TestHeroicScanner(unittest.TestCase):
    def test_epic_and_gog(self):
        root = FIXTURES / "heroic"
        with mock.patch("arcade.scanners.heroic.heroic_roots", return_value=[root]):
            games, errors = heroic.scan()
        self.assertEqual(errors, [])
        titles = {g.title for g in games}
        self.assertIn("Apex Legends", titles)
        self.assertIn("The Witcher 3: Wild Hunt", titles)
        self.assertNotIn("Fortnite", titles)
        witcher = next(g for g in games if "Witcher" in g.title)
        self.assertEqual(witcher.store, "gog")
        self.assertIn("heroic://launch?", witcher.launch.value)


class TestLutrisScanner(unittest.TestCase):
    def test_pga_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            db = data_dir / "pga.db"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE games (id INTEGER, name TEXT, slug TEXT, runner TEXT, installed INTEGER, directory TEXT)"
            )
            conn.execute(
                "INSERT INTO games VALUES (1, 'Hades', 'hades', 'wine', 1, '/games/hades')"
            )
            conn.execute(
                "INSERT INTO games VALUES (2, 'Hidden', 'hidden', 'wine', 0, '')"
            )
            conn.commit()
            conn.close()
            (data_dir / "coverart").mkdir()
            (data_dir / "coverart" / "hades.jpg").write_bytes(b"fake")
            with mock.patch("arcade.scanners.lutris.lutris_data_dirs", return_value=[data_dir]):
                games, errors = lutris.scan()
            self.assertEqual(errors, [])
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].title, "Hades")
            self.assertEqual(games[0].launch.value, "lutris:rungameid/1")
            self.assertTrue(games[0].art.cover)


class TestItchScanner(unittest.TestCase):
    def test_butler_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "butler.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, cover_url TEXT)")
            conn.execute("CREATE TABLE caves (id INTEGER PRIMARY KEY, game_id INTEGER)")
            conn.execute("INSERT INTO games VALUES (10, 'Celeste', 'https://example.com/c.png')")
            conn.execute("INSERT INTO caves VALUES (99, 10)")
            conn.commit()
            conn.close()
            with mock.patch("arcade.scanners.itch.itch_db_paths", return_value=[db]):
                games, errors = itch.scan()
            self.assertEqual(errors, [])
            self.assertEqual(games[0].title, "Celeste")
            self.assertEqual(games[0].launch.value, "itch://caves/99/launch")


class TestBottlesScanner(unittest.TestCase):
    def test_external_programs(self):
        with tempfile.TemporaryDirectory() as tmp:
            bottle = Path(tmp) / "bottles" / "Gaming"
            bottle.mkdir(parents=True)
            (bottle / "bottle.yml").write_text(
                """
Name: Gaming
External_Programs:
  abc-123:
    name: Cool Game
    path: C:\\Program Files\\Cool\\cool.exe
Arch: win64
""",
                encoding="utf-8",
            )
            with mock.patch("arcade.scanners.bottles.bottles_data_dirs", return_value=[Path(tmp)]):
                games, errors = bottles.scan()
            self.assertEqual(errors, [])
            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].title, "Cool Game")
            self.assertEqual(games[0].launch.value[0], "bottles-cli")


class TestMerge(unittest.TestCase):
    def test_desktop_folds_into_steam(self):
        from arcade.model import Game, LaunchSpec, TrackSpec

        steam_g = Game(
            id="steam:570",
            title="Dota 2",
            source="steam",
            steam_app_id=570,
            launch=LaunchSpec(kind="uri", value="steam://rungameid/570"),
            track=TrackSpec(steam_app_id=570),
            dedupe_keys=["steam:570", "title:dota2"],
        )
        desk = Game(
            id="desktop:steam:570",
            title="Dota 2",
            source="desktop",
            steam_app_id=570,
            launch=LaunchSpec(kind="uri", value="steam://rungameid/570"),
            dedupe_keys=["steam:570", "title:dota2"],
        )
        merged = merge_games([desk, steam_g])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "steam")


if __name__ == "__main__":
    unittest.main()
