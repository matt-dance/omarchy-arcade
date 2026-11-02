"""Filesystem watchers for Arcade library auto-refresh.

Prefers inotify:

1. ``watchdog`` if installed
2. ``pyinotify`` if installed
3. ctypes ``inotify`` (Linux, no extra deps)
4. cheap mtime / directory-listing poll (stdlib)

The poll backend is also used to re-probe well-known source paths that did
not exist when the daemon started (a new Steam library, a first-run Heroic
config dir, …).
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import Any, Iterable


# Linux inotify event bits we care about. Defined here so tests and the
# ctypes backend share one source of truth even when libc is missing.
IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_NONBLOCK = 0x00000800
IN_CLOEXEC = 0x00080000
IN_WATCH_MASK = (
    IN_MODIFY
    | IN_ATTRIB
    | IN_CLOSE_WRITE
    | IN_MOVED_FROM
    | IN_MOVED_TO
    | IN_CREATE
    | IN_DELETE
    | IN_DELETE_SELF
    | IN_MOVE_SELF
)

_EVENT_FMT = "iIII"  # wd, mask, cookie, len
_EVENT_SIZE = struct.calcsize(_EVENT_FMT)


class Debouncer:
    """Coalesce bursts of events (Steam rewrites manifests during a download)."""

    def __init__(self, delay_s: float = 4.0):
        self.delay_s = max(0.0, float(delay_s))
        self._due: float | None = None

    def poke(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._due = now + self.delay_s

    def ready(self, now: float | None = None) -> bool:
        if self._due is None:
            return False
        now = time.monotonic() if now is None else now
        return now >= self._due

    def next_deadline(self) -> float | None:
        return self._due

    def clear(self) -> None:
        self._due = None

    def pending(self) -> bool:
        return self._due is not None


def watch_dir_for(path: Path) -> Path | None:
    """Directory an inotify/poll watch should sit on for ``path``.

    Files are watched via their parent. Missing files still watch a parent
    that exists so a later create is visible.
    """
    try:
        if path.is_dir():
            return path
        if path.is_file():
            return path.parent
    except OSError:
        return None
    parent = path.parent
    try:
        if parent.is_dir():
            return parent
    except OSError:
        return None
    return None


class FileWatcher:
    """Common surface: a select-able fd (or none) plus optional poll()."""

    backend: str = "none"
    fd: int | None = None

    def set_paths(self, paths: Iterable[Path]) -> bool:
        """Replace the watched set. Returns True if the set changed."""
        raise NotImplementedError

    def read(self) -> list[tuple[Path | None, str]]:
        return []

    def poll(self) -> bool:
        return False

    def close(self) -> None:
        return None


class PollWatcher(FileWatcher):
    """Stat / listdir snapshot. Cheap; intended for a ~30 s interval."""

    backend = "poll"

    def __init__(self) -> None:
        self._dirs: list[Path] = []
        self._snap: dict[str, tuple[int, int]] = {}

    def set_paths(self, paths: Iterable[Path]) -> bool:
        dirs: list[Path] = []
        seen: set[Path] = set()
        for raw in paths:
            directory = watch_dir_for(Path(raw))
            if directory is None:
                continue
            try:
                key = directory.resolve()
            except OSError:
                key = directory
            if key in seen:
                continue
            seen.add(key)
            dirs.append(directory)
        changed = {str(p) for p in dirs} != {str(p) for p in self._dirs}
        self._dirs = dirs
        self._snap = self._snapshot()
        return changed

    def _snapshot(self) -> dict[str, tuple[int, int]]:
        snap: dict[str, tuple[int, int]] = {}
        for directory in self._dirs:
            key = str(directory)
            try:
                entries: list[tuple[str, int, int]] = []
                with os.scandir(directory) as it:
                    for entry in it:
                        try:
                            st = entry.stat(follow_symlinks=False)
                            entries.append((entry.name, st.st_mtime_ns, st.st_size))
                        except OSError:
                            entries.append((entry.name, 0, 0))
                entries.sort()
                # Stable identity for the listing; not persisted.
                snap[key] = (len(entries), hash(tuple(entries)))
            except OSError:
                snap[key] = (-1, 0)
        return snap

    def poll(self) -> bool:
        now = self._snapshot()
        if now != self._snap:
            self._snap = now
            return True
        return False


class InotifyWatcher(FileWatcher):
    """Non-blocking inotify via ctypes. One watch per directory, not recursive."""

    backend = "inotify"

    def __init__(self) -> None:
        import ctypes
        import ctypes.util

        libname = ctypes.util.find_library("c") or "libc.so.6"
        libc = ctypes.CDLL(libname, use_errno=True)
        init1 = libc.inotify_init1
        init1.argtypes = [ctypes.c_int]
        init1.restype = ctypes.c_int
        add_watch = libc.inotify_add_watch
        add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        add_watch.restype = ctypes.c_int
        rm_watch = libc.inotify_rm_watch
        rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        rm_watch.restype = ctypes.c_int
        fd = init1(IN_NONBLOCK | IN_CLOEXEC)
        if fd < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err) or "inotify_init1")
        self.fd = fd
        self._libc = libc
        self._add_watch = add_watch
        self._rm_watch = rm_watch
        self._wd_to_path: dict[int, Path] = {}
        self._path_to_wd: dict[Path, int] = {}

    def set_paths(self, paths: Iterable[Path]) -> bool:
        wanted: dict[Path, Path] = {}
        for raw in paths:
            directory = watch_dir_for(Path(raw))
            if directory is None:
                continue
            try:
                key = directory.resolve()
            except OSError:
                key = directory
            wanted[key] = directory
        current = set(self._path_to_wd)
        changed = current != set(wanted)
        for key in current - set(wanted):
            wd = self._path_to_wd.pop(key, None)
            if wd is None:
                continue
            self._wd_to_path.pop(wd, None)
            try:
                self._rm_watch(self.fd, wd)
            except OSError:
                pass
        for key, directory in wanted.items():
            if key in self._path_to_wd:
                continue
            wd = self._add_watch(self.fd, os.fsencode(directory), IN_WATCH_MASK)
            if wd < 0:
                continue
            self._path_to_wd[key] = wd
            self._wd_to_path[wd] = directory
        return changed

    def read(self) -> list[tuple[Path | None, str]]:
        if self.fd is None:
            return []
        events: list[tuple[Path | None, str]] = []
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            if not data:
                break
            offset = 0
            while offset + _EVENT_SIZE <= len(data):
                wd, mask, _cookie, namelen = struct.unpack_from(_EVENT_FMT, data, offset)
                offset += _EVENT_SIZE
                name = ""
                if namelen:
                    raw = data[offset : offset + namelen]
                    offset += namelen
                    name = os.fsdecode(raw.split(b"\x00", 1)[0])
                if mask & IN_Q_OVERFLOW:
                    events.append((None, "*"))
                    continue
                path = self._wd_to_path.get(wd)
                if mask & IN_IGNORED:
                    if wd in self._wd_to_path:
                        gone = self._wd_to_path.pop(wd)
                        try:
                            self._path_to_wd.pop(gone.resolve(), None)
                        except OSError:
                            self._path_to_wd.pop(gone, None)
                    continue
                events.append((path, name))
        return events

    def close(self) -> None:
        if self.fd is None:
            return
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None
        self._wd_to_path.clear()
        self._path_to_wd.clear()


class _PipeWakeWatcher(FileWatcher):
    """Thread-backed backend (watchdog) that wakes select() via a pipe."""

    def __init__(self) -> None:
        self._r, self._w = os.pipe()
        os.set_blocking(self._r, False)
        os.set_blocking(self._w, False)
        try:
            os.set_inheritable(self._r, False)
            os.set_inheritable(self._w, False)
        except OSError:
            pass
        self.fd = self._r

    def _wake(self) -> None:
        try:
            os.write(self._w, b"\x00")
        except OSError:
            pass

    def read(self) -> list[tuple[Path | None, str]]:
        drained = False
        if self.fd is None:
            return []
        while True:
            try:
                chunk = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            drained = True
        return [(None, "*")] if drained else []

    def _close_pipe(self) -> None:
        for fd in (self._r, self._w):
            try:
                os.close(fd)
            except OSError:
                pass
        self.fd = None


class WatchdogWatcher(_PipeWakeWatcher):
    backend = "watchdog"

    def __init__(self) -> None:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        super().__init__()
        self._paths: set[str] = set()
        self._observer = Observer()
        parent = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, _event: Any) -> None:
                parent._wake()

        self._handler = _Handler()
        self._observer.start()

    def set_paths(self, paths: Iterable[Path]) -> bool:
        wanted: set[str] = set()
        for raw in paths:
            directory = watch_dir_for(Path(raw))
            if directory is None:
                continue
            wanted.add(str(directory))
        changed = wanted != self._paths
        if not changed:
            return False
        try:
            self._observer.unschedule_all()
        except Exception:
            pass
        self._paths = wanted
        for directory in wanted:
            try:
                self._observer.schedule(self._handler, directory, recursive=False)
            except Exception:
                continue
        return True

    def close(self) -> None:
        try:
            self._observer.stop()
            self._observer.join(timeout=1.0)
        except Exception:
            pass
        self._close_pipe()


class PyinotifyWatcher(FileWatcher):
    backend = "pyinotify"

    def __init__(self) -> None:
        import pyinotify

        self._pyinotify = pyinotify
        self._wm = pyinotify.WatchManager()
        self._notifier = pyinotify.Notifier(self._wm, timeout=0)
        self.fd = self._wm.get_fd()
        self._wds: dict[str, int] = {}
        self._mask = (
            pyinotify.IN_CREATE
            | pyinotify.IN_DELETE
            | pyinotify.IN_MODIFY
            | pyinotify.IN_MOVED_FROM
            | pyinotify.IN_MOVED_TO
            | pyinotify.IN_CLOSE_WRITE
            | pyinotify.IN_ATTRIB
            | pyinotify.IN_DELETE_SELF
            | pyinotify.IN_MOVE_SELF
        )

    def set_paths(self, paths: Iterable[Path]) -> bool:
        wanted: set[str] = set()
        for raw in paths:
            directory = watch_dir_for(Path(raw))
            if directory is None:
                continue
            wanted.add(str(directory))
        changed = wanted != set(self._wds)
        for gone in set(self._wds) - wanted:
            wd = self._wds.pop(gone)
            try:
                self._wm.rm_watch(wd)
            except Exception:
                pass
        for directory in wanted - set(self._wds):
            try:
                result = self._wm.add_watch(directory, self._mask, rec=False, auto_add=False)
            except Exception:
                continue
            if isinstance(result, dict):
                wd = next(iter(result.values()), None)
            else:
                wd = result
            if isinstance(wd, int) and wd >= 0:
                self._wds[directory] = wd
        return changed

    def read(self) -> list[tuple[Path | None, str]]:
        events: list[tuple[Path | None, str]] = []

        def _handle(event: Any) -> None:
            name = getattr(event, "name", "") or ""
            path = Path(event.path) if getattr(event, "path", None) else None
            events.append((path, str(name)))

        try:
            self._notifier.read_events()
            self._notifier.process_events()
        except Exception:
            if not events:
                return [(None, "*")]
        # pyinotify delivers via WatchManager's default notifier; if the
        # default processor ate events, treat any readable fd as a poke.
        if not events:
            try:
                self._notifier._default_proc_fun = _handle  # noqa: SLF001
            except Exception:
                return [(None, "*")]
        return events or [(None, "*")]

    def close(self) -> None:
        try:
            self._notifier.stop()
        except Exception:
            pass
        self.fd = None
        self._wds.clear()


def create_watcher() -> FileWatcher:
    """Best available watcher. Never raises; poll is the last resort."""
    for factory in (_try_watchdog, _try_pyinotify, _try_inotify):
        try:
            watcher = factory()
        except Exception:
            continue
        if watcher is not None:
            return watcher
    return PollWatcher()


def _try_watchdog() -> FileWatcher | None:
    try:
        import watchdog  # noqa: F401
    except ImportError:
        return None
    return WatchdogWatcher()


def _try_pyinotify() -> FileWatcher | None:
    try:
        import pyinotify  # noqa: F401
    except ImportError:
        return None
    return PyinotifyWatcher()


def _try_inotify() -> FileWatcher | None:
    if os.name != "posix":
        return None
    try:
        return InotifyWatcher()
    except OSError:
        return None
