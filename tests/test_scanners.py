"""Scanner tests against fixtures."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arcade.home import source_badges
from arcade.model import (
    ArtSpec,
    Game,
    LaunchSpec,
    TrackSpec,
    art_from_dict,
    is_steam_desktop_wrapper,
    merge_games,
    normalize_title,
    should_record_also_on,
    write_library,
)
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
        # Steam Linux Runtime 4.0 (4183110), a future runtime by name, and
        # a generic type=tool app must never appear as playable games.
        self.assertNotIn("steam:4183110", ids)
        self.assertNotIn("steam:999001", ids)
        self.assertNotIn("steam:888001", ids)
        self.assertFalse(any("Steam Linux Runtime" in (g.title or "") for g in games))
        self.assertFalse(any((g.title or "").startswith("Proton ") for g in games))

    def test_local_hero_and_cover(self):
        root = FIXTURES / "steam"
        cache = root / "appcache" / "librarycache" / "1245620"
        cache.mkdir(parents=True, exist_ok=True)
        cover = cache / "library_600x900.jpg"
        hero = cache / "library_hero.jpg"
        cover.write_bytes(b"cover")
        hero.write_bytes(b"hero")
        with mock.patch("arcade.scanners.steam.steam_roots", return_value=[root]):
            games, errors = steam.scan()
        self.assertEqual(errors, [])
        elden = next(g for g in games if g.id == "steam:1245620")
        self.assertTrue(elden.art.cover)
        self.assertTrue(elden.art.hero)
        self.assertIn("library_hero", elden.art.hero)


class TestDesktopScanner(unittest.TestCase):
    def test_gfn_and_native_skip_steam_launcher(self):
        apps = FIXTURES / "applications"
        with mock.patch("arcade.scanners.desktop.application_dirs", return_value=[apps]):
            games, errors = desktop.scan()
        self.assertEqual(errors, [])
        ids = {g.id for g in games}
        gfn = [g for g in games if g.source == "gfn"]
        gfn_titles = {g.title for g in gfn}
        # Every plugin launcher: numeric cms-id files, plus the leftover slug
        # file (gfn-diablo-iv) even when NoDisplay=true / plugin id is short.
        self.assertEqual(
            {g.id for g in gfn},
            {
                "gfn:gfn-102383111",
                "gfn:gfn-102670811",
                "gfn:gfn-107820252",
                "gfn:gfn-diablo-iv",
            },
        )
        self.assertEqual(
            gfn_titles,
            {
                "Assassin's Creed Black Flag Resynced",
                "Diablo IV",
                "Enshrouded",
            },
        )
        self.assertTrue(all(g.runner == "cloud" for g in gfn))
        # GFN client itself is never a game
        self.assertFalse(any("geforcenow" in g.id.lower() for g in games))
        self.assertNotIn("GeForce NOW", {g.title for g in games})
        self.assertIn("desktop:super-meat-boy", ids)
        self.assertIn("desktop:battle.net", ids)
        self.assertIn("desktop:wow", ids)
        wow = next(g for g in games if g.id == "desktop:wow")
        self.assertEqual(wow.title, "World of Warcraft")
        self.assertEqual(wow.launch.value, str(apps / "wow.desktop"))
        # Bare Steam launcher skipped
        self.assertFalse(any("steam" == g.id.split(":")[-1] for g in games if g.source == "desktop"))
        # Steam-generated / steam://rungameid .desktop files fold into Steam, not Play on Desktop
        self.assertNotIn("desktop:steam:1203620", ids)
        self.assertNotIn("desktop:steam_app_1203620", ids)
        self.assertNotIn("desktop:enshrouded-steam", ids)
        self.assertFalse(any(g.steam_app_id == 1203620 for g in games))
        self.assertTrue(desktop.is_steam_generated_desktop(
            {"X-Steam-Library-AppID": "1203620"},
            "enshrouded",
            "steam steam://rungameid/1203620",
        ))
        self.assertFalse(
            desktop.is_steam_generated_desktop(
                {"StartupWMClass": "steam_app_battlenet"},
                "wow",
                "/home/mdance/.local/bin/launch-wow",
                installed_appids={570, 1245620},
            )
        )
        self.assertTrue(
            desktop.is_steam_generated_desktop(
                {"StartupWMClass": "steam_app_570"},
                "dota",
                "/opt/custom/dota",
                installed_appids={570},
            )
        )
        self.assertFalse(
            desktop.is_steam_generated_desktop(
                {"StartupWMClass": "steam_app_570"},
                "dota",
                "/opt/custom/dota",
                installed_appids=set(),
            )
        )

    def test_desktop_icon_is_icon_only_except_gfn(self):
        with tempfile.TemporaryDirectory() as tmp:
            apps = Path(tmp)
            icon = apps / "wow.png"
            icon.write_bytes(b"\x89PNG\r\n\x1a\n")
            (apps / "wow.desktop").write_text(
                "\n".join(
                    [
                        "[Desktop Entry]",
                        "Type=Application",
                        "Name=World of Warcraft",
                        "Exec=/opt/wow/wow",
                        f"Icon={icon}",
                        "Categories=Game;",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (apps / "gfn-1.desktop").write_text(
                "\n".join(
                    [
                        "[Desktop Entry]",
                        "Type=Application",
                        "Name=GFN - Diablo IV",
                        "Exec=bash /tmp/gfn-play.sh --cms-id 1",
                        f"Icon={icon}",
                        "Categories=Game;",
                        "X-Omarchy-Plugin=matt-dance.gfn-omarchy",
                        "X-GFN-CmsId=1",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch("arcade.scanners.desktop.application_dirs", return_value=[apps]):
                games, errors = desktop.scan()
        self.assertEqual(errors, [])
        wow = next(g for g in games if g.title == "World of Warcraft")
        self.assertTrue(wow.art.icon_only)
        self.assertTrue(wow.art.cover)
        gfn = next(g for g in games if g.source == "gfn")
        self.assertFalse(gfn.art.icon_only)
        self.assertTrue(gfn.art.cover)


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
        self.assertEqual(merged[0].also_on, [])
        self.assertTrue(is_steam_desktop_wrapper(desk))
        self.assertFalse(is_steam_desktop_wrapper(steam_g))
        self.assertFalse(should_record_also_on(steam_g, desk))

    def test_gfn_prefix_merges_with_steam(self):
        self.assertEqual(normalize_title("GFN - Enshrouded"), "enshrouded")
        self.assertEqual(normalize_title("Enshrouded"), "enshrouded")
        steam_g = Game(
            id="steam:1203620",
            title="Enshrouded",
            source="steam",
            steam_app_id=1203620,
            launch=LaunchSpec(kind="uri", value="steam://rungameid/1203620"),
            track=TrackSpec(steam_app_id=1203620),
            dedupe_keys=["steam:1203620", "title:enshrouded"],
        )
        gfn = Game(
            id="gfn:gfn-107820252",
            title="GFN - Enshrouded",
            source="gfn",
            store="Steam",
            runner="cloud",
            launch=LaunchSpec(kind="desktop", value="/tmp/gfn-107820252.desktop"),
            dedupe_keys=["gfn:107820252", "title:enshrouded"],
        )
        self.assertEqual(gfn.title, "Enshrouded")
        merged = merge_games([steam_g, gfn])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].id, "steam:1203620")
        self.assertEqual(merged[0].title, "Enshrouded")
        self.assertEqual(len(merged[0].also_on), 1)
        alt = merged[0].also_on[0]
        self.assertEqual(alt["id"], "gfn:gfn-107820252")
        self.assertEqual(alt["source"], "gfn")
        self.assertEqual(alt["launch"]["kind"], "desktop")

    def test_same_source_gfn_slug_and_cms_collapse(self):
        a = Game(
            id="gfn:gfn-102670811",
            title="GFN - Diablo IV",
            source="gfn",
            launch=LaunchSpec(kind="desktop", value="/tmp/a.desktop"),
            dedupe_keys=["gfn:102670811", "title:diabloiv"],
        )
        b = Game(
            id="gfn:gfn-diablo-iv",
            title="Diablo IV",
            source="gfn",
            launch=LaunchSpec(kind="desktop", value="/tmp/b.desktop"),
            dedupe_keys=["title:diabloiv"],
        )
        merged = merge_games([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "Diablo IV")
        # Same source: no Play on… row
        self.assertEqual(merged[0].also_on, [])

    def test_enshrouded_wrapper_does_not_add_play_on_desktop(self):
        steam_g = Game(
            id="steam:1203620",
            title="Enshrouded",
            source="steam",
            steam_app_id=1203620,
            launch=LaunchSpec(kind="uri", value="steam://rungameid/1203620"),
            track=TrackSpec(steam_app_id=1203620),
            dedupe_keys=["steam:1203620", "title:enshrouded"],
        )
        desk = Game(
            id="desktop:steam:1203620",
            title="Enshrouded",
            source="desktop",
            steam_app_id=1203620,
            launch=LaunchSpec(kind="desktop", value="/tmp/enshrouded-steam.desktop"),
            track=TrackSpec(steam_app_id=1203620),
            dedupe_keys=["steam:1203620", "title:enshrouded"],
        )
        gfn = Game(
            id="gfn:gfn-107820252",
            title="Enshrouded",
            source="gfn",
            store="Steam",
            runner="cloud",
            launch=LaunchSpec(kind="desktop", value="/tmp/gfn-107820252.desktop"),
            dedupe_keys=["gfn:107820252", "title:enshrouded"],
        )
        merged = merge_games([steam_g, desk, gfn])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "steam")
        self.assertEqual([e["source"] for e in merged[0].also_on], ["gfn"])
        self.assertEqual(source_badges(merged[0].to_dict()), ["Steam", "Play on GeForce NOW"])

    def test_small_icon_does_not_overwrite_cover(self):
        keeper = Game(
            id="steam:1",
            title="World of Warcraft",
            source="steam",
            art=ArtSpec(cover="file:///cover.jpg"),
            dedupe_keys=["title:worldofwarcraft"],
        )
        icon = Game(
            id="desktop:wow",
            title="World of Warcraft",
            source="desktop",
            art=ArtSpec(cover="file:///wow.png", icon="file:///wow.png", icon_only=True),
            dedupe_keys=["title:worldofwarcraft"],
        )
        merged = merge_games([keeper, icon])
        self.assertEqual(merged[0].art.cover, "file:///cover.jpg")
        self.assertFalse(merged[0].art.icon_only)

    def test_icon_only_game_survives_merge_and_write(self):
        wow = Game(
            id="desktop:wow",
            title="World of Warcraft",
            source="desktop",
            art=ArtSpec(cover="file:///wow.png", icon="file:///wow.png", icon_only=True),
            launch=LaunchSpec(kind="desktop", value="/tmp/wow.desktop"),
            dedupe_keys=["title:worldofwarcraft"],
        )
        battle = Game(
            id="desktop:battle.net",
            title="Battle.net",
            source="desktop",
            launch=LaunchSpec(kind="desktop", value="/tmp/battle.net.desktop"),
            dedupe_keys=["title:battlenet"],
        )
        merged = merge_games([wow, battle])
        self.assertEqual({g.id for g in merged}, {"desktop:wow", "desktop:battle.net"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "library.json"
            write_library(path, merged, [])
            data = json.loads(path.read_text(encoding="utf-8"))
        ids = {g["id"] for g in data["games"]}
        self.assertEqual(ids, {"desktop:wow", "desktop:battle.net"})
        wow_art = next(g["art"] for g in data["games"] if g["id"] == "desktop:wow")
        self.assertTrue(wow_art.get("iconOnly"))
        loaded = art_from_dict(wow_art)
        self.assertTrue(loaded.icon_only)


if __name__ == "__main__":
    unittest.main()
