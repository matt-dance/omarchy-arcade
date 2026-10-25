"""Optional API keys for IGDB (Twitch) and SteamGridDB.

The repo is public. Keys are never shipped, never logged, and are read only from
`~/.config/matt-dance.arcade/keys.json` plus environment-variable overrides.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ..paths import keys_path as default_keys_path

ENV_STEAMGRIDDB = "ARCADE_STEAMGRIDDB_API_KEY"
ENV_TWITCH_ID = "ARCADE_TWITCH_CLIENT_ID"
ENV_TWITCH_SECRET = "ARCADE_TWITCH_CLIENT_SECRET"

_FILE_FIELDS = (
    "steamgriddb_api_key",
    "twitch_client_id",
    "twitch_client_secret",
)


@dataclass(frozen=True)
class Keys:
    steamgriddb_api_key: str | None = None
    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def has_igdb(self) -> bool:
        return bool(self.twitch_client_id and self.twitch_client_secret)

    @property
    def has_steamgriddb(self) -> bool:
        return bool(self.steamgriddb_api_key)

    def redacted(self) -> dict[str, bool | list[str]]:
        """Safe summary for logs / CLI — booleans only, never values."""
        return {
            "steamgriddb": self.has_steamgriddb,
            "igdb": self.has_igdb,
            "warnings": list(self.warnings),
        }


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_keys(
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Keys:
    """Load keys from the config file, then apply env-var overrides.

    Environment variables win so a session can inject keys without writing
    them to disk. Missing file or empty fields are fine — those sources stay off.
    """
    env = environ if environ is not None else os.environ
    warnings: list[str] = []
    data: dict[str, object] = {}
    keys_file = path if path is not None else default_keys_path()
    if keys_file.is_file():
        mode = keys_file.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            warnings.append(
                f"{keys_file} is group/world readable; run chmod 600 {keys_file}"
            )
        try:
            parsed = json.loads(keys_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            warnings.append(f"{keys_file} is not valid JSON")
            parsed = {}
        if isinstance(parsed, dict):
            data = parsed

    def pick(field: str, env_name: str) -> str | None:
        override = _clean(env.get(env_name, ""))
        if override:
            return override
        return _clean(data.get(field))

    # Touch expected fields so a typo in the example file does not silently
    # accept unknown names as configured.
    _ = {name: data.get(name) for name in _FILE_FIELDS}

    return Keys(
        steamgriddb_api_key=pick("steamgriddb_api_key", ENV_STEAMGRIDDB),
        twitch_client_id=pick("twitch_client_id", ENV_TWITCH_ID),
        twitch_client_secret=pick("twitch_client_secret", ENV_TWITCH_SECRET),
        warnings=warnings,
    )


# Short names used by bin/arcade-keys and the overlay, so the overlay never
# needs to know the file's field names.
FIELD_ALIASES = {
    "steamgriddb": "steamgriddb_api_key",
    "twitch-id": "twitch_client_id",
    "twitch-secret": "twitch_client_secret",
}
_ENV_FOR_FIELD = {
    "steamgriddb_api_key": ENV_STEAMGRIDDB,
    "twitch_client_id": ENV_TWITCH_ID,
    "twitch_client_secret": ENV_TWITCH_SECRET,
}
MAX_KEY_LENGTH = 256


class KeyValueError(ValueError):
    """Bad field name or key value. Messages never include the value."""


def resolve_field(name: str) -> str:
    field_name = FIELD_ALIASES.get(name, name)
    if field_name not in _FILE_FIELDS:
        raise KeyValueError(f"unknown key {name!r}; expected one of {', '.join(FIELD_ALIASES)}")
    return field_name


def clean_value(raw: str) -> str:
    """Trim a pasted key and reject obvious non-keys (multi-line clipboard, prose)."""
    value = (raw or "").strip().strip("\"'")
    if not value:
        raise KeyValueError("empty value")
    if len(value) > MAX_KEY_LENGTH:
        raise KeyValueError("value is too long to be an API key")
    if any(ch.isspace() for ch in value) or not value.isprintable():
        raise KeyValueError("value contains spaces or control characters")
    return value


def _read_file(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_private(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_key(name: str, raw_value: str, path: Path | None = None) -> str:
    """Store one key in keys.json (mode 0600). Returns the canonical field name."""
    field_name = resolve_field(name)
    value = clean_value(raw_value)
    keys_file = path if path is not None else default_keys_path()
    data = _read_file(keys_file)
    for known in _FILE_FIELDS:
        data.setdefault(known, "")
    data[field_name] = value
    _write_private(keys_file, data)
    return field_name


def remove_keys(names: list[str] | None = None, path: Path | None = None) -> list[str]:
    """Blank the given fields (all when ``names`` is empty). Returns cleared fields."""
    fields = [resolve_field(n) for n in names] if names else list(_FILE_FIELDS)
    keys_file = path if path is not None else default_keys_path()
    if not keys_file.is_file():
        return []
    data = _read_file(keys_file)
    for field_name in fields:
        data[field_name] = ""
    _write_private(keys_file, data)
    return fields


def key_status(path: Path | None = None, environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Which keys are configured — booleans only, safe to print or log."""
    env = environ if environ is not None else os.environ
    keys_file = path if path is not None else default_keys_path()
    keys = load_keys(keys_file, env)
    fields = {}
    for alias, field_name in FIELD_ALIASES.items():
        fields[alias] = {
            "set": bool(getattr(keys, field_name)),
            "fromEnv": bool(_clean(env.get(_ENV_FOR_FIELD[field_name], ""))),
        }
    return {
        "steamgriddb": keys.has_steamgriddb,
        "igdb": keys.has_igdb,
        "fields": fields,
        "file": str(keys_file),
        "warnings": list(keys.warnings),
    }
