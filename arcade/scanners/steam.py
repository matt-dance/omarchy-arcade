"""Steam library scanner (Proton titles + non-Steam shortcuts)."""

from __future__ import annotations

import re
import time
from pathlib import Path

from ..model import ArtSpec, Game, LaunchSpec, ScanError, TrackSpec, normalize_title
from ..paths import steam_roots
from ..vdf import parse_binary, parse_text, steam_shortcut_app_id

# Tool / runtime appids that are not games.
_STEAM_TOOLS = {
    228980,  # Steamworks Common Redistributables
    1070560,  # Steam Linux Runtime 1.0 (scout)
    1391110,  # Steam Linux Runtime 2.0 (soldier)
    1628350,  # Steam Linux Runtime 3.0 (sniper)
    4183110,  # Steam Linux Runtime 4.0
    4185400,  # Steam Linux Runtime 4.0 (arm64 companion, when present)
    1493710,  # Proton Experimental
    1887720,  # Proton 7.0
    1580130,  # Proton 6.3
    1420170,  # Proton 5.13
    1113280,  # Proton 5.0
    961940,  # Proton 4.2
    930400,  # Proton 3.16
    858280,  # Proton 3.7
    2180100,  # Proton 8.0
    2805730,  # Proton 9.0
    3658110,  # Proton 10.0
}

_PROTON_TOOL_RE = re.compile(
    r"^proton(\s+\d|\s+experimental|\s+hotfix|\s+next|$)",
    re.IGNORECASE,
)


