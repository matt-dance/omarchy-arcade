"""RetroArch playlist (.lpl) scanner."""

from __future__ import annotations

import json
from pathlib import Path

from ..model import ArtSpec, Game, LaunchSpec, ScanError, TrackSpec, normalize_title
from ..paths import home, xdg_config_home


def _playlist_dirs() -> list[Path]:
    return [
        xdg_config_home() / "retroarch" / "playlists",
        home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "playlists",
    ]


def scan() -> tuple[list[Game], list[ScanError]]:
    games: list[Game] = []
    errors: list[ScanError] = []
    found_any = False
    for directory in _playlist_dirs():
        if not directory.is_dir():
            continue
        found_any = True
        for lpl in directory.glob("*.lpl"):
            try:
                data = json.loads(lpl.read_text(encoding="utf-8", errors="replace"))
            except Exception as exc:  # noqa: BLE001
                errors.append(ScanError(source="retroarch", error=f"{lpl}: {exc}"))
                continue
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                continue
            system = lpl.stem
            for idx, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                path = item.get("path") or ""
                label = item.get("label") or Path(path).stem or f"{system}-{idx}"
                core = item.get("core_path") or "DETECT"
                if not path:
                    continue
                argv = ["retroarch"]
                if core and core != "DETECT":
                    argv.extend(["-L", core])
                argv.append(path)
                safe = normalize_title(str(label)) or str(idx)
                games.append(
                    Game(
                        id=f"retroarch:{system}:{safe}",
                        title=str(label),
                        source="retroarch",
                        runner="emulator",
                        platform=system,
                        launch=LaunchSpec(kind="argv", value=argv),
                        track=TrackSpec(
                            window_class="com.libretro.RetroArch",
                            handoff=False,
                        ),
                        art=ArtSpec(),
                        dedupe_keys=[
                            f"retroarch:{system}:{safe}",
                            f"title:{safe}",
                        ],
                    )
                )
    if not found_any:
        return [], []
    return games, errors
