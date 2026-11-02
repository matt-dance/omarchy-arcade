"""Manifest StateFlags, debounce coalescing, and library add/remove diffs."""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from arcade.config import load_config, library_settings
from arcade.library_watch import (
    GameRef,
    LibraryMonitor,
    collect_source_paths,
    collect_watch_paths,
    collect_watch_targets,
    diff_library,
    event_is_interesting,
    library_is_stale,
    source_is_watched,
)
from arcade.model import Game, write_library
from arcade.paths import GFN_PLUGIN_IDS, gfn_plugin_paths
from arcade.scanners import SCANNER_MODULES, scanner_watch_paths, steam
from arcade.watch import Debouncer, FileWatcher, PollWatcher


ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def fake_xdg(home: Path):
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_DATA_DIRS": str(home / ".local" / "share"),
    }
    with mock.patch.dict(os.environ, env, clear=False):
        yield


class FakeWatcher(FileWatcher):
    backend = "fake"

    def __init__(self) -> None:
        self.fd = 7
        self.paths: list[Path] = []
        self.events: list[tuple[Path | None, str]] = []
        self.polled = False

    def set_paths(self, paths) -> bool:
        self.paths = [Path(p) for p in paths]
        return True

    def read(self) -> list[tuple[Path | None, str]]:
        events, self.events = self.events, []
        return events

    def poll(self) -> bool:
        return self.polled


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


def _populate_scanner_sources(home: Path) -> None:
    share = home / ".local" / "share"
    config = home / ".config"
    apps = share / "applications"
    apps.mkdir(parents=True)
    (apps / "gfn-108815277.desktop").write_text(
        "[Desktop Entry]\nName=World of Warcraft\nExec=gfn-play.sh --cms-id 108815277\n"
        "X-Omarchy-Plugin=matt-dance.gfn-omarchy\nX-GFN-CmsId=108815277\n",
        encoding="utf-8",
    )
    (apps / "wow.desktop").write_text(
        "[Desktop Entry]\nName=World of Warcraft\nExec=umu-run wow\n",
        encoding="utf-8",
    )
    extensions = config / "omarchy" / "extensions"
    extensions.mkdir(parents=True)
    (extensions / "omarchy-menu.jsonc").write_text("{}\n", encoding="utf-8")
    gfn = share / "matt-dance.gfn-omarchy"
    gfn.mkdir(parents=True)
    (gfn / "games.json").write_text("[]\n", encoding="utf-8")
    steamapps = share / "Steam" / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n}\n', encoding="utf-8")
    userdata = share / "Steam" / "userdata" / "123" / "config"
    userdata.mkdir(parents=True)
    (userdata / "shortcuts.vdf").write_bytes(b"")
    (userdata / "localconfig.vdf").write_text('"UserLocalConfigStore"{}\n', encoding="utf-8")
    for rel in (
        "legendaryConfig/legendary/installed.json",
        "gog_store/installed.json",
        "nile_config/nile/installed.json",
        "sideload_apps/library.json",
    ):
        path = config / "heroic" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    legendary = config / "legendary" / "installed.json"
    legendary.parent.mkdir(parents=True)
    legendary.write_text("{}\n", encoding="utf-8")
    lutris = share / "lutris"
    lutris.mkdir(parents=True)
    (lutris / "pga.db").write_bytes(b"")
    (config / "lutris").mkdir(parents=True, exist_ok=True)
    bottle = share / "bottles" / "bottles" / "gaming"
    bottle.mkdir(parents=True)
    (bottle / "bottle.yml").write_text("Name: gaming\n", encoding="utf-8")
    itch = config / "itch" / "db"
    itch.mkdir(parents=True)
    (itch / "butler.db").write_bytes(b"")
    playlists = config / "retroarch" / "playlists"
    playlists.mkdir(parents=True)
    (playlists / "Nintendo - NES.lpl").write_text("{}\n", encoding="utf-8")
    roms = home / "Games" / "roms" / "nes"
    roms.mkdir(parents=True)


