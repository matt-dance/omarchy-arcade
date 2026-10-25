"""Per-user library state: favorites, hidden games, Arcade play history, sort.

Stored at ``$XDG_STATE_HOME/matt-dance.arcade/state.json``. The overlay reads
the file directly; every write goes through :func:`update` so the daemon
(play history) and ``bin/arcade-state`` (favorites, hide, sort) never clobber
each other.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator

from .paths import arcade_state_dir

VERSION = 1
SORTS = ("recent", "az", "played", "source")
# Launches that end this fast (crash, wrong store, no window) are not playtime.
MIN_SESSION_SECONDS = 10


def state_path() -> Path:
    return arcade_state_dir() / "state.json"


def empty_state() -> dict[str, Any]:
    return {"version": VERSION, "favorites": [], "hidden": [], "games": {}, "sort": SORTS[0]}


def _id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return out


def normalize(data: Any) -> dict[str, Any]:
    state = empty_state()
    if not isinstance(data, dict):
        return state
    state["favorites"] = _id_list(data.get("favorites"))
    state["hidden"] = _id_list(data.get("hidden"))
    games = data.get("games")
    if isinstance(games, dict):
        for game_id, entry in games.items():
            if not isinstance(game_id, str) or not isinstance(entry, dict):
                continue
            clean: dict[str, Any] = {}
            if isinstance(entry.get("lastPlayed"), str):
                clean["lastPlayed"] = entry["lastPlayed"]
            for key in ("seconds", "launches"):
                value = entry.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                    clean[key] = int(value)
            if clean:
                state["games"][game_id] = clean
    if data.get("sort") in SORTS:
        state["sort"] = data["sort"]
    return state


def load(path: Path | None = None) -> dict[str, Any]:
    path = path or state_path()
    try:
        return normalize(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return empty_state()


def _write_atomic(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def update(mutate: Callable[[dict[str, Any]], None], path: Path | None = None) -> dict[str, Any]:
    path = path or state_path()
    with _locked(path):
        state = load(path)
        mutate(state)
        state = normalize(state)
        _write_atomic(path, state)
    return state


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _set_member(items: list[str], game_id: str, on: bool | None) -> None:
    present = game_id in items
    want = (not present) if on is None else on
    if want and not present:
        items.append(game_id)
    elif not want and present:
        items.remove(game_id)


def set_favorite(game_id: str, on: bool | None = None, path: Path | None = None) -> dict[str, Any]:
    """Set favorite on/off; ``on=None`` toggles."""
    return update(lambda s: _set_member(s["favorites"], game_id, on), path)


def set_hidden(game_id: str, on: bool | None = None, path: Path | None = None) -> dict[str, Any]:
    return update(lambda s: _set_member(s["hidden"], game_id, on), path)


def set_sort(mode: str, path: Path | None = None) -> dict[str, Any]:
    if mode not in SORTS:
        raise ValueError(f"unknown sort {mode!r}; expected one of {', '.join(SORTS)}")

    def mutate(state: dict[str, Any]) -> None:
        state["sort"] = mode

    return update(mutate, path)


def record_launch(game_id: str, when: str | None = None, path: Path | None = None) -> dict[str, Any]:
    stamp = when or now_iso()

    def mutate(state: dict[str, Any]) -> None:
        entry = state["games"].setdefault(game_id, {})
        entry["lastPlayed"] = stamp
        entry["launches"] = int(entry.get("launches") or 0) + 1

    return update(mutate, path)


def record_session(game_id: str, seconds: int, path: Path | None = None) -> dict[str, Any] | None:
    """Add a finished session's playtime. Short sessions are ignored."""
    if seconds < MIN_SESSION_SECONDS:
        return None

    def mutate(state: dict[str, Any]) -> None:
        entry = state["games"].setdefault(game_id, {})
        entry["seconds"] = int(entry.get("seconds") or 0) + int(seconds)
        entry["lastPlayed"] = now_iso()

    return update(mutate, path)
