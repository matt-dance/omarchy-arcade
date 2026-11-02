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
    home,
    library_path,
    xdg_cache_home,
    xdg_config_home,
    xdg_data_dirs,
    xdg_data_home,
    xdg_state_home,
)
from .scanners import scanner_watch_paths
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


@dataclass(frozen=True)
class WatchTarget:
    """A directory to watch. ``names`` limits events when the dir is a wide ancestor."""

    directory: Path
    names: frozenset[str] | None = None


def collect_source_paths(cfg: ArcadeConfig | None = None) -> list[Path]:
    """Every path scanners read, including ones that do not exist yet."""
    paths: list[Path] = []
    for _name, items in scanner_watch_paths(cfg).items():
        paths.extend(items)
    return _unique_paths(paths)


def collect_watch_paths(cfg: ArcadeConfig | None = None) -> list[Path]:
    """Directories (and existing files) handed to the watcher."""
    return [t.directory for t in collect_watch_targets(cfg)]


def collect_watch_targets(cfg: ArcadeConfig | None = None) -> list[WatchTarget]:
    """Watch parents of files so atomic replace / editor temps are visible.

    Missing sources watch one existing ancestor. Wide ancestors
    (``$HOME``, XDG roots) are name-filtered so ``~/.local/share`` is not
    a firehose.
    """
    stop = _resolved(home())
    wide = wide_watch_roots(stop)
    merged: dict[Path, frozenset[str] | None] = {}
    for source in collect_source_paths(cfg):
        for target in targets_for_source(source, stop_at=stop, wide=wide):
            key = _resolved(target.directory) or target.directory
            if key not in merged or target.names is None:
                merged[key] = target.names
            elif merged[key] is not None and target.names is not None:
                merged[key] = merged[key] | target.names
    return [WatchTarget(directory=path, names=names) for path, names in merged.items()]


def wide_watch_roots(stop_at: Path | None = None) -> set[Path]:
    """Ancestors that must not be watched unfiltered."""
    stop = _resolved(stop_at if stop_at is not None else home())
    roots = {stop}
    extras = [
        stop / ".local",
        stop / ".local" / "share",
        stop / ".local" / "state",
        stop / ".config",
        stop / ".cache",
        stop / ".var",
        stop / ".var" / "app",
        stop / ".steam",
        xdg_data_home(),
        xdg_config_home(),
        xdg_cache_home(),
        xdg_state_home(),
    ]
    extras.extend(xdg_data_dirs())
    for extra in extras:
        roots.add(_resolved(extra))
    return roots


def targets_for_source(
    source: Path,
    stop_at: Path | None = None,
    wide: set[Path] | None = None,
) -> list[WatchTarget]:
    stop = _resolved(stop_at) if stop_at is not None else None
    wide_roots = wide if wide is not None else wide_watch_roots(stop)
    try:
        if source.is_dir():
            return [WatchTarget(source, None)]
        if source.is_file():
            return [WatchTarget(source.parent, None)]
    except OSError:
        pass
    child = source
    current = source.parent
    while True:
        try:
            exists = current.is_dir()
        except OSError:
            exists = False
        if exists:
            key = _resolved(current)
            if current == source.parent and key not in wide_roots:
                return [WatchTarget(current, None)]
            return [WatchTarget(current, frozenset({child.name}))]
        if current == current.parent:
            return []
        if stop is not None and _resolved(current) == stop:
            return []
        child = current
        current = current.parent


def event_is_interesting(directory: Path | None, name: str, targets: list[WatchTarget]) -> bool:
    """True when an inotify/poll event should start the rescan debounce.

    Fully-watched dirs (``names is None``) keep ``gfn-*.desktop``,
    ``.gfn-write.*`` temp dirs, and events from ephemeral child watches.
    Name-filtered wide ancestors only accept the listed child names.
    """
    if name == "*":
        return True
    if directory is None:
        return True
    dir_key = _resolved(directory)
    for target in targets:
        key = _resolved(target.directory)
        if dir_key == key:
            if target.names is None or name in target.names:
                return True
            continue
        if target.names is None:
            if _is_relative_to(dir_key, key):
                return True
            continue
        if _is_relative_to(dir_key, key):
            rel = _relative_to(dir_key, key)
            if rel is not None and rel.parts and rel.parts[0] in target.names:
                return True
    return False


def source_is_watched(source: Path, targets: list[WatchTarget]) -> bool:
    """True when a scanner input is covered by ``targets``."""
    src = _resolved(source)
    for target in targets:
        key = _resolved(target.directory)
        if src == key:
            return True
        if target.names is None:
            if _is_relative_to(src, key):
                return True
            continue
        if src.parent == key and src.name in target.names:
            return True
        if _is_relative_to(src, key):
            rel = _relative_to(src, key)
            if rel is not None and rel.parts and rel.parts[0] in target.names:
                return True
    return False


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _relative_to(path: Path, parent: Path) -> Path | None:
    try:
        return path.relative_to(parent)
    except ValueError:
        return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    return _relative_to(path, parent) is not None


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        key = _resolved(path)
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
        self._watch_targets: list[WatchTarget] = []
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
            self._watch_targets = []

    def on_overlay_open(self) -> None:
        if library_is_stale(self._library_file, self._settings["stale_minutes"], self._wall()):
            self._on_rescan("open")

    def on_readable(self, fd: int) -> None:
        if self._watcher is None or fd != self._watcher.fd:
            return
        events = self._watcher.read()
        interesting = False
        retarget = False
        for directory, name in events:
            if event_is_interesting(directory, name, self._watch_targets):
                interesting = True
            if directory is not None and name:
                child = directory / name
                try:
                    if child.is_dir():
                        retarget = True
                except OSError:
                    pass
        if retarget:
            self._apply_targets()
        if interesting:
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
        self._watch_targets = []

    def _apply_targets(self) -> bool:
        if self._watcher is None:
            return False
        targets = collect_watch_targets(self.cfg)
        paths = [item.directory for item in targets]
        changed = [str(p) for p in paths] != [str(p) for p in self._watch_paths]
        self._watch_targets = targets
        self._watch_paths = paths
        try:
            self._watcher.set_paths(paths)
        except Exception:
            return changed
        return changed
