"""Library state: favorites, hidden, play history, sort (state.json)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from arcade import state

ROOT = Path(__file__).resolve().parent.parent


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "matt-dance.arcade" / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_is_empty_state(self):
        self.assertEqual(state.load(self.path), state.empty_state())

    def test_corrupt_file_is_empty_state(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(state.load(self.path), state.empty_state())

    def test_normalize_drops_junk(self):
        data = {
            "favorites": ["a", "a", 3, ""],
            "hidden": "nope",
            "games": {"x": {"seconds": -5, "launches": True, "lastPlayed": 7}, "y": {"seconds": 61.9}},
            "sort": "bogus",
        }
        clean = state.normalize(data)
        self.assertEqual(clean["favorites"], ["a"])
        self.assertEqual(clean["hidden"], [])
        self.assertEqual(clean["games"], {"y": {"seconds": 61}})
        self.assertEqual(clean["sort"], "recent")

    def test_toggle_and_set_favorite(self):
        self.assertEqual(state.set_favorite("steam:1", path=self.path)["favorites"], ["steam:1"])
        self.assertEqual(state.set_favorite("steam:1", path=self.path)["favorites"], [])
        state.set_favorite("steam:1", True, path=self.path)
        state.set_favorite("steam:1", True, path=self.path)
        self.assertEqual(state.load(self.path)["favorites"], ["steam:1"])
        state.set_favorite("steam:1", False, path=self.path)
        self.assertEqual(state.load(self.path)["favorites"], [])

    def test_hidden(self):
        state.set_hidden("desktop:x", True, path=self.path)
        self.assertEqual(state.load(self.path)["hidden"], ["desktop:x"])

    def test_sort(self):
        state.set_sort("played", path=self.path)
        self.assertEqual(state.load(self.path)["sort"], "played")
        with self.assertRaises(ValueError):
            state.set_sort("random", path=self.path)

    def test_record_launch_and_session(self):
        state.record_launch("gfn:fortnite", when="2026-10-01T10:00:00Z", path=self.path)
        state.record_launch("gfn:fortnite", when="2026-10-02T10:00:00Z", path=self.path)
        state.record_session("gfn:fortnite", 3600, path=self.path)
        self.assertIsNone(state.record_session("gfn:fortnite", 3, path=self.path))
        entry = state.load(self.path)["games"]["gfn:fortnite"]
        self.assertEqual(entry["launches"], 2)
        self.assertEqual(entry["seconds"], 3600)
        self.assertGreater(entry["lastPlayed"], "2026-10-02T10:00:00Z")

    def test_write_is_atomic_and_leaves_no_temp_files(self):
        state.set_favorite("a", path=self.path)
        names = sorted(p.name for p in self.path.parent.iterdir())
        self.assertEqual(names, ["state.json", "state.json.lock"])
        json.loads(self.path.read_text(encoding="utf-8"))

    def test_concurrent_writers_do_not_lose_updates(self):
        def work(i):
            state.record_launch(f"g{i % 3}", path=self.path)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        games = state.load(self.path)["games"]
        self.assertEqual(sum(g["launches"] for g in games.values()), 30)

    def test_default_path_uses_xdg_state_home(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": self.tmp.name}):
            self.assertEqual(state.state_path(), Path(self.tmp.name) / "matt-dance.arcade" / "state.json")


class TestStateCli(unittest.TestCase):
    def run_cli(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(ROOT / "bin" / "arcade-state"), *args],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )

    def test_cli_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, XDG_STATE_HOME=tmp)
            self.run_cli("favorite", "steam:1", env=env)
            self.run_cli("hide", "desktop:junk", "--on", env=env)
            out = self.run_cli("sort", "az", env=env)
            data = json.loads(out.stdout)
            self.assertEqual(data["favorites"], ["steam:1"])
            self.assertEqual(data["hidden"], ["desktop:junk"])
            self.assertEqual(data["sort"], "az")
            self.assertTrue((Path(tmp) / "matt-dance.arcade" / "state.json").is_file())
            shown = json.loads(self.run_cli("show", env=env).stdout)
            self.assertEqual(shown, data)


class TestDaemonHistory(unittest.TestCase):
    def test_session_end_records_playtime_but_not_failures(self):
        from arcade.daemon import ArcadeDaemon

        class FakeSession:
            def __init__(self, info):
                self.info = info
                self.game_id = info["game"]

            def to_dict(self):
                return self.info

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}):
            daemon = ArcadeDaemon.__new__(ArcadeDaemon)
            daemon._record_session_end(FakeSession({"game": "a", "seconds": 120, "exitCode": 0}))
            daemon._record_session_end(FakeSession({"game": "b", "seconds": 90, "exitCode": -1}))
            daemon._record_session_end(FakeSession({"game": "c", "seconds": 90, "reason": "failed"}))
            daemon._record_session_end(FakeSession({"game": "d", "seconds": 300, "reason": "closed"}))
            games = state.load()["games"]
            self.assertEqual(sorted(games), ["a", "d"])
            self.assertEqual(games["a"]["seconds"], 120)


if __name__ == "__main__":
    unittest.main()
