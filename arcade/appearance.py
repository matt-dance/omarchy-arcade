"""Normalize and persist [appearance] in arcade.toml.

The overlay reads these keys live (FileView + daemon config). Writes go only
to the user override file so defaults stay in the plugin checkout.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from .config import load_config, normalize_appearance
from .paths import user_config_path

ANIMATIONS = ("full", "reduced", "off")
KEYS = ("background_opacity", "blur", "dynamic_tint", "animations")

_SECTION_RE = re.compile(r"(?m)^\[([^\]]+)\]\s*$")

_HEADER = (
    "# User overrides for Omarchy Arcade. Merged over the plugin defaults.\n"
    "# Edit this file or use Arcade → Settings. Reloads live.\n"
)


def current_appearance(
    plugin_dir: Path | None = None,
    user_path: Path | None = None,
) -> dict[str, Any]:
    return dict(load_config(plugin_dir=plugin_dir, user_path=user_path).appearance)


def format_appearance_body(values: dict[str, Any]) -> str:
    data = normalize_appearance(values)
    blur = "true" if data["blur"] else "false"
    tint = "true" if data["dynamic_tint"] else "false"
    opacity = data["background_opacity"]
    opacity_s = f"{opacity:.2f}".rstrip("0").rstrip(".") if isinstance(opacity, float) else str(opacity)
    return (
        f"background_opacity = {opacity_s}\n"
        f"blur = {blur}\n"
        f"dynamic_tint = {tint}\n"
        f'animations = "{data["animations"]}"\n'
    )


def replace_table(text: str, name: str, body: str) -> str:
    """Replace or append a top-level TOML table, leaving other sections intact."""
    matches = list(_SECTION_RE.finditer(text))
    start = end = None
    for i, match in enumerate(matches):
        if match.group(1).strip() == name:
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            break
    block = f"[{name}]\n{body.rstrip()}\n"
    if start is None:
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        return prefix + block
    before = text[:start].rstrip()
    after = text[end:].lstrip("\n")
    mid = (before + "\n\n" if before else "") + block
    return mid + ("\n" + after if after else "")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=".arcade-toml-",
        suffix=".tmp",
        delete=False,
    ) as fh:
        fh.write(text)
        fh.flush()
        tmp = Path(fh.name)
    tmp.replace(path)


def set_appearance(
    updates: dict[str, Any],
    user_path: Path | None = None,
    plugin_dir: Path | None = None,
) -> dict[str, Any]:
    path = user_path or user_config_path()
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if not text.strip():
        text = _HEADER
    current = current_appearance(plugin_dir=plugin_dir, user_path=path if path.is_file() else Path("/nonexistent"))
    merged = normalize_appearance({**current, **updates})
    new_text = replace_table(text, "appearance", format_appearance_body(merged))
    _write_atomic(path, new_text)
    return merged


def parse_set_value(key: str, raw: str) -> Any:
    if key not in KEYS:
        raise ValueError(f"unknown appearance key {key!r}")
    value = str(raw).strip()
    if key == "background_opacity":
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"background_opacity must be a number, got {raw!r}") from exc
    if key == "animations":
        anim = value.lower()
        if anim not in ANIMATIONS:
            raise ValueError(f"animations must be one of {', '.join(ANIMATIONS)}")
        return anim
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be true or false, got {raw!r}")
