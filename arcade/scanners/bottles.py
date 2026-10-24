"""Bottles External_Programs scanner (YAML-ish bottle.yml)."""

from __future__ import annotations

import re
from pathlib import Path

from ..model import ArtSpec, Game, LaunchSpec, ScanError, TrackSpec, normalize_title
from ..paths import bottles_data_dirs


def _parse_simple_yaml_programs(text: str) -> list[dict[str, str]]:
    """Extract External_Programs entries without a YAML dependency.

    Bottles bottle.yml is YAML. We only need name + path under External_Programs.
    """
    # Find External_Programs: block
    m = re.search(r"(?m)^External_Programs:\s*$", text)
    if not m:
        # Sometimes it's a map on one level with quoted keys
        m = re.search(r"(?m)^External_Programs:\s*\{\s*$", text)
    if not m:
        # Inline empty
        if re.search(r"(?m)^External_Programs:\s*\{\s*\}\s*$", text):
            return []
        if re.search(r"(?m)^External_Programs:\s*$", text) is None:
            # Try to find nested programs another way — look for name:/path: pairs under programs
            pass

    programs: list[dict[str, str]] = []
    # Match program blocks: a UUID or id key, then indented name/path/folder
    # Pattern for:
    #   uuid:
    #     name: Foo
    #     path: C:\...
    block = text
    if m:
        block = text[m.end() :]
        # Stop at next top-level key (no indent)
        stop = re.search(r"(?m)^[A-Za-z_]", block)
        if stop:
            block = block[: stop.start()]

    current: dict[str, str] | None = None
    for line in block.splitlines():
        if re.match(r"^\s{2}[^\s].*:$", line) or re.match(r"^\s{2}[\"'].*[\"']:\s*$", line):
            if current and current.get("name"):
                programs.append(current)
            current = {}
            continue
        if current is None:
            continue
        km = re.match(r"^\s+(name|path|folder|icon):\s*(.+)$", line)
        if km:
            key, val = km.group(1), km.group(2).strip().strip("\"'")
            current[key] = val
    if current and current.get("name"):
        programs.append(current)
    return programs


def scan() -> tuple[list[Game], list[ScanError]]:
    dirs = bottles_data_dirs()
    if not dirs:
        return [], []
    games: list[Game] = []
    errors: list[ScanError] = []
    for data_dir in dirs:
        bottles_root = data_dir / "bottles"
        if not bottles_root.is_dir():
            continue
        for bottle_dir in bottles_root.iterdir():
            yml = bottle_dir / "bottle.yml"
            if not yml.is_file():
                continue
            bottle_name = bottle_dir.name
            try:
                text = yml.read_text(encoding="utf-8", errors="replace")
                programs = _parse_simple_yaml_programs(text)
            except Exception as exc:  # noqa: BLE001
                errors.append(ScanError(source="bottles", error=f"{yml}: {exc}"))
                continue
            for prog in programs:
                title = prog["name"]
                safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-").lower() or "program"
                games.append(
                    Game(
                        id=f"bottles:{bottle_name}:{safe}",
                        title=title,
                        source="bottles",
                        runner="proton",
                        launch=LaunchSpec(
                            kind="argv",
                            value=[
                                "bottles-cli",
                                "run",
                                "-b",
                                bottle_name,
                                "-p",
                                title,
                            ],
                        ),
                        track=TrackSpec(handoff=True),
                        art=ArtSpec(),
                        description=f"Bottle: {bottle_name}",
                        dedupe_keys=[
                            f"bottles:{bottle_name}:{safe}",
                            f"title:{normalize_title(title)}",
                        ],
                    )
                )
    return games, errors
