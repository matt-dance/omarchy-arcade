"""Lutris pga.db (SQLite) scanner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..model import ArtSpec, Game, LaunchSpec, ScanError, TrackSpec, normalize_title
from ..paths import lutris_data_dirs


def _cover(data_dir: Path, slug: str) -> str | None:
    for folder, name in (
        ("coverart", f"{slug}.jpg"),
        ("coverart", f"{slug}.png"),
        ("banners", f"{slug}.jpg"),
        ("banners", f"{slug}.png"),
    ):
        p = data_dir / folder / name
        if p.is_file():
            return p.as_uri()
    return None


def scan() -> tuple[list[Game], list[ScanError]]:
    dirs = lutris_data_dirs()
    if not dirs:
        return [], []
    games: list[Game] = []
    errors: list[ScanError] = []
    for data_dir in dirs:
        db = data_dir / "pga.db"
        if not db.is_file():
            continue
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT id, name, slug, runner, installed, directory "
                    "FROM games WHERE installed = 1"
                ).fetchall()
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(ScanError(source="lutris", error=f"{db}: {exc}"))
            continue
        for row in rows:
            gid = int(row["id"])
            title = row["name"] or row["slug"] or f"Lutris {gid}"
            slug = row["slug"] or str(gid)
            runner = row["runner"] or "unknown"
            runner_kind = "proton" if runner in ("wine", "proton", "umu") else "native"
            if runner == "steam":
                runner_kind = "proton"
            cover = _cover(data_dir, slug)
            games.append(
                Game(
                    id=f"lutris:{gid}",
                    title=str(title),
                    source="lutris",
                    store=None,
                    runner=runner_kind,
                    launch=LaunchSpec(kind="uri", value=f"lutris:rungameid/{gid}"),
                    track=TrackSpec(handoff=True),
                    art=ArtSpec(cover=cover),
                    description=f"Lutris runner: {runner}",
                    dedupe_keys=[f"lutris:{gid}", f"title:{normalize_title(str(title))}"],
                )
            )
    return games, errors
