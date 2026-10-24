"""itch.io butler.db scanner."""

from __future__ import annotations

import sqlite3

from ..model import ArtSpec, Game, LaunchSpec, ScanError, TrackSpec, normalize_title
from ..paths import itch_db_paths


def scan() -> tuple[list[Game], list[ScanError]]:
    paths = itch_db_paths()
    if not paths:
        return [], []
    games: list[Game] = []
    errors: list[ScanError] = []
    for db in paths:
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        except Exception as exc:  # noqa: BLE001
            errors.append(ScanError(source="itch", error=f"{db}: {exc}"))
            continue
        try:
            try:
                rows = conn.execute(
                    """
                    SELECT caves.id AS cave_id, games.title AS title,
                           games.cover_url AS cover_url, games.id AS game_id
                    FROM caves
                    JOIN games ON games.id = caves.game_id
                    """
                ).fetchall()
            except sqlite3.Error:
                rows = conn.execute(
                    """
                    SELECT id AS cave_id, title, cover_url, id AS game_id
                    FROM caves
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            errors.append(ScanError(source="itch", error=f"{db}: {exc}"))
            conn.close()
            continue
        conn.close()
        for row in rows:
            cave_id = row["cave_id"]
            title = row["title"] or f"itch {cave_id}"
            cover = row["cover_url"] if "cover_url" in row.keys() else None
            games.append(
                Game(
                    id=f"itch:{cave_id}",
                    title=str(title),
                    source="itch",
                    store="itch",
                    runner="native",
                    launch=LaunchSpec(
                        kind="uri",
                        value=f"itch://caves/{cave_id}/launch",
                    ),
                    track=TrackSpec(handoff=True),
                    art=ArtSpec(cover=cover if cover else None),
                    dedupe_keys=[f"itch:{cave_id}", f"title:{normalize_title(str(title))}"],
                )
            )
    return games, errors
