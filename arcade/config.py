"""Load and merge arcade.toml defaults + user overrides."""

from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import default_config_path, user_config_path


BUTTON_ALIASES = {
    "A": "A",
    "B": "B",
    "X": "X",
    "Y": "Y",
    "SOUTH": "A",
    "EAST": "B",
    "WEST": "X",
    "NORTH": "Y",
    "CROSS": "A",
    "CIRCLE": "B",
    "SQUARE": "X",
    "TRIANGLE": "Y",
    "LB": "LB",
    "RB": "RB",
    "L1": "LB",
    "R1": "RB",
    "LT": "LT",
    "RT": "RT",
    "L2": "LT",
    "R2": "RT",
    "LS": "LS",
    "RS": "RS",
    "L3": "L3",
    "R3": "R3",
    "START": "START",
    "SELECT": "SELECT",
    "BACK": "SELECT",
    "OPTIONS": "START",
    "SHARE": "SELECT",
    "GUIDE": "GUIDE",
    "HOME": "GUIDE",
    "PS": "GUIDE",
    "MODE": "GUIDE",
    "DPAD_UP": "DPAD_UP",
    "DPAD_DOWN": "DPAD_DOWN",
    "DPAD_LEFT": "DPAD_LEFT",
    "DPAD_RIGHT": "DPAD_RIGHT",
    "UP": "DPAD_UP",
    "DOWN": "DPAD_DOWN",
    "LEFT": "DPAD_LEFT",
    "RIGHT": "DPAD_RIGHT",
}

KNOWN_ACTIONS = {
    "arcade.toggle",
    "arcade.quick_menu",
    "arcade.cheat_sheet",
    "game.close",
    "game.focus",
    "game.force_quit",
}


@dataclass
class Binding:
    combo: tuple[str, ...]
    action: str | None = None
    exec: str | None = None
    keys: str | None = None
    description: str = ""
    hold: bool = False
    hold_ms: int | None = None
    repeat: bool = False
    tap: bool = False
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "combo": list(self.combo),
            "description": self.description,
            "hold": self.hold,
            "repeat": self.repeat,
            "tap": self.tap,
            "enabled": self.enabled,
        }
        if self.action:
            d["action"] = self.action
        if self.exec:
            d["exec"] = self.exec
        if self.keys:
            d["keys"] = self.keys
        if self.hold_ms is not None:
            d["hold_ms"] = self.hold_ms
        return d


@dataclass
class ArcadeConfig:
    raw: dict[str, Any] = field(default_factory=dict)
    bindings: list[Binding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def input(self) -> dict[str, Any]:
        return dict(self.raw.get("input") or {})

    @property
    def ui(self) -> dict[str, Any]:
        return dict(self.raw.get("ui") or {})

    @property
    def launch(self) -> dict[str, Any]:
        return dict(self.raw.get("launch") or {})

    @property
    def sources(self) -> dict[str, Any]:
        return dict(self.raw.get("sources") or {})

    @property
    def art(self) -> dict[str, Any]:
        return dict(self.raw.get("art") or {})

    def source_enabled(self, name: str) -> bool:
        return bool(self.sources.get(name, True))


def parse_combo(text: str) -> tuple[str, ...]:
    parts = [p.strip() for p in text.split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"empty button in combo {text!r}")
    buttons: list[str] = []
    for part in parts:
        key = part.upper().replace("-", "_").replace(" ", "_")
        if key not in BUTTON_ALIASES:
            raise ValueError(f"unknown button {part!r} in combo {text!r}")
        buttons.append(BUTTON_ALIASES[key])
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for b in buttons:
        if b in seen:
            continue
        seen.add(b)
        out.append(b)
    return tuple(out)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if key == "bindings" and isinstance(value, dict):
            # Binding tables merge per-key; false disables a default.
            merged = dict(result.get("bindings") or {})
            for bkey, bval in value.items():
                if bval is False:
                    merged.pop(bkey, None)
                else:
                    merged[bkey] = bval
            result["bindings"] = merged
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _parse_bindings(table: dict[str, Any], errors: list[str]) -> list[Binding]:
    bindings: list[Binding] = []
    for key, value in table.items():
        try:
            combo = parse_combo(key)
        except ValueError as exc:
            errors.append(f'bindings."{key}": {exc}')
            continue
        if value is False:
            continue
        if not isinstance(value, dict):
            errors.append(f'bindings."{key}": expected a table')
            continue
        if value.get("enabled") is False:
            continue
        action = value.get("action")
        exec_cmd = value.get("exec")
        keys = value.get("keys")
        n = sum(1 for x in (action, exec_cmd, keys) if x)
        if n != 1:
            errors.append(f'bindings."{key}": set exactly one of action, exec, keys')
            continue
        if action and action not in KNOWN_ACTIONS:
            errors.append(f'bindings."{key}": unknown action {action!r}')
            continue
        bindings.append(
            Binding(
                combo=combo,
                action=str(action) if action else None,
                exec=str(exec_cmd) if exec_cmd else None,
                keys=str(keys) if keys else None,
                description=str(value.get("description") or ""),
                hold=bool(value.get("hold", False)),
                hold_ms=int(value["hold_ms"]) if value.get("hold_ms") is not None else None,
                repeat=bool(value.get("repeat", False)),
                tap=bool(value.get("tap", False)),
                enabled=True,
            )
        )
    # Longer chords first helps the engine prefer them
    bindings.sort(key=lambda b: (-len(b.combo), "+".join(b.combo)))
    return bindings


def load_config(
    plugin_dir: Path | None = None,
    user_path: Path | None = None,
    defaults_path: Path | None = None,
) -> ArcadeConfig:
    defaults = _load_toml(defaults_path or default_config_path(plugin_dir))
    user = _load_toml(user_path or user_config_path())
    merged = _deep_merge(defaults, user) if defaults else copy.deepcopy(user)
    errors: list[str] = []
    bindings = _parse_bindings(merged.get("bindings") or {}, errors)
    return ArcadeConfig(raw=merged, bindings=bindings, errors=errors)


def config_to_public(cfg: ArcadeConfig) -> dict[str, Any]:
    return {
        "input": cfg.input,
        "ui": cfg.ui,
        "launch": cfg.launch,
        "sources": cfg.sources,
        "art": cfg.art,
        "bindings": [b.to_dict() for b in cfg.bindings],
        "errors": list(cfg.errors),
    }
