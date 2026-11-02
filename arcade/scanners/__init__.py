"""Library scanners for each game source."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Callable

from ..config import ArcadeConfig
from ..model import Game, ScanError, merge_games
from . import bottles, desktop, heroic, itch, legendary, lutris, retroarch, roms, steam

ScanFn = Callable[[], tuple[list[Game], list[ScanError]]]

SCANNER_MODULES: dict[str, ModuleType] = {
    "steam": steam,
    "heroic": heroic,
    "legendary": legendary,
    "lutris": lutris,
    "bottles": bottles,
    "itch": itch,
    "desktop": desktop,
    "retroarch": retroarch,
    "roms": roms,
}

SCANNERS: dict[str, ScanFn] = {name: module.scan for name, module in SCANNER_MODULES.items()}


def scanner_watch_paths(cfg: ArcadeConfig | None = None) -> dict[str, list[Path]]:
    """Per-scanner filesystem inputs (may not exist yet)."""
    out: dict[str, list[Path]] = {}
    for name, module in SCANNER_MODULES.items():
        if cfg is not None and not cfg.source_enabled(name):
            continue
        fn = getattr(module, "watch_paths", None)
        if fn is None:
            continue
        try:
            paths = list(fn())
        except Exception:
            paths = []
        out[name] = paths
    return out


def run_all(cfg: ArcadeConfig | None = None) -> tuple[list[Game], list[ScanError]]:
    games: list[Game] = []
    errors: list[ScanError] = []
    sources = cfg.sources if cfg else {}
    for name, fn in SCANNERS.items():
        if cfg is not None and not cfg.source_enabled(name):
            continue
        if cfg is None and sources.get(name) is False:
            continue
        try:
            found, errs = fn()
        except Exception as exc:  # noqa: BLE001 — scanners must never kill the run
            errors.append(ScanError(source=name, error=str(exc)))
            continue
        games.extend(found)
        errors.extend(errs)
    return merge_games(games), errors
