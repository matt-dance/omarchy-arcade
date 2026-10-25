"""API key loading: file + env, permissions warning, never leak values."""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from arcade.meta.keys import (
    ENV_STEAMGRIDDB,
    ENV_TWITCH_ID,
    ENV_TWITCH_SECRET,
    load_keys,
)


def _write_keys(path: Path, payload: dict, mode: int = 0o600) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(mode)


class TestLoadKeys(unittest.TestCase):
    def test_missing_file_is_empty(self):
        keys = load_keys(path=Path("/nonexistent/keys.json"), environ={})
        self.assertFalse(keys.has_igdb)
        self.assertFalse(keys.has_steamgriddb)
        self.assertEqual(keys.warnings, [])

    def test_reads_file_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keys.json"
            _write_keys(
                path,
                {
                    "steamgriddb_api_key": "sgdb-secret",
                    "twitch_client_id": "twitch-id",
                    "twitch_client_secret": "twitch-secret",
                },
            )
            keys = load_keys(path=path, environ={})
            self.assertEqual(keys.steamgriddb_api_key, "sgdb-secret")
            self.assertEqual(keys.twitch_client_id, "twitch-id")
            self.assertEqual(keys.twitch_client_secret, "twitch-secret")
            self.assertTrue(keys.has_igdb)
            self.assertTrue(keys.has_steamgriddb)
            self.assertEqual(keys.warnings, [])

    def test_env_overrides_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keys.json"
            _write_keys(
                path,
                {
                    "steamgriddb_api_key": "file-sgdb",
                    "twitch_client_id": "file-id",
                    "twitch_client_secret": "file-secret",
                },
            )
            keys = load_keys(
                path=path,
                environ={
                    ENV_STEAMGRIDDB: "env-sgdb",
                    ENV_TWITCH_ID: "env-id",
                    ENV_TWITCH_SECRET: "env-secret",
                },
            )
            self.assertEqual(keys.steamgriddb_api_key, "env-sgdb")
            self.assertEqual(keys.twitch_client_id, "env-id")
            self.assertEqual(keys.twitch_client_secret, "env-secret")

    def test_warns_when_group_or_world_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keys.json"
            _write_keys(
                path,
                {"steamgriddb_api_key": "sgdb-secret"},
                mode=0o644,
            )
            keys = load_keys(path=path, environ={})
            self.assertEqual(len(keys.warnings), 1)
            self.assertIn("chmod 600", keys.warnings[0])
            self.assertIn(str(path), keys.warnings[0])
            self.assertNotIn("sgdb-secret", keys.warnings[0])

    def test_redacted_summary_never_includes_values(self):
        keys = load_keys(
            path=Path("/nonexistent/keys.json"),
            environ={
                ENV_STEAMGRIDDB: "super-secret-key",
                ENV_TWITCH_ID: "id-value",
                ENV_TWITCH_SECRET: "secret-value",
            },
        )
        dumped = json.dumps(keys.redacted())
        self.assertNotIn("super-secret-key", dumped)
        self.assertNotIn("id-value", dumped)
        self.assertNotIn("secret-value", dumped)
        self.assertTrue(keys.redacted()["steamgriddb"])
        self.assertTrue(keys.redacted()["igdb"])

    def test_invalid_json_warns_without_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keys.json"
            path.write_text("{not json, steamgriddb_api_key: leaked}\n", encoding="utf-8")
            path.chmod(0o600)
            keys = load_keys(path=path, environ={})
            self.assertFalse(keys.has_steamgriddb)
            self.assertTrue(any("not valid JSON" in w for w in keys.warnings))
            self.assertFalse(any("leaked" in w for w in keys.warnings))

    def test_empty_strings_are_inactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keys.json"
            _write_keys(
                path,
                {
                    "steamgriddb_api_key": "   ",
                    "twitch_client_id": "",
                    "twitch_client_secret": "",
                },
            )
            keys = load_keys(path=path, environ={})
            self.assertFalse(keys.has_igdb)
            self.assertFalse(keys.has_steamgriddb)


class TestKeysExampleAndGitignore(unittest.TestCase):
    def test_example_has_empty_values_only(self):
        root = Path(__file__).resolve().parent.parent
        example = json.loads((root / "keys.example.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(example),
            {"steamgriddb_api_key", "twitch_client_id", "twitch_client_secret"},
        )
        self.assertTrue(all(v == "" for v in example.values()))

    def test_gitignore_covers_key_files(self):
        root = Path(__file__).resolve().parent.parent
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("keys.json", ignore)
        self.assertIn("*.keys.json", ignore)

    def test_repo_does_not_ship_real_keys_file(self):
        root = Path(__file__).resolve().parent.parent
        self.assertFalse((root / "keys.json").exists())
        extras = list(root.rglob("*.keys.json"))
        extras = [p for p in extras if ".git" not in p.parts]
        self.assertEqual(extras, [])


class TestKeysFileModeBits(unittest.TestCase):
    def test_group_writable_also_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keys.json"
            _write_keys(path, {"steamgriddb_api_key": "x"}, mode=0o660)
            keys = load_keys(path=path, environ={})
            self.assertTrue(keys.warnings)
            mode = path.stat().st_mode
            self.assertTrue(mode & (stat.S_IRWXG | stat.S_IRWXO))


if __name__ == "__main__":
    unittest.main()
