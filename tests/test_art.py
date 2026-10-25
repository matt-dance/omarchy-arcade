"""SteamGridDB lookup by Steam appid or title."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arcade.art import fetch_sgdb_image, search_sgdb_game_id, sgdb_json
from arcade.model import ArtSpec, image_max_edge, path_from_uri, stamp_icon_only


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


class TestIconOnlyInference(unittest.TestCase):
    def test_png_edge_and_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            small = Path(tmp) / "wow.png"
            large = Path(tmp) / "cover.png"
            small.write_bytes(_png(64, 64))
            large.write_bytes(_png(600, 900))
            self.assertEqual(image_max_edge(small), 64)
            self.assertEqual(image_max_edge(large), 900)
            tiny = ArtSpec(cover=small.as_uri(), icon=small.as_uri())
            stamp_icon_only(tiny)
            self.assertTrue(tiny.icon_only)
            box = ArtSpec(cover=large.as_uri())
            stamp_icon_only(box)
            self.assertFalse(box.icon_only)

    def test_gfn_box_art_in_icons_dir_is_not_icon_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            icons = Path(tmp) / "icons" / "gfn"
            icons.mkdir(parents=True)
            cover = icons / "gfn-107820252.png"
            cover.write_bytes(_png(600, 900))
            art = ArtSpec(cover=cover.as_uri(), icon=cover.as_uri())
            stamp_icon_only(art)
            self.assertFalse(art.icon_only)
        self.assertEqual(path_from_uri("file:///tmp/foo%20bar.png"), Path("/tmp/foo bar.png"))

    def test_unreadable_cover_is_left_alone(self):
        art = ArtSpec(cover="file:///tmp/wow.png", icon="file:///tmp/wow.png")
        stamp_icon_only(art)
        self.assertFalse(art.icon_only)


class TestSteamGridDB(unittest.TestCase):
    def test_search_requires_normalized_title_match(self):
        hits = {
            "data": [
                {"id": 11, "name": "World of Warcraft Classic"},
                {"id": 22, "name": "World of Warcraft"},
            ]
        }

        def opener(req, timeout):
            self.assertIn("search/autocomplete/", req.full_url)
            self.assertEqual(req.get_header("Authorization"), "Bearer test-key")
            return _FakeResp(json.dumps(hits).encode())

        self.assertEqual(search_sgdb_game_id("World of Warcraft", "test-key", opener=opener), 22)
        self.assertIsNone(search_sgdb_game_id("Battle.net", "test-key", opener=opener))
        self.assertIsNone(search_sgdb_game_id("World of Warcraft", ""))

    def test_fetch_grid_writes_dest(self):
        calls: list[str] = []

        def opener(req, timeout):
            calls.append(req.full_url)
            if "steamgriddb.com/api" in req.full_url:
                return _FakeResp(json.dumps({"data": [{"url": "https://cdn.example/cover.jpg"}]}).encode())
            return _FakeResp(b"jpeg-bytes")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "cover.jpg"
            uri = fetch_sgdb_image("grids", ("game", 22), "test-key", dest, "600x900", opener=opener)
            self.assertEqual(dest.read_bytes(), b"jpeg-bytes")
        self.assertTrue(uri and uri.endswith("cover.jpg"))
        self.assertTrue(any("/grids/game/22" in url for url in calls))

    def test_sgdb_json_swallows_errors(self):
        def boom(req, timeout):
            raise TimeoutError("nope")

        self.assertIsNone(sgdb_json("https://example.invalid", "k", opener=boom))


class TestArcadeArtScript(unittest.TestCase):
    def test_fetches_by_title_and_clears_icon_only(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader

        root = Path(__file__).resolve().parent.parent
        loader = SourceFileLoader("arcade_art_bin", str(root / "bin" / "arcade-art"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "library.json"
            key = Path(tmp) / "steamgriddb.key"
            key.write_text("test-key\n", encoding="utf-8")
            lib.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "games": [
                            {
                                "id": "desktop:battle.net",
                                "title": "Battle.net",
                                "art": {"cover": "file:///tiny.png", "iconOnly": True},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            cfg = mock.Mock()
            cfg.art = {"steamgriddb_key_file": str(key)}

            def fake_search(title, api_key, opener=None):
                self.assertEqual(title, "Battle.net")
                return 99

            def fake_fetch(kind, lookup, api_key, dest, dimensions, opener=None):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"art")
                return dest.as_uri()

            with (
                mock.patch.object(mod, "load_config", return_value=cfg),
                mock.patch.object(mod, "library_path", return_value=lib),
                mock.patch.object(mod, "arcade_cache_dir", return_value=Path(tmp) / "cache"),
                mock.patch.object(mod, "search_sgdb_game_id", side_effect=fake_search),
                mock.patch.object(mod, "fetch_sgdb_image", side_effect=fake_fetch),
            ):
                code = mod.main(["--plugin-dir", str(root), "--limit", "5"])
            self.assertEqual(code, 0)
            data = json.loads(lib.read_text(encoding="utf-8"))
            art = data["games"][0]["art"]
            self.assertNotIn("iconOnly", art)
            self.assertTrue(art["cover"].endswith("cover.jpg"))
            self.assertTrue(art["hero"].endswith("hero.jpg"))
