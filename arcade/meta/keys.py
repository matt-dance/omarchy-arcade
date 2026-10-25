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
