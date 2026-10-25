"""Local Steam userdata helpers (playtime / last played)."""

from __future__ import annotations

import time
from pathlib import Path

from .paths import steam_roots
from .vdf import parse_text


def playtime_map(root: Path) -> dict[int, tuple[int | None, str | None]]:
    """Return appid -> (playtime_minutes, last_played_iso) from localconfig.vdf."""
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
            apps = data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
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
                existing = out.get(appid)
                if existing is None or _newer(last, existing[1]):
                    out[appid] = (minutes, last)
    return out


def _newer(a: str | None, b: str | None) -> bool:
    if a and not b:
        return True
    if a and b:
        return a > b
    return False


def playtime_for_appid(
    appid: int,
    roots: list[Path] | None = None,
) -> tuple[int | None, str | None]:
    """Look up local Steam playtime for one appid across known Steam roots."""
    best: tuple[int | None, str | None] = (None, None)
    for root in roots if roots is not None else steam_roots():
        minutes, last = playtime_map(root).get(int(appid), (None, None))
        if last and (best[1] is None or last > best[1]):
            best = (minutes, last)
        elif best[0] is None and minutes is not None:
            best = (minutes, last)
    return best
