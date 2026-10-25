"""Known store/client launchers — not games. Skip IGDB name matching."""

from __future__ import annotations

from typing import Any

from ..model import normalize_title

# Normalized titles / desktop-file stems that are launchers, not games.
_LAUNCHER_KEYS = {
    "battlenet": "battlenet",
    "blizzardbattlenet": "battlenet",
    "blizzardapp": "battlenet",
    "steam": "steam",
    "lutris": "lutris",
    "heroic": "heroic",
    "heroicgameslauncher": "heroic",
    "eaapp": "ea",
    "ea": "ea",
    "origin": "ea",
    "electronicarts": "ea",
    "ubisoftconnect": "ubisoft",
    "ubisoft": "ubisoft",
    "uplay": "ubisoft",
    "goggalaxy": "gog",
    "gog": "gog",
    "geforcenow": "geforcenow",
    "nvidiageforcenow": "geforcenow",
}

_LAUNCHER_COPY = {
    "battlenet": (
        "Blizzard's desktop launcher for Warcraft, Diablo, Overwatch, "
        "and other Blizzard titles."
    ),
    "steam": "Valve's store, library, and launcher for Steam games.",
    "lutris": "Open-source game manager for Wine, emulators, and native Linux titles.",
    "heroic": "Open-source launcher for Epic, GOG, Amazon, and other stores.",
    "ea": "EA's desktop launcher for EA titles.",
    "ubisoft": "Ubisoft Connect launcher for Ubisoft games.",
    "gog": "GOG Galaxy launcher for DRM-free GOG titles.",
    "geforcenow": "NVIDIA GeForce NOW cloud gaming client.",
}

_LAUNCHER_EXEC_MARKERS = (
    "omarchy-launch-battlenet",
)


def _id_stem(game_id: str) -> str:
    text = str(game_id or "").strip()
    if not text:
        return ""
    return text.rsplit(":", 1)[-1]


def _launch_text(game: dict[str, Any]) -> str:
    launch = game.get("launch") or {}
    if not isinstance(launch, dict):
        return ""
    value = launch.get("value")
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(str(p) for p in value)
    return ""


def launcher_key(game: dict[str, Any] | None) -> str | None:
    """Return a launcher family key, or None when this row is a game."""
    if not game:
        return None
    title_key = normalize_title(str(game.get("title") or ""))
    if title_key in _LAUNCHER_KEYS:
        return _LAUNCHER_KEYS[title_key]
    stem_key = normalize_title(_id_stem(str(game.get("id") or "")))
    if stem_key in _LAUNCHER_KEYS:
        return _LAUNCHER_KEYS[stem_key]
    exec_line = _launch_text(game).casefold()
    if any(marker in exec_line for marker in _LAUNCHER_EXEC_MARKERS):
        return "battlenet"
    return None


def is_launcher(game: dict[str, Any] | None) -> bool:
    return launcher_key(game) is not None


def launcher_description(game: dict[str, Any] | None) -> str:
    key = launcher_key(game)
    if not key:
        return ""
    return _LAUNCHER_COPY.get(key, "")


def launcher_cache_looks_like_a_game(record: dict[str, Any] | None) -> bool:
    """True when a cached launcher record was filled from an IGDB game match."""
    if not record:
        return False
    used = record.get("sourcesUsed") or []
    if "igdb" in used:
        return True
    if record.get("releaseYear") or record.get("rating"):
        return True
    genres = record.get("genres") or []
    return bool(genres)
