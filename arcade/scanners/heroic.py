"""Heroic Games Launcher (Epic / GOG / Amazon / sideload)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..model import ArtSpec, Game, LaunchSpec, ScanError, TrackSpec, normalize_title
from ..paths import heroic_roots


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _art_from(info: dict) -> ArtSpec:
    cover = (
        info.get("art_square")
        or info.get("art_cover")
        or info.get("cover")
        or info.get("folder_name")
    )
    # folder_name is not art — ignore non-urls/paths
    if isinstance(cover, str) and (cover.startswith("http") or cover.startswith("/") or cover.startswith("file:")):
        if cover.startswith("/") and Path(cover).is_file():
            cover = Path(cover).as_uri()
        return ArtSpec(cover=cover)
    # Try nested
    for key in ("art", "metadata"):
        nested = info.get(key)
        if isinstance(nested, dict):
            a = _art_from(nested)
            if a.cover:
                return a
    return ArtSpec()


def _games_from_installed(path: Path, store: str, runner: str) -> list[Game]:
    if not path.is_file():
        return []
    data = _load_json(path)
    games: list[Game] = []
    # Formats vary: dict of appName -> info, or list, or {"games": [...]}
    items: list[tuple[str, dict]] = []
    if isinstance(data, dict):
        if "games" in data and isinstance(data["games"], list):
            for g in data["games"]:
                if isinstance(g, dict):
                    app = str(g.get("app_name") or g.get("appName") or g.get("id") or "")
                    items.append((app, g))
        else:
            for app, info in data.items():
                if isinstance(info, dict):
                    items.append((str(app), info))
    elif isinstance(data, list):
        for g in data:
            if isinstance(g, dict):
                app = str(g.get("app_name") or g.get("appName") or g.get("id") or "")
                items.append((app, g))

    for app_name, info in items:
        if not app_name:
            continue
        # Skip if explicitly not installed
        if info.get("is_installed") is False or info.get("isInstalled") is False:
            continue
        title = (
            info.get("title")
            or info.get("app_title")
            or info.get("name")
            or info.get("install_path")
            or app_name
        )
        install_path = info.get("install_path") or info.get("installPath") or info.get("path")
        if not install_path and store != "sideload":
            # Legendary installed.json always has install_path when installed
            if "executable" not in info and "install_size" not in info and "install_path" not in info:
                continue
        art = _art_from(info)
        steam_id = None
        for key in ("steam_appid", "steamAppId", "app_id"):
            if key in info:
                try:
                    steam_id = int(info[key])
                except (TypeError, ValueError):
                    pass
        uri = f"heroic://launch?appName={quote(app_name)}&runner={quote(runner)}"
        dedupe = [f"title:{normalize_title(str(title))}"]
        if steam_id:
            dedupe.insert(0, f"steam:{steam_id}")
        dedupe.insert(0, f"heroic:{store}:{app_name}")
        games.append(
            Game(
                id=f"heroic:{store}:{app_name}",
                title=str(title),
                source="heroic",
                store=store,
                runner="proton",
                steam_app_id=steam_id,
                launch=LaunchSpec(kind="uri", value=uri),
                track=TrackSpec(handoff=True),
                art=art,
                dedupe_keys=dedupe,
            )
        )
    return games


def scan() -> tuple[list[Game], list[ScanError]]:
    roots = heroic_roots()
    if not roots:
        return [], []
    games: list[Game] = []
    errors: list[ScanError] = []
    specs = [
        ("legendaryConfig/legendary/installed.json", "epic", "legendary"),
        ("gog_store/installed.json", "gog", "gog"),
        ("nile_config/nile/installed.json", "amazon", "nile"),
        ("sideload_apps/library.json", "sideload", "sideload"),
    ]
    for root in roots:
        for rel, store, runner in specs:
            path = root / rel
            try:
                games.extend(_games_from_installed(path, store, runner))
            except Exception as exc:  # noqa: BLE001
                errors.append(ScanError(source="heroic", error=f"{path}: {exc}"))
    by_id = {g.id: g for g in games}
    return list(by_id.values()), errors
