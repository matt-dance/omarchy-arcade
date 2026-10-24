"""Scan .desktop entries: native, Flatpak, GFN plugin, RetroArch launchers, web apps."""

from __future__ import annotations

import shlex
from pathlib import Path

from ..model import (
    ArtSpec,
    Game,
    LaunchSpec,
    ScanError,
    TrackSpec,
    normalize_title,
    strip_source_title_prefix,
)
from ..paths import application_dirs

# Launchers themselves — not games.
_SKIP_IDS = {
    "steam",
    "steam-native",
    "com.valvesoftware.Steam",
    "heroic",
    "com.heroicgameslauncher.hgl",
    "net.lutris.Lutris",
    "lutris",
    "com.usebottles.bottles",
    "bottles",
    "io.itch.itch",
    "itch",
    "com.nvidia.geforcenow",
    "retroarch",
    "org.libretro.RetroArch",
    "com.libretro.RetroArch",
    "minecraft-launcher",
    "org.prismlauncher.PrismLauncher",
    "com.moonlight_stream.Moonlight",
    "moonlight",
}

# NVIDIA GeForce NOW client — never a library title.
_GFN_CLIENT_IDS = {
    "com.nvidia.geforcenow",
    "nvidia-geforcenow",
    "geforcenow",
    "geforce-now",
}
_GFN_CLIENT_NAMES = {
    "geforce now",
    "nvidia geforce now",
    "nvidia® geforce now",
}
_GFN_PLUGIN_PREFIXES = (
    "matt-dance.gfn",
    "matt-dance.gfn-omarchy",
)

_SKIP_EXEC_PREFIXES = (
    "steam %U",
    "steam steam://",
)


def _parse_desktop(path: Path) -> dict[str, str] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    in_desktop = False
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_desktop = line.lower() == "[desktop entry]"
            continue
        if not in_desktop or "=" not in line:
            continue
        key, _, value = line.partition("=")
        fields.setdefault(key.strip(), value.strip())
    if not fields.get("Name") or not fields.get("Exec"):
        return None
    if fields.get("Type", "Application") != "Application":
        return None
    return fields


def _is_hidden(fields: dict[str, str]) -> bool:
    return fields.get("NoDisplay", "").lower() in ("true", "1") or fields.get(
        "Hidden", ""
    ).lower() in ("true", "1")


def _categories(fields: dict[str, str]) -> set[str]:
    return {c for c in fields.get("Categories", "").split(";") if c}


def _is_gfn_client(fields: dict[str, str], stem: str) -> bool:
    if stem in _GFN_CLIENT_IDS or stem in _SKIP_IDS and "geforce" in stem:
        return True
    name = fields.get("Name", "").casefold().strip()
    if name in _GFN_CLIENT_NAMES:
        return True
    exec_line = fields.get("Exec", "").casefold()
    if "gfn-play.sh" in exec_line or any(k.startswith("X-GFN-") for k in fields):
        return False
    if "geforcenow" in exec_line or "geforce now" in exec_line:
        return True
    return False


def _is_gfn_launcher(fields: dict[str, str], stem: str) -> bool:
    """True for a GeForce NOW Menu plugin title, never the GFN client."""
    if _is_gfn_client(fields, stem):
        return False
    plugin = fields.get("X-Omarchy-Plugin", "")
    if any(plugin == p or plugin.startswith(p + ".") or plugin.startswith(p + "-") for p in _GFN_PLUGIN_PREFIXES):
        return True
    if plugin.startswith("matt-dance.gfn"):
        return True
    if any(key.startswith("X-GFN-") for key in fields):
        return True
    if stem.startswith("gfn-"):
        return True
    exec_line = fields.get("Exec", "")
    if "gfn-play.sh" in exec_line:
        return True
    return False


def _is_game(fields: dict[str, str], stem: str = "") -> str | None:
    """Return a source tag if this desktop entry should appear, else None."""
    if _is_gfn_launcher(fields, stem):
        return "gfn"
    cats = _categories(fields)
    exec_line = fields.get("Exec", "")
    if "omarchy-launch-webapp" in exec_line and (
        "xbox.com" in exec_line.lower() or "xbox" in fields.get("Name", "").lower()
    ):
        return "webapp"
    if "omarchy-launch-battlenet" in exec_line:
        return "desktop"
    if "Game" in cats or "Emulator" in cats:
        return "desktop"
    # Explicit gaming keywords in Name for known Omarchy webapps without Game category
    name = fields.get("Name", "").lower()
    if _is_gfn_client(fields, stem) or name in _GFN_CLIENT_NAMES:
        return None
    if any(k in name for k in ("xbox cloud", "minecraft")):
        return "webapp" if "omarchy-launch-webapp" in exec_line else "desktop"
    return None


