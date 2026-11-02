"""XDG and Steam/Heroic/Lutris path helpers."""

from __future__ import annotations

import os
from pathlib import Path


PLUGIN_ID = "matt-dance.arcade"


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (home() / ".config"))


def xdg_cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or (home() / ".cache"))


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or (home() / ".local" / "state"))


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or (home() / ".local" / "share"))


def xdg_data_dirs() -> list[Path]:
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [Path(p) for p in raw.split(":") if p]
    # Flatpak exports
    dirs.extend(
        [
            Path("/var/lib/flatpak/exports/share"),
            xdg_data_home() / "flatpak" / "exports" / "share",
        ]
    )
    return dirs


def arcade_config_dir() -> Path:
    return xdg_config_home() / "omarchy" / "arcade"


def plugin_user_config_dir() -> Path:
    """Plugin-owned config (API keys). Distinct from arcade.toml."""
    return xdg_config_home() / PLUGIN_ID


def keys_path() -> Path:
    return plugin_user_config_dir() / "keys.json"


def arcade_cache_dir() -> Path:
    return xdg_cache_home() / PLUGIN_ID


def meta_cache_dir() -> Path:
    return arcade_cache_dir() / "meta"


def arcade_state_dir() -> Path:
    return xdg_state_home() / PLUGIN_ID


def library_path() -> Path:
    return arcade_cache_dir() / "library.json"


def user_config_path() -> Path:
    return arcade_config_dir() / "arcade.toml"


def default_config_path(plugin_dir: Path | None = None) -> Path:
    if plugin_dir is not None:
        return plugin_dir / "default" / "arcade.toml"
    # When running from a checkout or installed plugin
    here = Path(__file__).resolve().parent.parent
    return here / "default" / "arcade.toml"


def expand_user(path: str) -> Path:
    return Path(os.path.expanduser(path))


def steam_roots() -> list[Path]:
    h = home()
    candidates = [
        h / ".local" / "share" / "Steam",
        h / ".steam" / "steam",
        h / ".steam" / "root",
        h / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    ]
    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        try:
            resolved = p.resolve()
        except OSError:
            continue
        if resolved in seen or not (resolved / "steamapps").is_dir():
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def heroic_roots() -> list[Path]:
    h = home()
    candidates = [
        xdg_config_home() / "heroic",
        h / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic",
    ]
    return [p for p in candidates if p.is_dir()]


def lutris_data_dirs() -> list[Path]:
    h = home()
    candidates = [
        xdg_data_home() / "lutris",
        h / ".var" / "app" / "net.lutris.Lutris" / "data" / "lutris",
    ]
    return [p for p in candidates if p.is_dir()]


def bottles_data_dirs() -> list[Path]:
    h = home()
    candidates = [
        xdg_data_home() / "bottles",
        h / ".var" / "app" / "com.usebottles.bottles" / "data" / "bottles",
    ]
    return [p for p in candidates if p.is_dir()]


def itch_db_paths() -> list[Path]:
    h = home()
    candidates = [
        xdg_config_home() / "itch" / "db" / "butler.db",
        h / ".var" / "app" / "io.itch.itch" / "config" / "itch" / "db" / "butler.db",
    ]
    return [p for p in candidates if p.is_file()]


def legendary_installed() -> list[Path]:
    candidates = [
        xdg_config_home() / "legendary" / "installed.json",
        home() / ".config" / "legendary" / "installed.json",
    ]
    return [p for p in candidates if p.is_file()]


GFN_PLUGIN_IDS = ("matt-dance.gfn-omarchy", "matt-dance.gfn")


def application_dir_candidates() -> list[Path]:
    """Application dirs the desktop scanner reads, including ones not created yet."""
    dirs = [xdg_data_home() / "applications"]
    for d in xdg_data_dirs():
        dirs.append(d / "applications")
    return dirs


def gfn_plugin_paths() -> list[Path]:
    """GeForce NOW Menu plugin state, cache, and Omarchy menu block.

    ``write-desktop-entry.sh`` writes ``gfn-*.desktop`` under applications/
    via a hidden ``.gfn-write.*`` subdir, then records
    ``$XDG_DATA_HOME/matt-dance.gfn-omarchy/games.json`` and rewrites the
    ``gfn-games`` block in ``omarchy-menu.jsonc``.
    """
    out: list[Path] = []
    for plugin_id in GFN_PLUGIN_IDS:
        out.append(xdg_data_home() / plugin_id)
        out.append(xdg_data_home() / plugin_id / "games.json")
        out.append(xdg_config_home() / plugin_id)
        out.append(xdg_cache_home() / plugin_id)
        out.append(xdg_state_home() / plugin_id)
        out.append(xdg_config_home() / "omarchy" / "plugins" / plugin_id)
    out.append(xdg_data_home() / "icons" / "gfn")
    out.append(xdg_config_home() / "omarchy" / "extensions")
    out.append(xdg_config_home() / "omarchy" / "extensions" / "omarchy-menu.jsonc")
    return out


def application_dirs() -> list[Path]:
    dirs = [xdg_data_home() / "applications"]
    for d in xdg_data_dirs():
        dirs.append(d / "applications")
    # Deduplicate while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for d in dirs:
        try:
            r = d.resolve()
        except OSError:
            r = d
        if r in seen:
            continue
        seen.add(r)
        if d.is_dir():
            out.append(d)
    return out
