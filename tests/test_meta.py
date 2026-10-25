"""Metadata fetch/cache tests. Fixtures only — a live HTTP call fails the test."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from arcade.meta.cache import cache_stem, is_fresh, load_cached, meta_json_path, write_cached
from arcade.meta.http import HttpError
from arcade.meta.keys import Keys
from arcade.meta.protondb import parse_summary
from arcade.meta.resolve import art_is_weak, resolve_game, should_search_steam
from arcade.meta.steam import parse_appdetails, parse_store_search
from arcade.meta.steamgriddb import parse_search
from arcade.meta.textutil import parse_year, strip_html
from arcade.steam_local import playtime_for_appid, playtime_map

FIXTURES = Path(__file__).parent / "fixtures" / "meta"


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeHttp:
    """URL-map client. Unexpected hosts/paths raise so tests cannot go live."""

    def __init__(
        self,
        routes: dict[str, Any] | None = None,
        downloads: dict[str, bytes] | None = None,
    ) -> None:
        self.routes = routes or {}
        self.downloads = downloads or {}
        self.calls: list[tuple[str, str]] = []

    def _lookup(self, method: str, url: str) -> Any:
        self.calls.append((method, url))
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname not in {
            "example.test",
            "store.steampowered.com",
            "www.protondb.com",
            "id.twitch.tv",
            "api.igdb.com",
            "www.steamgriddb.com",
            "images.igdb.com",
        }:
            raise AssertionError(f"unexpected live host: {parsed.hostname}")
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise HttpError(f"no fixture for {parsed.netloc}{parsed.path}")

    def get_json(self, url: str, headers: dict | None = None) -> Any:
        self._check_headers(headers)
        return self._lookup("GET", url)

    def post_json(self, url: str, data: bytes, headers: dict | None = None) -> Any:
        self._check_headers(headers)
        return self._lookup("POST", url)

    def download(self, url: str, dest: Path, headers: dict | None = None) -> bool:
        self._check_headers(headers)
        self.calls.append(("GET", url))
        blob = self.downloads.get(url)
        if blob is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        return True

    def _check_headers(self, headers: dict | None) -> None:
        if not headers:
            return
        joined = " ".join(str(v) for v in headers.values())
        # Values may include a bearer token in the Authorization header during
        # a real call; tests must not persist that into assertions later.
        _ = joined


class TestTextUtil(unittest.TestCase):
    def test_strip_html_and_year(self):
        self.assertEqual(strip_html("Hello <b>world</b> &amp; you"), "Hello world & you")
        self.assertEqual(parse_year("24 Jan, 2024"), 2024)
        self.assertEqual(parse_year(1096588800), 2004)
        self.assertIsNone(parse_year(""))


class TestSteamParsers(unittest.TestCase):
    def test_appdetails_fields(self):
        parsed = parse_appdetails(_load_json("steam_appdetails_enshrouded.json"), 1203620)
        assert parsed is not None
        self.assertEqual(parsed["steamAppId"], 1203620)
        self.assertEqual(parsed["title"], "Enshrouded")
        self.assertIn("survival", parsed["description"])
        self.assertNotIn("<b>", parsed["description"])
        self.assertEqual(parsed["genres"], ["Action", "Adventure", "Indie"])
        self.assertEqual(parsed["developers"], ["Keen Games GmbH"])
        self.assertEqual(parsed["releaseYear"], 2024)
        self.assertEqual(parsed["rating"]["source"], "metacritic")
        self.assertEqual(parsed["rating"]["score"], 81)
        self.assertEqual(len(parsed["screenshotUrls"]), 2)

    def test_appdetails_missing(self):
        self.assertIsNone(parse_appdetails(_load_json("steam_appdetails_missing.json"), 1))

    def test_store_search_picks_exact_title(self):
        appid = parse_store_search(_load_json("steam_storesearch_diablo.json"), "Diablo IV")
        self.assertEqual(appid, 2344520)


class TestProtonDBParser(unittest.TestCase):
    def test_summary(self):
        parsed = parse_summary(_load_json("protondb_enshrouded.json"), 1203620)
        assert parsed is not None
        self.assertEqual(parsed["tier"], "platinum")
        self.assertEqual(parsed["total"], 412)


class TestPlaytime(unittest.TestCase):
    def test_localconfig(self):
        root = FIXTURES / "steam_root"
        mapping = playtime_map(root)
        self.assertEqual(mapping[1203620][0], 240)
        self.assertTrue(mapping[1203620][1].startswith("2024-"))
        minutes, last = playtime_for_appid(242050, [root])
        self.assertEqual(minutes, 90)
        self.assertTrue(last)


class TestCacheFreshness(unittest.TestCase):
    def test_fresh_and_stale(self):
        now = datetime(2026, 10, 25, tzinfo=timezone.utc)
        fresh = {"fetchedAt": "2026-10-20T00:00:00Z", "ttlDays": 14}
        stale = {"fetchedAt": "2026-09-01T00:00:00Z", "ttlDays": 14}
        self.assertTrue(is_fresh(fresh, now=now))
        self.assertFalse(is_fresh(stale, now=now))
        self.assertFalse(is_fresh({}, now=now))

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            write_cached("steam:1203620", {"id": "steam:1203620", "description": "hi"}, cache)
            loaded = load_cached("steam:1203620", cache)
            assert loaded is not None
            self.assertEqual(loaded["description"], "hi")
            self.assertIsNone(load_cached("missing", cache))
            self.assertEqual(cache_stem("steam:1203620"), "steam_1203620")
            self.assertTrue(str(meta_json_path("steam:1203620", cache)).endswith("steam_1203620.json"))


class TestResolve(unittest.TestCase):
    def _steam_http(self) -> FakeHttp:
        return FakeHttp(
            routes={
                "appdetails?appids=1203620": _load_json("steam_appdetails_enshrouded.json"),
                "summaries/1203620.json": _load_json("protondb_enshrouded.json"),
                "storesearch": _load_json("steam_storesearch_diablo.json"),
            },
            downloads={
                "https://example.test/enshrouded/ss0_t.jpg": b"ss0",
                "https://example.test/enshrouded/ss1_t.jpg": b"ss1",
            },
        )

    def test_steam_game_fills_fields_and_caches(self):
        http = self._steam_http()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            game = {
                "id": "steam:1203620",
                "title": "Enshrouded",
                "source": "steam",
                "steamAppId": 1203620,
                "art": {"cover": "file:///steam/library_600x900.jpg"},
            }
            meta = resolve_game(
                game,
                http=http,
                keys=Keys(),
                cache_dir=cache,
                steam_library_roots=[FIXTURES / "steam_root"],
            )
            self.assertEqual(meta["description"][:10], "Enshrouded")
            self.assertEqual(meta["genres"][0], "Action")
            self.assertEqual(meta["developers"], ["Keen Games GmbH"])
            self.assertEqual(meta["releaseYear"], 2024)
            self.assertEqual(meta["rating"]["score"], 81)
            self.assertEqual(meta["proton"]["tier"], "platinum")
            self.assertEqual(meta["playtimeMinutes"], 240)
            self.assertTrue(meta["lastPlayed"])
            self.assertEqual(len(meta["screenshots"]), 2)
            self.assertIn("steam", meta["sourcesUsed"])
            self.assertIn("protondb", meta["sourcesUsed"])
            self.assertIn("local", meta["sourcesUsed"])
            cached = load_cached("steam:1203620", cache)
            assert cached is not None
            self.assertEqual(cached["releaseYear"], 2024)

    def test_cache_hit_skips_http(self):
        http = self._steam_http()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            write_cached(
                "steam:1203620",
                {
                    "id": "steam:1203620",
                    "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ttlDays": 14,
                    "description": "cached copy",
                    "steamAppId": 1203620,
                },
                cache,
            )
            meta = resolve_game(
                {"id": "steam:1203620", "title": "Enshrouded", "steamAppId": 1203620},
                http=http,
                keys=Keys(),
                cache_dir=cache,
                steam_library_roots=[FIXTURES / "steam_root"],
            )
            self.assertEqual(meta["description"], "cached copy")
            self.assertTrue(meta["fresh"])
            self.assertEqual(http.calls, [])

    def test_stale_cache_still_returned_offline(self):
        http = self._steam_http()
        stale_at = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            write_cached(
                "steam:1203620",
                {
                    "id": "steam:1203620",
                    "fetchedAt": stale_at,
                    "ttlDays": 14,
                    "description": "old but useful",
                    "steamAppId": 1203620,
                },
                cache,
            )
            meta = resolve_game(
                {"id": "steam:1203620", "title": "Enshrouded", "steamAppId": 1203620},
                offline=True,
                http=http,
                keys=Keys(),
                cache_dir=cache,
                steam_library_roots=[],
            )
            self.assertEqual(meta["description"], "old but useful")
            self.assertEqual(http.calls, [])

    def test_missing_source_degrades(self):
        http = FakeHttp(routes={})
        with tempfile.TemporaryDirectory() as tmp:
            meta = resolve_game(
                {"id": "steam:1203620", "title": "Enshrouded", "steamAppId": 1203620},
                force=True,
                http=http,
                keys=Keys(),
                cache_dir=Path(tmp),
                steam_library_roots=[],
            )
            self.assertEqual(meta["description"], "")
            self.assertIsNone(meta["proton"])
            self.assertTrue(any(e.startswith("steam:") for e in meta["errors"]))
            self.assertTrue(any(e.startswith("protondb:") for e in meta["errors"]))

    def test_gfn_title_maps_via_store_search(self):
        http = FakeHttp(
            routes={
                "storesearch": _load_json("steam_storesearch_diablo.json"),
                "appdetails?appids=2344520": {
                    "2344520": {
                        "success": True,
                        "data": {
                            "name": "Diablo IV",
                            "steam_appid": 2344520,
                            "short_description": "End the eternal conflict.",
                            "developers": ["Blizzard Entertainment"],
                            "publishers": ["Blizzard Entertainment"],
                            "genres": [{"description": "Action"}],
                            "release_date": {"date": "6 Jun, 2023"},
                            "screenshots": [],
                        },
                    }
                },
                "summaries/2344520.json": {"tier": "gold", "bestReportedTier": "gold", "total": 10},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            game = {
                "id": "gfn:gfn-102670811",
                "title": "Diablo IV",
                "source": "gfn",
                "store": "Steam",
            }
            self.assertTrue(should_search_steam(game))
            meta = resolve_game(
                game,
                http=http,
                keys=Keys(),
                cache_dir=Path(tmp),
                steam_library_roots=[],
            )
            self.assertEqual(meta["steamAppId"], 2344520)
            self.assertEqual(meta["description"], "End the eternal conflict.")
            self.assertEqual(meta["proton"]["tier"], "gold")

    def test_igdb_and_sgdb_inactive_without_keys(self):
        http = FakeHttp(
            routes={
                "id.twitch.tv": AssertionError("IGDB token requested without keys"),
                "api.igdb.com": AssertionError("IGDB games requested without keys"),
                "steamgriddb.com": AssertionError("SGDB requested without keys"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            meta = resolve_game(
                {"id": "desktop:wow", "title": "World of Warcraft", "source": "desktop"},
                http=http,
                keys=Keys(),
                cache_dir=Path(tmp),
                steam_library_roots=[],
            )
            self.assertNotIn("igdb", meta["sourcesUsed"])
            self.assertNotIn("steamgriddb", meta["sourcesUsed"])
            self.assertEqual(http.calls, [])

    def test_igdb_and_sgdb_fill_non_steam(self):
        http = FakeHttp(
            routes={
                "oauth2/token": {"access_token": "igdb-access-token-value", "expires_in": 3600},
                "api.igdb.com": _load_json("igdb_wow.json"),
                "search/autocomplete": _load_json("sgdb_search_wow.json"),
                "/grids/game/77": _load_json("sgdb_grids.json"),
                "/heroes/game/77": {"success": True, "data": []},
                "/logos/game/77": {"success": True, "data": []},
            },
            downloads={"https://example.test/sgdb/wow-cover.jpg": b"cover"},
        )
        keys = Keys(
            steamgriddb_api_key="sgdb-secret",
            twitch_client_id="twitch-id",
            twitch_client_secret="twitch-secret",
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            meta = resolve_game(
                {
                    "id": "desktop:wow",
                    "title": "World of Warcraft",
                    "source": "desktop",
                    "art": {
                        "cover": "file:///home/user/.local/share/icons/wow.png",
                        "icon": "file:///home/user/.local/share/icons/wow.png",
                    },
                },
                http=http,
                keys=keys,
                cache_dir=cache,
                steam_library_roots=[],
            )
            self.assertIn("Azeroth", meta["description"])
            self.assertEqual(meta["developers"], ["Blizzard Entertainment"])
            self.assertEqual(meta["releaseYear"], 2004)
            self.assertEqual(meta["rating"]["score"], 88)
            self.assertIn("igdb", meta["sourcesUsed"])
            self.assertIn("steamgriddb", meta["sourcesUsed"])
            self.assertTrue(meta["art"].get("cover", "").endswith("cover.jpg"))
            dumped = json.dumps(meta) + json.dumps(http.calls)
            self.assertNotIn("sgdb-secret", dumped)
            self.assertNotIn("twitch-secret", dumped)
            self.assertNotIn("twitch-id", dumped)
            self.assertNotIn("igdb-access-token-value", dumped)

    def test_weak_art_heuristic(self):
        self.assertTrue(art_is_weak(None))
        self.assertTrue(art_is_weak({"cover": None}))
        self.assertTrue(
            art_is_weak(
                {
                    "cover": "file:///icons/wow.png",
                    "icon": "file:///icons/wow.png",
                }
            )
        )
        self.assertFalse(art_is_weak({"cover": "file:///Steam/library_600x900.jpg"}))


class TestArcadeMetaCli(unittest.TestCase):
    def test_cli_help_and_missing_library(self):
        import subprocess
        import sys

        root = Path(__file__).resolve().parent.parent
        help_proc = subprocess.run(
            [sys.executable, str(root / "bin" / "arcade-meta"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_proc.returncode, 0)
        self.assertIn("metadata", help_proc.stdout.casefold())
        missing = subprocess.run(
            [
                sys.executable,
                str(root / "bin" / "arcade-meta"),
                "--offline",
                "--library",
                "/nonexistent/library.json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertNotIn("ARCADE_STEAMGRIDDB_API_KEY", missing.stdout)
        self.assertNotIn("twitch_client_secret", missing.stdout)

    def test_offline_cli_uses_cache(self):
        from arcade.meta.cache import write_cached

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "meta"
            cache.mkdir()
            lib = Path(tmp) / "library.json"
            lib.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "games": [
                            {
                                "id": "steam:1203620",
                                "title": "Enshrouded",
                                "steamAppId": 1203620,
                            }
                        ],
                        "errors": [],
                    }
                ),
                encoding="utf-8",
            )
            write_cached(
                "steam:1203620",
                {
                    "id": "steam:1203620",
                    "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "description": "from cache",
                },
                cache,
            )
            from arcade.meta.resolve import resolve_library

            result = resolve_library(
                json.loads(lib.read_text())["games"],
                ids=["steam:1203620"],
                offline=True,
                http=FakeHttp(routes={}),
                keys=Keys(),
                cache_dir=cache,
                steam_library_roots=[],
            )
            self.assertEqual(result["updated"], 1)
            self.assertEqual(result["keys"]["steamgriddb"], False)


class TestNoLiveNetworkGuard(unittest.TestCase):
    def test_default_http_client_is_not_used_in_parser_tests(self):
        # Parsers are pure: they never construct HttpClient.
        import inspect

        from arcade.meta import protondb, steam

        self.assertNotIn("urlopen", inspect.getsource(steam.parse_appdetails))
        self.assertNotIn("urlopen", inspect.getsource(protondb.parse_summary))


if __name__ == "__main__":
    unittest.main()
