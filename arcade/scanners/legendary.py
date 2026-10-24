"""Standalone Legendary (Epic) installed.json."""

from __future__ import annotations

import json

from ..model import ArtSpec, Game, LaunchSpec, ScanError, TrackSpec, normalize_title
from ..paths import legendary_installed


def scan() -> tuple[list[Game], list[ScanError]]:
    paths = legendary_installed()
    if not paths:
        return [], []
    games: list[Game] = []
    errors: list[ScanError] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(ScanError(source="legendary", error=f"{path}: {exc}"))
            continue
        if not isinstance(data, dict):
            continue
        for app_name, info in data.items():
            if not isinstance(info, dict):
                continue
            title = info.get("title") or info.get("app_title") or app_name
            games.append(
                Game(
                    id=f"legendary:{app_name}",
                    title=str(title),
                    source="legendary",
                    store="epic",
                    runner="proton",
                    launch=LaunchSpec(
                        kind="argv",
                        value=["legendary", "launch", str(app_name)],
                    ),
                    track=TrackSpec(handoff=True),
                    art=ArtSpec(),
                    dedupe_keys=[
                        f"legendary:{app_name}",
                        f"heroic:epic:{app_name}",
                        f"title:{normalize_title(str(title))}",
                    ],
                )
            )
    return games, errors
