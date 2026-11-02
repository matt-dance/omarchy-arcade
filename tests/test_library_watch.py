"""Manifest StateFlags, debounce coalescing, and library add/remove diffs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arcade.config import load_config, library_settings
from arcade.library_watch import (
    GameRef,
    LibraryMonitor,
    collect_watch_paths,
    diff_library,
    library_is_stale,
)
from arcade.model import Game, write_library
from arcade.scanners import steam
from arcade.watch import Debouncer, PollWatcher


ROOT = Path(__file__).resolve().parent.parent


class TestManifestStateFlags(unittest.TestCase):
    def test_parse_state_flags(self):
        self.assertEqual(steam.parse_state_flags(4), 4)
        self.assertEqual(steam.parse_state_flags("4"), 4)
        self.assertEqual(steam.parse_state_flags(" 16 "), 16)
        self.assertEqual(steam.parse_state_flags(None), 0)
        self.assertEqual(steam.parse_state_flags(""), 0)
        self.assertEqual(steam.parse_state_flags("nope"), 0)
        self.assertEqual(steam.parse_state_flags(True), 0)
        self.assertEqual(steam.parse_state_flags(-3), 0)

    def test_fully_installed_bit_only(self):
        self.assertTrue(steam.manifest_is_installed({"StateFlags": "4"}))
        self.assertTrue(steam.manifest_is_installed({"stateflags": 4}))
        # Fully installed + other bits (e.g. update leftover) still counts.
        self.assertTrue(steam.manifest_is_installed({"StateFlags": 4 | 2}))
        self.assertTrue(steam.manifest_is_installed({"StateFlags": 4 | 16}))
        # Mid-download / not fully installed.
        self.assertFalse(steam.manifest_is_installed({"StateFlags": "0"}))
        self.assertFalse(steam.manifest_is_installed({"StateFlags": 2}))
        self.assertFalse(steam.manifest_is_installed({"StateFlags": 16}))
        self.assertFalse(steam.manifest_is_installed({"StateFlags": 1026}))
        self.assertFalse(steam.manifest_is_installed({}))
        self.assertFalse(steam.manifest_is_installed(None))
        self.assertFalse(steam.manifest_is_installed({"StateFlags": "xyz"}))

    def test_scan_skips_mass_effect_until_fully_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apps = root / "steamapps"
            apps.mkdir()
            acf = apps / "appmanifest_1328670.acf"
            acf.write_text(
                '"AppState"\n{\n  "appid" "1328670"\n'
                '  "name" "Mass Effect Legendary Edition"\n'
                '  "StateFlags" "16"\n}\n',
                encoding="utf-8",
            )
            with mock.patch("arcade.scanners.steam.steam_roots", return_value=[root]):
                games, errors = steam.scan()
            self.assertEqual(errors, [])
            self.assertEqual(games, [])

            acf.write_text(
                '"AppState"\n{\n  "appid" "1328670"\n'
                '  "name" "Mass Effect Legendary Edition"\n'
                '  "StateFlags" "4"\n}\n',
                encoding="utf-8",
            )
            with mock.patch("arcade.scanners.steam.steam_roots", return_value=[root]):
                games, errors = steam.scan()
            self.assertEqual(errors, [])
            self.assertEqual([g.id for g in games], ["steam:1328670"])
            self.assertEqual(games[0].title, "Mass Effect Legendary Edition")


class TestDebouncer(unittest.TestCase):
    def test_not_ready_until_delay(self):
        d = Debouncer(4.0)
        self.assertFalse(d.pending())
        self.assertFalse(d.ready(0.0))
        d.poke(10.0)
        self.assertTrue(d.pending())
        self.assertFalse(d.ready(13.9))
        self.assertTrue(d.ready(14.0))
        self.assertTrue(d.ready(20.0))

    def test_poke_extends_deadline(self):
        d = Debouncer(4.0)
        d.poke(0.0)
        d.poke(2.0)
        d.poke(3.0)
        self.assertFalse(d.ready(6.9))
        self.assertTrue(d.ready(7.0))
        self.assertEqual(d.next_deadline(), 7.0)

    def test_clear_and_zero_delay(self):
        d = Debouncer(0.0)
        d.poke(5.0)
        self.assertTrue(d.ready(5.0))
        d.clear()
        self.assertFalse(d.pending())
        self.assertFalse(d.ready(100.0))
        self.assertIsNone(d.next_deadline())


class TestLibraryDiff(unittest.TestCase):
    def test_add_remove_and_unchanged(self):
        old = [
            Game(id="steam:570", title="Dota 2", source="steam"),
            Game(id="steam:1245620", title="ELDEN RING", source="steam"),
        ]
        new = [
            Game(id="steam:570", title="Dota 2", source="steam"),
            Game(id="steam:1328670", title="Mass Effect Legendary Edition", source="steam"),
        ]
        diff = diff_library(old, new)
        self.assertTrue(diff.changed)
        self.assertEqual(diff.added, [GameRef("steam:1328670", "Mass Effect Legendary Edition")])
        self.assertEqual(diff.removed, [GameRef("steam:1245620", "ELDEN RING")])
        self.assertEqual(diff.added_line(), "Added: Mass Effect Legendary Edition")
        self.assertEqual(
            diff.to_dict()["added"],
            [{"id": "steam:1328670", "title": "Mass Effect Legendary Edition"}],
        )

        same = diff_library(old, old)
        self.assertFalse(same.changed)
        self.assertEqual(same.added, [])
        self.assertEqual(same.removed, [])
        self.assertEqual(same.added_line(), "")

    def test_dicts_and_multiple_added(self):
        old = [{"id": "desktop:wow", "title": "World of Warcraft"}]
        new = [
            {"id": "desktop:wow", "title": "World of Warcraft"},
            {"id": "gfn:1", "title": "Diablo IV"},
            {"id": "heroic:epic:a", "title": "Hades"},
        ]
        diff = diff_library(old, new)
        self.assertEqual([g.id for g in diff.added], ["gfn:1", "heroic:epic:a"])
        self.assertEqual(diff.added_line(), "Added: Diablo IV, Hades")
        many = diff_library([], [{"id": f"g:{i}", "title": f"G{i}"} for i in range(5)])
        self.assertEqual(many.added_line(), "Added: 5 games")

    def test_removed_only(self):
        diff = diff_library(
            [{"id": "steam:1", "title": "Gone"}],
            [],
        )
        self.assertEqual(diff.removed, [GameRef("steam:1", "Gone")])
        self.assertFalse(diff.added)


class TestLibraryStaleAndMonitor(unittest.TestCase):
    def test_stale_missing_and_age(self):
        self.assertTrue(library_is_stale(Path("/nonexistent/arcade-lib.json"), 15))
        self.assertTrue(library_is_stale(Path("/nonexistent/arcade-lib.json"), 0))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "library.json"
            write_library(path, [], [])
            now = path.stat().st_mtime
            self.assertFalse(library_is_stale(path, 15, now=now + 60))
            self.assertTrue(library_is_stale(path, 15, now=now + 15 * 60))
            self.assertTrue(library_is_stale(path, 15, now=now + 16 * 60))

    def test_monitor_startup_and_open_and_debounce(self):
        cfg = load_config(plugin_dir=ROOT, user_path=Path("/nonexistent"))
        reasons: list[str] = []
        watcher = PollWatcher()
        clock = {"mono": 0.0, "wall": 1_700_000_000.0}

        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "missing" / "library.json"
            mon = LibraryMonitor(
                cfg,
                on_rescan=reasons.append,
                library_file=lib,
                watcher=watcher,
                now=lambda: clock["mono"],
                wall_now=lambda: clock["wall"],
            )
            mon.start()
            self.assertEqual(reasons, ["startup"])

            reasons.clear()
            clock["wall"] += 60
            mon.on_overlay_open()
            self.assertEqual(reasons, ["open"])  # still missing → stale

            reasons.clear()
            write_library(lib, [], [])
            clock["wall"] = lib.stat().st_mtime + 10
            mon.on_overlay_open()
            self.assertEqual(reasons, [])

            mon.debouncer.poke(clock["mono"])
            mon.tick(clock["mono"] + 3.9)
            self.assertEqual(reasons, [])
            mon.tick(clock["mono"] + 4.0)
            self.assertEqual(reasons, ["watch"])
            mon.close()

    def test_auto_watch_off_skips_watch_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp) / "arcade.toml"
            user.write_text("[library]\nauto_watch = false\n", encoding="utf-8")
            cfg = load_config(plugin_dir=ROOT, user_path=user)
            self.assertFalse(library_settings(cfg)["auto_watch"])
            reasons: list[str] = []
            lib = Path(tmp) / "library.json"
            write_library(lib, [], [])
            mon = LibraryMonitor(
                cfg,
                on_rescan=reasons.append,
                library_file=lib,
                watcher=PollWatcher(),
                now=lambda: 100.0,
                wall_now=lambda: lib.stat().st_mtime + 10,
            )
            mon.start()
            self.assertEqual(mon.backend, "off")
            mon.debouncer.poke(100.0)
            mon.tick(200.0)
            self.assertEqual(reasons, [])
            mon.close()


class TestCollectWatchPaths(unittest.TestCase):
    def test_includes_steamapps_and_applications(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            steamapps = home / ".local" / "share" / "Steam" / "steamapps"
            steamapps.mkdir(parents=True)
            (steamapps / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n}\n', encoding="utf-8")
            apps = home / ".local" / "share" / "applications"
            apps.mkdir(parents=True)
            (apps / "Mass Effect Legendary Edition.desktop").write_text(
                "[Desktop Entry]\nName=Mass Effect Legendary Edition\n"
                "Exec=steam steam://rungameid/1328670\n",
                encoding="utf-8",
            )
            cfg = load_config(plugin_dir=ROOT, user_path=Path("/nonexistent"))
            with mock.patch("arcade.library_watch.steam_roots", return_value=[steamapps.parent]):
                with mock.patch("arcade.library_watch.application_dirs", return_value=[apps]):
                    with mock.patch("arcade.library_watch.xdg_data_home", return_value=home / ".local" / "share"):
                        with mock.patch("arcade.library_watch.heroic_roots", return_value=[]):
                            with mock.patch("arcade.library_watch.lutris_data_dirs", return_value=[]):
                                with mock.patch("arcade.library_watch.bottles_data_dirs", return_value=[]):
                                    with mock.patch("arcade.library_watch.itch_db_paths", return_value=[]):
                                        with mock.patch("arcade.library_watch.legendary_installed", return_value=[]):
                                            paths = collect_watch_paths(cfg)
            strs = {str(p) for p in paths}
            self.assertIn(str(steamapps), strs)
            self.assertIn(str(apps), strs)


class TestLibrarySettings(unittest.TestCase):
    def test_defaults_from_bundled_toml(self):
        cfg = load_config(plugin_dir=ROOT, user_path=Path("/nonexistent"))
        settings = library_settings(cfg)
        self.assertTrue(settings["auto_watch"])
        self.assertEqual(settings["debounce_s"], 4.0)
        self.assertEqual(settings["poll_interval_s"], 30.0)
        self.assertEqual(settings["stale_minutes"], 15.0)

    def test_clamps_and_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp) / "arcade.toml"
            user.write_text(
                "[library]\nauto_watch = false\ndebounce_s = 0\npoll_interval_s = 9999\n",
                encoding="utf-8",
            )
            cfg = load_config(plugin_dir=ROOT, user_path=user)
            settings = library_settings(cfg)
            self.assertFalse(settings["auto_watch"])
            self.assertEqual(settings["debounce_s"], 0.5)
            self.assertEqual(settings["poll_interval_s"], 600.0)


class TestPollWatcher(unittest.TestCase):
    def test_detects_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            watcher = PollWatcher()
            watcher.set_paths([directory])
            self.assertFalse(watcher.poll())
            (directory / "appmanifest_1328670.acf").write_text("x", encoding="utf-8")
            self.assertTrue(watcher.poll())
            self.assertFalse(watcher.poll())


class TestInotifyWatcher(unittest.TestCase):
    def test_create_wakes_and_stdlib_backend_has_no_extra_deps(self):
        from arcade.watch import create_watcher

        watcher = create_watcher()
        self.addCleanup(watcher.close)
        self.assertIn(watcher.backend, {"inotify", "poll", "watchdog", "pyinotify"})
        # Zero extra deps: this environment has neither watchdog nor pyinotify.
        if watcher.backend != "inotify":
            self.skipTest("inotify unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            watcher.set_paths([directory])
            self.assertIsNotNone(watcher.fd)
            self.assertEqual(watcher.read(), [])
            (directory / "appmanifest_1328670.acf").write_text("x", encoding="utf-8")
            # The kernel may deliver the event slightly after the write returns.
            events = watcher.read()
            if not events:
                import select

                select.select([watcher.fd], [], [], 1.0)
                events = watcher.read()
            self.assertTrue(events)


if __name__ == "__main__":
    unittest.main()
