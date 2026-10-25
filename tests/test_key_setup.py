"""In-app key setup: keys.json writes, status, live checks, CLI, stale metadata."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arcade.meta import keycheck
from arcade.meta.cache import write_cached
from arcade.meta.http import HttpError
from arcade.meta.keys import (
    KeyValueError,
    Keys,
    clean_value,
    key_status,
    load_keys,
    remove_keys,
    save_key,
)
from arcade.meta.resolve import missing_new_provider, providers_at_fetch, resolve_game

ROOT = Path(__file__).resolve().parent.parent
SECRET = "sk_live_DO_NOT_PRINT_12345"


class RouteHttp:
    def __init__(self, routes: dict[str, Any]):
        self.routes = routes
        self.calls: list[str] = []

    def _hit(self, url: str) -> Any:
        self.calls.append(url)
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise HttpError("no route", status=None)

    def get_json(self, url, headers=None):
        return self._hit(url)

    def post_json(self, url, data, headers=None):
        return self._hit(url)


class TestKeyStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cfg" / "keys.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_creates_private_file_with_all_fields(self):
        save_key("steamgriddb", f"  {SECRET}\n", self.path)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["steamgriddb_api_key"], SECRET)
        self.assertEqual(data["twitch_client_id"], "")
        self.assertEqual(load_keys(self.path, {}).warnings, [])
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["keys.json"])

    def test_save_keeps_other_fields_and_fixes_loose_permissions(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"twitch_client_id": "cid"}), encoding="utf-8")
        self.path.chmod(0o644)
        save_key("twitch-secret", "csecret", self.path)
        keys = load_keys(self.path, {})
        self.assertTrue(keys.has_igdb)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_rejects_junk_without_echoing_it(self):
        for bad in ("", "   ", "two words", "x" * 300, "line1\nline2"):
            with self.assertRaises(KeyValueError) as ctx:
                clean_value(bad)
            if bad.strip():
                self.assertNotIn(bad.strip()[:8], str(ctx.exception))
        with self.assertRaises(KeyValueError):
            save_key("github_token", "abc", self.path)
        self.assertFalse(self.path.exists())

    def test_strips_quotes_from_paste(self):
        self.assertEqual(clean_value('"abc123"'), "abc123")

    def test_remove_one_and_all(self):
        save_key("steamgriddb", "a1", self.path)
        save_key("twitch-id", "b2", self.path)
        remove_keys(["steamgriddb"], self.path)
        keys = load_keys(self.path, {})
        self.assertFalse(keys.has_steamgriddb)
        self.assertEqual(keys.twitch_client_id, "b2")
        remove_keys(None, self.path)
        self.assertIsNone(load_keys(self.path, {}).twitch_client_id)

    def test_status_is_booleans_only(self):
        save_key("steamgriddb", SECRET, self.path)
        status = key_status(self.path, {"ARCADE_TWITCH_CLIENT_ID": "envid"})
        self.assertTrue(status["steamgriddb"])
        self.assertFalse(status["igdb"])
        self.assertEqual(status["fields"]["twitch-id"], {"set": True, "fromEnv": True})
        self.assertNotIn(SECRET, json.dumps(status))
        self.assertNotIn("envid", json.dumps(status))


class TestKeyChecks(unittest.TestCase):
    def test_steamgriddb(self):
        keys = Keys(steamgriddb_api_key=SECRET)
        self.assertEqual(keycheck.check_steamgriddb(Keys(), RouteHttp({})), keycheck.MISSING)
        ok = RouteHttp({"steamgriddb.com": {"success": True, "data": []}})
        self.assertEqual(keycheck.check_steamgriddb(keys, ok), keycheck.OK)
        bad = RouteHttp({"steamgriddb.com": HttpError("HTTP 401", status=401)})
        self.assertEqual(keycheck.check_steamgriddb(keys, bad), keycheck.INVALID)
        down = RouteHttp({"steamgriddb.com": HttpError("request failed")})
        self.assertEqual(keycheck.check_steamgriddb(keys, down), keycheck.UNREACHABLE)

    def test_igdb_ok_caches_token(self):
        keys = Keys(twitch_client_id="cid", twitch_client_secret=SECRET)
        http = RouteHttp(
            {
                "id.twitch.tv": {"access_token": "tok", "expires_in": 3600},
                "api.igdb.com": [{"id": 1}],
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(keycheck.check_igdb(keys, http, Path(tmp)), keycheck.OK)
            token_file = Path(tmp) / "igdb_token.json"
            self.assertTrue(token_file.is_file())
            keycheck.clear_igdb_token(Path(tmp))
            self.assertFalse(token_file.exists())
            keycheck.clear_igdb_token(Path(tmp))

    def test_igdb_invalid_secret(self):
        keys = Keys(twitch_client_id="cid", twitch_client_secret="nope")
        http = RouteHttp({"id.twitch.tv": HttpError("HTTP 403", status=403)})
        self.assertEqual(keycheck.check_igdb(keys, http, Path("/nonexistent")), keycheck.INVALID)
        self.assertEqual(keycheck.check_igdb(Keys(twitch_client_id="cid"), http), keycheck.MISSING)


class TestStaleOnNewProvider(unittest.TestCase):
    def test_inference_for_old_records(self):
        self.assertEqual(
            providers_at_fetch({"sourcesUsed": ["steam", "steamgriddb"], "errors": ["igdb: unavailable"]}),
            {"igdb": True, "steamgriddb": True},
        )
        self.assertEqual(providers_at_fetch({"sourcesUsed": ["steam"]}), {"igdb": False, "steamgriddb": False})
        self.assertEqual(
            providers_at_fetch({"providers": {"igdb": True}, "sourcesUsed": []}),
            {"igdb": True, "steamgriddb": False},
        )

    def test_missing_new_provider(self):
        meta = {"sourcesUsed": ["steam"]}
        self.assertFalse(missing_new_provider(meta, Keys()))
        self.assertTrue(missing_new_provider(meta, Keys(steamgriddb_api_key="k")))
        self.assertFalse(missing_new_provider({"providers": {"steamgriddb": True}}, Keys(steamgriddb_api_key="k")))

    def test_fresh_cache_refetches_once_after_key_added(self):
        http = RouteHttp({"steamgriddb.com": {"success": False}, "store.steampowered.com": {}, "protondb": {}})
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            write_cached(
                "desktop:wow",
                {
                    "id": "desktop:wow",
                    "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ttlDays": 14,
                    "description": "cached",
                    "sourcesUsed": [],
                },
                cache,
            )
            game = {"id": "desktop:wow", "title": "World of Warcraft", "source": "desktop"}
            fresh = resolve_game(game, http=http, keys=Keys(), cache_dir=cache, steam_library_roots=[])
            self.assertEqual(http.calls, [])
            self.assertTrue(fresh["fresh"])

            keys = Keys(steamgriddb_api_key="k")
            resolve_game(game, http=http, keys=keys, cache_dir=cache, steam_library_roots=[])
            self.assertTrue(any("steamgriddb.com" in c for c in http.calls))

            http.calls.clear()
            again = resolve_game(game, http=http, keys=keys, cache_dir=cache, steam_library_roots=[])
            self.assertEqual(http.calls, [], "providers recorded, no refetch loop")
            self.assertEqual(again["description"], "cached")


class TestKeysCli(unittest.TestCase):
    def run_cli(self, env, *args, stdin=""):
        return subprocess.run(
            [sys.executable, str(ROOT / "bin" / "arcade-keys"), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_set_status_remove_never_prints_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=f"{tmp}/c", XDG_CACHE_HOME=f"{tmp}/k", PATH="/usr/bin:/bin")
            for var in ("ARCADE_STEAMGRIDDB_API_KEY", "ARCADE_TWITCH_CLIENT_ID", "ARCADE_TWITCH_CLIENT_SECRET"):
                env.pop(var, None)
            first = json.loads(self.run_cli(env, "status").stdout)
            self.assertFalse(first["steamgriddb"])
            self.assertFalse(first["promptDismissed"])

            token = Path(tmp) / "k" / "matt-dance.arcade" / "igdb_token.json"
            token.parent.mkdir(parents=True)
            token.write_text("{}", encoding="utf-8")

            out = self.run_cli(env, "set", "twitch-secret", stdin=SECRET + "\n")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertNotIn(SECRET, out.stdout + out.stderr)
            data = json.loads(out.stdout)
            self.assertEqual(data["saved"], "twitch-secret")
            self.assertTrue(data["fields"]["twitch-secret"]["set"])
            self.assertTrue(data["promptDismissed"])
            self.assertFalse(token.exists(), "IGDB token cache is cleared when Twitch keys change")

            keys_file = Path(tmp) / "c" / "matt-dance.arcade" / "keys.json"
            self.assertEqual(stat.S_IMODE(keys_file.stat().st_mode), 0o600)

            bad = self.run_cli(env, "set", "steamgriddb", stdin="not a key\n")
            self.assertEqual(bad.returncode, 1)
            self.assertIn("error", json.loads(bad.stdout))

            removed = json.loads(self.run_cli(env, "remove").stdout)
            self.assertFalse(removed["fields"]["twitch-secret"]["set"])

    @unittest.skipIf(shutil.which("wl-paste"), "wl-paste installed")
    def test_clipboard_without_wl_paste_is_a_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, XDG_CONFIG_HOME=f"{tmp}/c", PATH="/nonexistent")
            out = self.run_cli(env, "set", "steamgriddb", "--from-clipboard")
            self.assertEqual(out.returncode, 1)
            self.assertIn("wl-paste", json.loads(out.stdout)["error"])


class TestOverlayKeys(unittest.TestCase):
    def test_overlay_never_names_key_fields_or_passes_values_in_argv(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        for field in ("steamgriddb_api_key", "twitch_client_id", "twitch_client_secret"):
            self.assertNotIn(field, qml)
        self.assertIn("--from-clipboard", qml)
        self.assertIn("echoMode: TextInput.Password", qml)
        self.assertIn('root.runKeys(["set", row.id], value + "\\n")', qml)

    def test_system_menu_opens_keys_with_explicit_summon(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        service = (ROOT / "Service.qml").read_text(encoding="utf-8")
        fn = qml[qml.index("function showKeysFromMenu()"):]
        fn = fn[: fn.index("\n  }\n")]
        self.assertIn('"summon"', fn)
        self.assertNotIn("toggle", fn)
        self.assertIn("keysSheetWanted = true", fn)
        self.assertIn("property bool keysSheetWanted", service)
        self.assertIn('payload.surface === "keys"', qml)

    def test_menu_rows_show_hints(self):
        menu = (ROOT / "QuickMenu.qml").read_text(encoding="utf-8")
        self.assertIn("text: modelData.hint", menu)

    def test_keys_rows_ignore_resting_pointer(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        self.assertNotIn("onEntered: root.keysIndex", qml)
        self.assertIn("function pointerMoved(scenePos)", qml)

    def test_first_status_read_is_not_a_change(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        self.assertIn("var known = root.keyStatus.file !== undefined", qml)
        self.assertIn("if (known && ", qml)

    def test_keys_json_is_gitignored(self):
        self.assertIn("keys.json", (ROOT / ".gitignore").read_text(encoding="utf-8").split())
        example = json.loads((ROOT / "keys.example.json").read_text(encoding="utf-8"))
        self.assertTrue(all(v == "" for v in example.values()))


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestModelProviders(unittest.TestCase):
    def run_js(self, expr):
        source = (ROOT / "ArcadeModel.js").read_text(encoding="utf-8").replace(".pragma library", "", 1)
        out = subprocess.run(
            ["node", "-e", source + "\nprocess.stdout.write(JSON.stringify(" + expr + "))"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(out.stdout)

    def test_meta_missing_provider_matches_python(self):
        self.assertTrue(self.run_js('metaMissingProvider({sourcesUsed: ["steam"]}, {steamgriddb: true})'))
        self.assertFalse(self.run_js('metaMissingProvider({providers: {steamgriddb: true}}, {steamgriddb: true})'))
        self.assertFalse(self.run_js('metaMissingProvider({errors: ["igdb: unavailable"]}, {igdb: true})'))
        self.assertFalse(self.run_js("metaMissingProvider({sourcesUsed: []}, {})"))


if __name__ == "__main__":
    unittest.main()