def _library_folders(root: Path) -> list[Path]:
    vdf = root / "steamapps" / "libraryfolders.vdf"
    folders = [root]
    if not vdf.is_file():
        return folders
    try:
        data = parse_text(vdf.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return folders
    lib = data.get("libraryfolders") or data
    for _key, value in lib.items():
        if not isinstance(value, dict):
            continue
        path = value.get("path")
        if not path:
            continue
        p = Path(path)
        if (p / "steamapps").is_dir() and p not in folders:
            folders.append(p)
    return folders


def _acf_type(app: dict) -> str:
    """Best-effort Steam app type from an ACF AppState dict."""
    for key in ("type", "Type"):
        value = app.get(key)
        if value:
            return str(value).casefold()
    user = app.get("UserConfig") or app.get("userconfig") or {}
    if isinstance(user, dict):
        for key in ("type", "Type"):
            value = user.get(key)
            if value:
                return str(value).casefold()
    return ""


def _is_steam_tool(app: dict, appid: int, name: str) -> bool:
    """Filter Proton, Steam Linux Runtime, Steamworks redistributables, etc."""
    if appid in _STEAM_TOOLS:
        return True
    if _acf_type(app) in {"tool", "config"}:
        return True
    n = (name or "").casefold().strip()
    if n.startswith("steam linux runtime") or n.startswith("steamworks"):
        return True
    if _PROTON_TOOL_RE.match(n):
        return True
    installdir = str(app.get("installdir") or app.get("InstallDir") or "").casefold()
    compact = installdir.replace(" ", "").replace("_", "")
    if "steamlinuxruntime" in compact:
        return True
    if compact.startswith("proton") and "protonvpn" not in compact:
        return True
    return False


def _manifest_installed(manifest: dict) -> bool:
    state = manifest.get("StateFlags") or manifest.get("stateflags") or "0"
    try:
        flags = int(state)
    except ValueError:
        return False
    # Bit 2 (4) = Fully Installed
    return bool(flags & 4)


def _hero_for(root: Path, appid: int) -> str | None:
    cache = root / "appcache" / "librarycache"
    for name in (
        f"{appid}/library_hero.jpg",
        f"{appid}/library_hero.png",
        f"{appid}/library_hero_2x.jpg",
        f"{appid}_library_hero.jpg",
        f"{appid}_library_hero.png",
    ):
        p = cache / name
        if p.is_file():
            return p.as_uri()
    userdata = root / "userdata"
    if userdata.is_dir():
        for user in userdata.iterdir():
            if not user.is_dir() or not user.name.isdigit():
                continue
            for ext in ("_hero.jpg", "_hero.png"):
                g = user / "config" / "grid" / f"{appid}{ext}"
                if g.is_file():
                    return g.as_uri()
    return None


def _cover_for(root: Path, appid: int) -> str | None:
    cache = root / "appcache" / "librarycache"
    # Newer Steam: per-app folder
    for name in (
        f"{appid}/library_600x900.jpg",
        f"{appid}/library_capsule.jpg",
        f"{appid}_library_600x900.jpg",
        f"{appid}_library_capsule.jpg",
        f"{appid}_header.jpg",
    ):
        p = cache / name
        if p.is_file():
            return p.as_uri()
    # Custom grid
    userdata = root / "userdata"
    if userdata.is_dir():
        for user in userdata.iterdir():
            if not user.is_dir() or not user.name.isdigit():
                continue
            for ext in ("p.jpg", "p.png", ".jpg", ".png"):
                g = user / "config" / "grid" / f"{appid}{ext}"
                if g.is_file():
                    return g.as_uri()
    return None


def _playtime_map(root: Path) -> dict[int, tuple[int | None, str | None]]:
    """Return appid -> (playtime_minutes, last_played_iso)."""
    out: dict[int, tuple[int | None, str | None]] = {}
    userdata = root / "userdata"
    if not userdata.is_dir():
        return out
    for user in userdata.iterdir():
        cfg = user / "config" / "localconfig.vdf"
        if not cfg.is_file():
            continue
        try:
            data = parse_text(cfg.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        try:
            apps = (
                data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
            )
        except (KeyError, TypeError):
            continue
        if not isinstance(apps, dict):
            continue
        for appid_s, info in apps.items():
            if not isinstance(info, dict):
                continue
            try:
                appid = int(appid_s)
            except ValueError:
                continue
            minutes = None
            if "Playtime" in info:
                try:
                    minutes = int(info["Playtime"])
                except ValueError:
                    minutes = None
            last = None
            if "LastPlayed" in info:
                try:
                    ts = int(info["LastPlayed"])
                    if ts > 0:
                        last = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
                except ValueError:
                    pass
            if minutes is not None or last is not None:
                out[appid] = (minutes, last)
    return out


def _scan_manifests(root: Path, playtimes: dict) -> list[Game]:
    games: list[Game] = []
    for library in _library_folders(root):
        apps = library / "steamapps"
        for acf in apps.glob("appmanifest_*.acf"):
            try:
                data = parse_text(acf.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            app = data.get("AppState") or data.get("appstate") or {}
            if not isinstance(app, dict):
                continue
            try:
                appid = int(app.get("appid") or app.get("appID") or 0)
            except ValueError:
                continue
            if not appid:
                continue
            name = app.get("name") or f"Steam {appid}"
            if _is_steam_tool(app, appid, name):
                continue
            if not _manifest_installed(app):
                continue
            minutes, last = playtimes.get(appid, (None, None))
            cover = _cover_for(root, appid)
            hero = _hero_for(root, appid)
            games.append(
                Game(
                    id=f"steam:{appid}",
                    title=name,
                    source="steam",
                    store="steam",
                    runner="proton",
                    steam_app_id=appid,
                    playtime_minutes=minutes,
                    last_played=last,
                    launch=LaunchSpec(kind="uri", value=f"steam://rungameid/{appid}"),
                    track=TrackSpec(
                        window_class=f"steam_app_{appid}",
                        steam_app_id=appid,
                        handoff=True,
                    ),
                    art=ArtSpec(cover=cover, hero=hero),
                    dedupe_keys=[f"steam:{appid}", f"title:{normalize_title(name)}"],
                )
            )
    return games


def _scan_shortcuts(root: Path) -> list[Game]:
    games: list[Game] = []
    userdata = root / "userdata"
    if not userdata.is_dir():
        return games
    for user in userdata.iterdir():
        shortcuts = user / "config" / "shortcuts.vdf"
        if not shortcuts.is_file():
            continue
        try:
            data = parse_binary(shortcuts.read_bytes())
        except Exception:
            continue
        entries = data.get("shortcuts") or data
        if not isinstance(entries, dict):
            continue
        for _idx, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            title = entry.get("AppName") or entry.get("appname") or "Non-Steam Game"
            appid_raw = entry.get("appid") or entry.get("AppID")
            try:
                local_id = int(appid_raw)
            except (TypeError, ValueError):
                # Derive from title hash the way Steam does when missing — skip
                continue
            steam_id = steam_shortcut_app_id(local_id & 0xFFFFFFFF)
            exe = entry.get("Exe") or entry.get("exe") or ""
            launch = LaunchSpec(kind="uri", value=f"steam://rungameid/{steam_id}")
            icon = entry.get("icon") or entry.get("Icon") or None
            cover = None
            if icon and Path(str(icon).strip('"')).is_file():
                cover = Path(str(icon).strip('"')).as_uri()
            games.append(
                Game(
                    id=f"steam:shortcut:{local_id & 0xFFFFFFFF}",
                    title=str(title),
                    source="steam",
                    store="steam",
                    runner="proton" if exe else "native",
                    steam_app_id=steam_id,
                    launch=launch,
                    track=TrackSpec(steam_app_id=steam_id, handoff=True),
                    art=ArtSpec(cover=cover, icon=cover),
                    description=str(exe).strip('"') if exe else None,
                    dedupe_keys=[
                        f"steam:{steam_id}",
                        f"title:{normalize_title(str(title))}",
                    ],
                )
            )
    return games


def scan() -> tuple[list[Game], list[ScanError]]:
    roots = steam_roots()
    if not roots:
        return [], []
    games: list[Game] = []
    errors: list[ScanError] = []
    for root in roots:
        try:
            playtimes = _playtime_map(root)
            games.extend(_scan_manifests(root, playtimes))
            games.extend(_scan_shortcuts(root))
        except Exception as exc:  # noqa: BLE001
            errors.append(ScanError(source="steam", error=f"{root}: {exc}"))
    # Deduplicate by id across roots
    by_id: dict[str, Game] = {}
    for g in games:
        by_id.setdefault(g.id, g)
    return list(by_id.values()), errors