def _icon_uri(icon: str) -> str | None:
    if not icon:
        return None
    p = Path(icon)
    if p.is_file():
        return p.as_uri()
    if icon.startswith("/") and Path(icon).is_file():
        return Path(icon).as_uri()
    return None  # theme icon name — QML/IconTheme can resolve later


def _launch_from_exec(exec_line: str, path: Path) -> LaunchSpec:
    # Prefer launching via the desktop file so Field codes and Flatpak work.
    return LaunchSpec(kind="desktop", value=str(path))


def _argv_fallback(exec_line: str) -> list[str]:
    # Strip desktop field codes
    cleaned = exec_line
    for code in ("%f", "%F", "%u", "%U", "%i", "%c", "%k"):
        cleaned = cleaned.replace(code, "")
    try:
        return [p for p in shlex.split(cleaned) if p]
    except ValueError:
        return cleaned.split()


def scan() -> tuple[list[Game], list[ScanError]]:
    games: list[Game] = []
    errors: list[ScanError] = []
    seen_ids: set[str] = set()

    for directory in application_dirs():
        try:
            entries = sorted(directory.glob("*.desktop"))
        except OSError as exc:
            errors.append(ScanError(source="desktop", error=f"{directory}: {exc}"))
            continue
        for path in entries:
            stem = path.stem
            if stem.startswith("steam_app_"):
                # Steam scanner owns steam_app_* shortcuts.
                continue
            if stem in _SKIP_IDS or stem in _GFN_CLIENT_IDS:
                continue
            fields = _parse_desktop(path)
            if not fields:
                continue
            source = _is_game(fields, stem)
            if not source:
                continue
            # Plugin-managed GFN launchers stay in the library even when the
            # leftover slug file is marked NoDisplay after a cms-id rewrite.
            if source != "gfn" and _is_hidden(fields):
                continue
            if _is_gfn_client(fields, stem):
                continue
            exec_line = fields["Exec"]
            if any(exec_line.lower().startswith(p) for p in _SKIP_EXEC_PREFIXES):
                # Bare Steam launcher or steam://open — not a game
                if "rungameid" not in exec_line.lower():
                    continue
            # Fold steam://rungameid desktop wrappers into steam source via dedupe
            steam_app_id = None
            if "steam://rungameid/" in exec_line:
                try:
                    steam_app_id = int(exec_line.split("steam://rungameid/")[1].split()[0].strip("\"'"))
                except (IndexError, ValueError):
                    steam_app_id = None
            title = fields["Name"]
            # Strip "GFN - " prefix for display but keep identity
            store = None
            runner = "native"
            if source == "gfn":
                store = fields.get("X-GFN-AppStore") or "gfn"
                runner = "cloud"
                title = strip_source_title_prefix(title)
            elif "flatpak" in exec_line:
                runner = "flatpak"
            elif "Emulator" in _categories(fields) or "retroarch" in exec_line:
                runner = "emulator"
                source = "desktop"
            elif "proton" in exec_line.lower() or "umu-run" in exec_line or "wine" in exec_line.lower():
                runner = "proton"
            elif source == "webapp":
                runner = "cloud"
                store = "xbox-cloud" if "xbox" in title.lower() else None

            gid = f"{source}:{stem}"
            if steam_app_id is not None:
                gid = f"desktop:steam:{steam_app_id}"
            if gid in seen_ids:
                continue
            seen_ids.add(gid)

            icon = _icon_uri(fields.get("Icon", ""))
            dedupe = [f"title:{normalize_title(title)}"]
            if steam_app_id is not None:
                dedupe.insert(0, f"steam:{steam_app_id}")
            if fields.get("X-GFN-CmsId"):
                dedupe.insert(0, f"gfn:{fields['X-GFN-CmsId']}")

            games.append(
                Game(
                    id=gid,
                    title=title,
                    source=source,
                    store=store,
                    runner=runner,
                    steam_app_id=steam_app_id,
                    launch=_launch_from_exec(exec_line, path),
                    track=TrackSpec(
                        window_class="GeForceNOW" if source == "gfn" else None,
                        steam_app_id=steam_app_id,
                        handoff=source in ("gfn", "webapp") or steam_app_id is not None,
                    ),
                    art=ArtSpec(cover=icon, icon=icon),
                    description=fields.get("Comment"),
                    dedupe_keys=dedupe,
                )
            )
            # Keep argv for debugging
            _ = _argv_fallback(exec_line)
    return games, errors