class TestCollectWatchPaths(unittest.TestCase):
    def test_includes_steamapps_and_applications(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _populate_scanner_sources(home)
            cfg = load_config(plugin_dir=ROOT, user_path=Path("/nonexistent"))
            with fake_xdg(home):
                paths = collect_watch_paths(cfg)
            strs = {str(p) for p in paths}
            self.assertIn(str(home / ".local" / "share" / "Steam" / "steamapps"), strs)
            self.assertIn(str(home / ".local" / "share" / "applications"), strs)

    def test_every_scanner_has_watch_paths(self):
        missing = [name for name, module in SCANNER_MODULES.items() if not hasattr(module, "watch_paths")]
        self.assertEqual(missing, [])

    def test_every_scanner_input_is_in_the_watch_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _populate_scanner_sources(home)
            user = home / "arcade.toml"
            user.write_text(
                "[sources]\n" + "".join(f"{name} = true\n" for name in SCANNER_MODULES),
                encoding="utf-8",
            )
            cfg = load_config(plugin_dir=ROOT, user_path=user)
            with fake_xdg(home):
                by_scanner = scanner_watch_paths(cfg)
                targets = collect_watch_targets(cfg)
                sources = collect_source_paths(cfg)
            self.assertEqual(set(by_scanner), set(SCANNER_MODULES))
            self.assertTrue(sources)
            for name, paths in by_scanner.items():
                self.assertTrue(paths, f"{name} watch_paths() is empty")
                for path in paths:
                    self.assertTrue(
                        source_is_watched(path, targets),
                        f"{name} input {path} is not in the watch set",
                    )

    def test_gfn_plugin_and_omarchy_menu_are_watched(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            apps = home / ".local" / "share" / "applications"
            apps.mkdir(parents=True)
            extensions = home / ".config" / "omarchy" / "extensions"
            extensions.mkdir(parents=True)
            (extensions / "omarchy-menu.jsonc").write_text("{}\n", encoding="utf-8")
            cfg = load_config(plugin_dir=ROOT, user_path=Path("/nonexistent"))
            with fake_xdg(home):
                sources = {p.resolve() for p in collect_source_paths(cfg)}
                targets = collect_watch_targets(cfg)
                plugin_paths = gfn_plugin_paths()
            self.assertIn((apps).resolve(), sources)
            self.assertIn((extensions / "omarchy-menu.jsonc").resolve(), sources)
            self.assertIn(extensions.resolve(), sources)
            for plugin_id in GFN_PLUGIN_IDS:
                self.assertTrue(any(plugin_id in str(p) for p in plugin_paths))
            for path in plugin_paths:
                self.assertTrue(source_is_watched(path, targets), f"GFN source {path} is not watched")
            self.assertTrue(event_is_interesting(apps, "gfn-108815277.desktop", targets))
            self.assertTrue(event_is_interesting(apps, "wow.desktop", targets))
            self.assertTrue(event_is_interesting(apps, ".gfn-write.XXXXXX", targets))
            self.assertTrue(event_is_interesting(extensions, "omarchy-menu.jsonc", targets))

    def test_missing_gfn_plugin_does_not_watch_xdg_data_unfiltered(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            share = home / ".local" / "share"
            apps = share / "applications"
            apps.mkdir(parents=True)
            cfg = load_config(plugin_dir=ROOT, user_path=Path("/nonexistent"))
            with fake_xdg(home):
                targets = collect_watch_targets(cfg)
            share_targets = [t for t in targets if t.directory.resolve() == share.resolve()]
            self.assertTrue(share_targets)
            for target in share_targets:
                self.assertIsNotNone(target.names)
                self.assertTrue({"matt-dance.gfn-omarchy", "matt-dance.gfn", "icons"} & set(target.names or []))
            self.assertFalse(event_is_interesting(share, "Trash", targets))
            self.assertTrue(event_is_interesting(share, "matt-dance.gfn-omarchy", targets))
            self.assertTrue(event_is_interesting(apps, "gfn-108815277.desktop", targets))

    def test_gfn_desktop_event_requests_watch_rescan(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            apps = home / ".local" / "share" / "applications"
            apps.mkdir(parents=True)
            lib = home / ".cache" / "matt-dance.arcade" / "library.json"
            lib.parent.mkdir(parents=True)
            write_library(lib, [], [])
            cfg = load_config(plugin_dir=ROOT, user_path=Path("/nonexistent"))
            reasons: list[str] = []
            watcher = FakeWatcher()
            clock = {"mono": 0.0, "wall": lib.stat().st_mtime + 10}
            with fake_xdg(home):
                mon = LibraryMonitor(
                    cfg,
                    on_rescan=reasons.append,
                    library_file=lib,
                    watcher=watcher,
                    now=lambda: clock["mono"],
                    wall_now=lambda: clock["wall"],
                )
                mon.start()
                self.assertEqual(reasons, [])
                watcher.events = [(apps, "gfn-108815277.desktop")]
                mon.on_readable(watcher.fd)
                mon.tick(clock["mono"] + 3.9)
                self.assertEqual(reasons, [])
                mon.tick(clock["mono"] + 4.0)
                self.assertEqual(reasons, ["watch"])
                mon.close()


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

    def test_gfn_atomic_rename_from_hidden_write_dir(self):
        from arcade.watch import InotifyWatcher, create_watcher

        watcher = create_watcher()
        self.addCleanup(watcher.close)
        if not isinstance(watcher, InotifyWatcher):
            self.skipTest("inotify unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            apps = Path(tmp) / "applications"
            apps.mkdir()
            watcher.set_paths([apps])
            self.assertEqual(watcher.read(), [])
            write_dir = Path(tempfile.mkdtemp(prefix=".gfn-write.", dir=apps))
            staged = write_dir / "gfn-108815277.desktop"
            staged.write_text(
                "[Desktop Entry]\nName=World of Warcraft\nExec=gfn-play.sh\n",
                encoding="utf-8",
            )
            dest = apps / "gfn-108815277.desktop"
            os.replace(staged, dest)
            write_dir.rmdir()
            events = watcher.read()
            if not events:
                import select

                select.select([watcher.fd], [], [], 1.0)
                events = watcher.read()
            self.assertTrue(events)
            names = {name for _directory, name in events}
            self.assertTrue(
                names & {"gfn-108815277.desktop", write_dir.name, "*"},
                names,
            )


if __name__ == "__main__":
    unittest.main()
