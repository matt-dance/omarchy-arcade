"""Run ArcadeModel.js library-state helpers under node (skipped without node)."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def run_js(expr: str):
    source = (ROOT / "ArcadeModel.js").read_text(encoding="utf-8").replace(".pragma library", "", 1)
    script = source + "\nprocess.stdout.write(JSON.stringify(" + expr + "))\n"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


GAMES = [
    {"id": "steam:1", "title": "Elden Ring", "source": "steam", "lastPlayed": "2026-09-01T00:00:00Z", "playtimeMinutes": 600},
    {"id": "steam:2", "title": "Hades", "source": "steam"},
    {"id": "gfn:fortnite", "title": "Fortnite", "source": "gfn"},
    {
        "id": "desktop:wow",
        "title": "World of Warcraft",
        "source": "desktop",
        "alsoOn": [{"id": "gfn:wow", "source": "gfn", "title": "World of Warcraft"}],
    },
    {"id": "desktop:junk", "title": "Uninstaller", "source": "desktop"},
]

STATE = {
    "favorites": ["steam:2", "gfn:wow"],
    "hidden": ["desktop:junk"],
    "games": {
        "gfn:fortnite": {"lastPlayed": "2026-10-20T00:00:00Z", "seconds": 7200, "launches": 3},
        "steam:1": {"lastPlayed": "2026-10-01T00:00:00Z", "seconds": 60},
        "gfn:wow": {"seconds": 1800},
    },
    "sort": "played",
}


@unittest.skipUnless(NODE, "node not installed")
class TestModelState(unittest.TestCase):
    def applied(self):
        return (
            "applyState(" + json.dumps(GAMES) + ", parseStateText(" + json.dumps(json.dumps(STATE)) + "))"
        )

    def test_parse_state_text_tolerates_bad_input(self):
        empty = run_js('parseStateText("{oops")')
        self.assertEqual(empty, {"favorites": {}, "hidden": {}, "games": {}, "sort": "recent"})
        self.assertEqual(run_js("parseStateText(" + json.dumps(json.dumps(STATE)) + ").sort"), "played")

    def test_apply_state_merges_history_and_flags(self):
        games = {g["id"]: g for g in run_js(self.applied())}
        self.assertEqual(games["gfn:fortnite"]["lastPlayed"], "2026-10-20T00:00:00Z")
        self.assertEqual(games["gfn:fortnite"]["playtimeMinutes"], 120)
        self.assertEqual(games["steam:1"]["lastPlayed"], "2026-10-01T00:00:00Z")
        self.assertEqual(games["steam:1"]["playtimeMinutes"], 600)
        self.assertTrue(games["steam:2"]["favorite"])
        self.assertTrue(games["desktop:wow"]["favorite"], "favorite on a Play on… alias counts")
        self.assertEqual(games["desktop:wow"]["playtimeMinutes"], 30)
        self.assertTrue(games["desktop:junk"]["hidden"])
        self.assertNotIn("favorite", GAMES[1], "input rows are not mutated")

    def test_home_shelf_recent_then_favorites_then_rest(self):
        ids = run_js("homeShelf(" + self.applied() + ").map(function(g) { return g.id })")
        self.assertEqual(ids, ["gfn:fortnite", "steam:1", "steam:2", "desktop:wow"])

    def test_tabs_and_tab_games(self):
        tabs = run_js("libraryTabs(" + self.applied() + ").map(function(t) { return t.id })")
        self.assertEqual(tabs, ["all", "favorites", "source:desktop", "source:gfn", "source:steam", "hidden"])
        fav = run_js("tabGames(" + self.applied() + ', "favorites").map(function(g) { return g.id })')
        self.assertEqual(sorted(fav), ["desktop:wow", "steam:2"])
        hidden = run_js("tabGames(" + self.applied() + ', "hidden").map(function(g) { return g.id })')
        self.assertEqual(hidden, ["desktop:junk"])
        all_ids = run_js("tabGames(" + self.applied() + ', "all").map(function(g) { return g.id })')
        self.assertNotIn("desktop:junk", all_ids)
        search = run_js("filterGames(" + self.applied() + ', "").map(function(g) { return g.id })')
        self.assertNotIn("desktop:junk", search)

    def test_sorts(self):
        def order(mode):
            return run_js("sortGames(" + self.applied() + ', "' + mode + '").map(function(g) { return g.title })')

        self.assertEqual(order("az")[:3], ["Elden Ring", "Fortnite", "Hades"])
        self.assertEqual(order("played")[:3], ["Elden Ring", "Fortnite", "World of Warcraft"])
        self.assertEqual(order("recent")[:2], ["Fortnite", "Elden Ring"])
        self.assertEqual(order("source")[0], "Uninstaller")
        self.assertEqual(run_js('nextSort("source")'), "recent")

    def test_option_items(self):
        labels = run_js("optionItems(" + self.applied() + "[3]).map(function(i) { return i.label })")
        self.assertEqual(
            labels,
            ["Play on Desktop", "Play on GeForce NOW", "Remove from favorites", "Hide from library", "Refresh metadata"],
        )
        single = run_js("optionItems(" + self.applied() + "[1]).map(function(i) { return i.label })")
        self.assertEqual(single[0], "Play")

    def test_state_file_path(self):
        self.assertEqual(run_js('stateFilePath("/home/u", "")'), "/home/u/.local/state/matt-dance.arcade/state.json")
        self.assertEqual(run_js('stateFilePath("/home/u", "/x")'), "/x/matt-dance.arcade/state.json")


if __name__ == "__main__":
    unittest.main()
