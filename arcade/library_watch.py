"""Watch installed-game sources and request library rescans.

``arcaded`` owns the watches. After a coalesced change it emits ``rescan``
and ``Service.qml`` runs the existing ``arcade-scan`` path so the overlay
picks up ``library.json`` live (selection, favorites, hidden, and play
history are not stored in that file).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import ArcadeConfig, library_settings
from .paths import (
    application_dirs,
    bottles_data_dirs,
    heroic_roots,
    home,
    itch_db_paths,
    legendary_installed,
    library_path,
    lutris_data_dirs,
    steam_roots,
    xdg_config_home,
    xdg_data_home,
)
from .watch import Debouncer, FileWatcher, create_watcher


@dataclass(frozen=True)
class GameRef:
    id: str
    title: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title}


@dataclass(frozen=True)
class LibraryDiff:
    added: list[GameRef]
    removed: list[GameRef]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    def added_line(self) -> str:
        if not self.added:
            return ""
        if len(self.added) == 1:
            return f"Added: {self.added[0].title}"
        if len(self.added) <= 3:
            return "Added: " + ", ".join(item.title for item in self.added)
        return f"Added: {len(self.added)} games"

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        return {
            "added": [item.to_dict() for item in self.added],
            "removed": [item.to_dict() for item in self.removed],
        }


def _game_id(game: Any) -> str:
    if isinstance(game, dict):
        return str(game.get("id") or "")
    return str(getattr(game, "id", "") or "")


def _game_title(game: Any) -> str:
    if isinstance(game, dict):
        return str(game.get("title") or _game_id(game))
    return str(getattr(game, "title", None) or _game_id(game))


def diff_library(old: Iterable[Any] | None, new: Iterable[Any] | None) -> LibraryDiff:
    """Added / removed by stable game id. Order follows the new/old lists."""
    old_list = [g for g in (old or []) if _game_id(g)]
    new_list = [g for g in (new or []) if _game_id(g)]
    old_by = {_game_id(g): g for g in old_list}
    new_by = {_game_id(g): g for g in new_list}
    added = [
        GameRef(_game_id(g), _game_title(g))
        for g in new_list
        if _game_id(g) not in old_by
    ]
    removed = [
        GameRef(_game_id(g), _game_title(g))
        for g in old_list
        if _game_id(g) not in new_by
    ]
    # Dedupe if a list repeated an id
    seen_add: set[str] = set()
    uniq_add: list[GameRef] = []
    for item in added:
        if item.id in seen_add:
            continue
        seen_add.add(item.id)
        uniq_add.append(item)
    seen_rm: set[str] = set()
    uniq_rm: list[GameRef] = []
    for item in removed:
        if item.id in seen_rm:
            continue
        seen_rm.add(item.id)
        uniq_rm.append(item)
    return LibraryDiff(added=uniq_add, removed=uniq_rm)


def _add_path(out: list[Path], path: Path | None) -> None:
    if path is None:
        return
    out.append(path)


def collect_watch_paths(cfg: ArcadeConfig | None = None) -> list[Path]:
    """Existing files/dirs the scanners read. Shallow — never ``steamapps/common``."""
    paths: list[Path] = []
    enabled = cfg.source_enabled if cfg is not None else (lambda _name: True)

    if enabled("steam"):
        from .scanners.steam import library_folders

        for root in steam_roots():
            apps = root / "steamapps"
            _add_path(paths, apps)
            _add_path(paths, apps / "libraryfolders.vdf")
            for library in library_folders(root):
                _add_path(paths, library / "steamapps")
            userdata = root / "userdata"
            _add_path(paths, userdata)
            if userdata.is_dir():
                try:
                    users = list(userdata.iterdir())
                except OSError:
                    users = []
                for user in users:
                    if not user.is_dir() or not user.name.isdigit():
                        continue
                    config_dir = user / "config"
                    _add_path(paths, config_dir)
                    _add_path(paths, config_dir / "shortcuts.vdf")

    if enabled("heroic"):
        for root in heroic_roots():
            _add_path(paths, root)
            _add_path(paths, root / "legendaryConfig" / "legendary")
            _add_path(paths, root / "legendaryConfig" / "legendary" / "installed.json")
            _add_path(paths, root / "gog_store")
            _add_path(paths, root / "gog_store" / "installed.json")
            _add_path(paths, root / "nile_config" / "nile")
            _add_path(paths, root / "nile_config" / "nile" / "installed.json")
            _add_path(paths, root / "sideload_apps")
            _add_path(paths, root / "sideload_apps" / "library.json")

    if enabled("legendary"):
        for installed in legendary_installed():
            _add_path(paths, installed)
            _add_path(paths, installed.parent)
        _add_path(paths, xdg_config_home() / "legendary")
        _add_path(paths, home() / ".config" / "legendary")

    if enabled("lutris"):
        for data_dir in lutris_data_dirs():
            _add_path(paths, data_dir)
            _add_path(paths, data_dir / "pga.db")
        _add_path(paths, xdg_config_home() / "lutris")
        _add_path(paths, home() / ".var" / "app" / "net.lutris.Lutris" / "config" / "lutris")
        _add_path(paths, home() / ".var" / "app" / "net.lutris.Lutris" / "data" / "lutris")

    if enabled("bottles"):
        for data_dir in bottles_data_dirs():
            _add_path(paths, data_dir)
            bottles_root = data_dir / "bottles"
            _add_path(paths, bottles_root)
            if bottles_root.is_dir():
                try:
                    children = list(bottles_root.iterdir())
                except OSError:
                    children = []
                for bottle in children:
                    if bottle.is_dir():
                        _add_path(paths, bottle)
                        _add_path(paths, bottle / "bottle.yml")

    if enabled("itch"):
        for db in itch_db_paths():
            _add_path(paths, db)
            _add_path(paths, db.parent)
        _add_path(paths, xdg_config_home() / "itch" / "db")
        _add_path(paths, home() / ".var" / "app" / "io.itch.itch" / "config" / "itch" / "db")

    if enabled("desktop"):
        _add_path(paths, xdg_data_home() / "applications")
        for directory in application_dirs():
            _add_path(paths, directory)
        _add_path(paths, Path("/var/lib/flatpak/exports/share/applications"))
        _add_path(paths, xdg_data_home() / "flatpak" / "exports" / "share" / "applications")

    if enabled("retroarch"):
        _add_path(paths, xdg_config_home() / "retroarch" / "playlists")
        _add_path(
            paths,
            home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "playlists",
        )

    if enabled("roms"):
        roms = home() / "Games" / "roms"
        _add_path(paths, roms)
        if roms.is_dir():
            try:
                children = list(roms.iterdir())
            except OSError:
                children = []
            for child in children:
                if child.is_dir():
                    _add_path(paths, child)

    return _unique_existing(paths)


def _unique_existing(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        try:
            exists = path.exists()
        except OSError:
            continue
        if not exists:
            continue
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def library_is_stale(path: Path | None, stale_minutes: float, now: float | None = None) -> bool:
    """True when ``library.json`` is missing or older than ``stale_minutes``."""
    import time

    if stale_minutes <= 0:
        return True
    target = path or library_path()
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return True
    wall = time.time() if now is None else now
    return (wall - mtime) >= stale_minutes * 60.0


class LibraryMonitor:
    """Watch source paths, debounce, and invoke ``on_rescan(reason)``."""

    def __init__(
        self,
        cfg: ArcadeConfig,
        on_rescan: Callable[[str], None],
        library_file: Path | None = None,
        watcher: FileWatcher | None = None,
        now: Callable[[], float] | None = None,
        wall_now: Callable[[], float] | None = None,
    ) -> None:
        import time

        self._on_rescan = on_rescan
        self._library_file = library_file or library_path()
        self._now = now or time.monotonic
        self._wall = wall_now or time.time
        self._settings = library_settings(cfg)
        self.cfg = cfg
        self.debouncer = Debouncer(self._settings["debounce_s"])
        self._watcher = watcher
        self._owns_watcher = watcher is None
        self._last_resolve = 0.0
        self._watch_paths: list[Path] = []
        if self._settings["auto_watch"] and self._watcher is None:
            self._watcher = create_watcher()

    @property
    def backend(self) -> str:
        if not self._settings["auto_watch"]:
            return "off"
        if self._watcher is None:
            return "off"
        return self._watcher.backend

    @property
    def path_count(self) -> int:
        return len(self._watch_paths)

    def fds(self) -> list[int]:
        if self._watcher is None or self._watcher.fd is None:
            return []
        return [self._watcher.fd]

    def next_deadline(self) -> float | None:
        return self.debouncer.next_deadline()

    def start(self) -> None:
        self._apply_targets()
        self._last_resolve = self._now()
        if library_is_stale(self._library_file, self._settings["stale_minutes"], self._wall()):
            self._on_rescan("startup")

    def configure(self, cfg: ArcadeConfig) -> None:
        self.cfg = cfg
        self._settings = library_settings(cfg)
        self.debouncer.delay_s = self._settings["debounce_s"]
        if self._settings["auto_watch"]:
            if self._watcher is None:
                self._watcher = create_watcher()
                self._owns_watcher = True
            self._apply_targets()
        else:
            self.debouncer.clear()
            if self._owns_watcher and self._watcher is not None:
                self._watcher.close()
                self._watcher = None
            self._watch_paths = []

    def on_overlay_open(self) -> None:
        if library_is_stale(self._library_file, self._settings["stale_minutes"], self._wall()):
            self._on_rescan("open")

    def on_readable(self, fd: int) -> None:
        if self._watcher is None or fd != self._watcher.fd:
            return
        events = self._watcher.read()
        if events:
            self.debouncer.poke(self._now())

    def tick(self, now: float | None = None) -> None:
        now = self._now() if now is None else now
        if self._settings["auto_watch"] and self._watcher is not None:
            interval = self._settings["poll_interval_s"]
            if now - self._last_resolve >= interval:
                self._last_resolve = now
                retargeted = self._apply_targets()
                polled = bool(self._watcher.poll())
                if retargeted or polled:
                    self.debouncer.poke(now)
        if self.debouncer.ready(now):
            self.debouncer.clear()
            if self._settings["auto_watch"]:
                self._on_rescan("watch")

    def close(self) -> None:
        self.debouncer.clear()
        if self._owns_watcher and self._watcher is not None:
            self._watcher.close()
        self._watcher = None
        self._watch_paths = []

    def _apply_targets(self) -> bool:
        if self._watcher is None:
            return False
        paths = collect_watch_paths(self.cfg)
        changed = [str(p) for p in paths] != [str(p) for p in self._watch_paths]
        self._watch_paths = paths
        try:
            self._watcher.set_paths(paths)
        except Exception:
            return changed
        return changed
