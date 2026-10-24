"""Opt-in ROM folder scanner for ~/Games/roms/<system>/."""

from __future__ import annotations

from pathlib import Path

from ..model import ArtSpec, Game, LaunchSpec, ScanError, TrackSpec, normalize_title
from ..paths import home

# Extension → (system folder name, preferred core path hint)
# Cores match Omarchy's libretro package naming where possible.
_EXTENSIONS: dict[str, str] = {
    ".nes": "nes",
    ".fds": "nes",
    ".smc": "snes",
    ".sfc": "snes",
    ".fig": "snes",
    ".n64": "n64",
    ".z64": "n64",
    ".v64": "n64",
    ".gb": "gb",
    ".gbc": "gbc",
    ".gba": "gba",
    ".nds": "nds",
    ".md": "megadrive",
    ".gen": "megadrive",
    ".sms": "mastersystem",
    ".gg": "gamegear",
    ".pce": "pcengine",
    ".cue": "psx",
    ".chd": "psx",
    ".iso": "psx",
    ".bin": "psx",
    ".gcm": "gc",
    ".ciso": "gc",
    ".wbfs": "wii",
    ".rvz": "wii",
    ".zip": "arcade",
    ".7z": "arcade",
}

_CORE_HINTS: dict[str, str] = {
    "nes": "mesen_libretro.so",
    "snes": "snes9x_libretro.so",
    "n64": "mupen64plus_next_libretro.so",
    "gb": "gambatte_libretro.so",
    "gbc": "gambatte_libretro.so",
    "gba": "mgba_libretro.so",
    "nds": "melonds_libretro.so",
    "megadrive": "genesis_plus_gx_libretro.so",
    "mastersystem": "genesis_plus_gx_libretro.so",
    "gamegear": "genesis_plus_gx_libretro.so",
    "pcengine": "mednafen_pce_libretro.so",
    "psx": "pcsx_rearmed_libretro.so",
    "gc": "dolphin_libretro.so",
    "wii": "dolphin_libretro.so",
    "arcade": "mame_libretro.so",
}


def _rom_root() -> Path:
    return home() / "Games" / "roms"


def _find_core(name: str) -> str | None:
    candidates = [
        Path("/usr/lib/libretro") / name,
        Path("/usr/lib64/libretro") / name,
        home() / ".config" / "retroarch" / "cores" / name,
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def scan() -> tuple[list[Game], list[ScanError]]:
    root = _rom_root()
    if not root.is_dir():
        return [], []
    games: list[Game] = []
    errors: list[ScanError] = []
    try:
        systems = [p for p in root.iterdir() if p.is_dir()]
    except OSError as exc:
        return [], [ScanError(source="roms", error=str(exc))]

    for system_dir in systems:
        system = system_dir.name
        try:
            files = [p for p in system_dir.rglob("*") if p.is_file()]
        except OSError as exc:
            errors.append(ScanError(source="roms", error=f"{system_dir}: {exc}"))
            continue
        for rom in files:
            ext = rom.suffix.lower()
            # Prefer folder name as system; fall back to extension map
            platform = system if system != "roms" else _EXTENSIONS.get(ext)
            if platform is None and ext not in _EXTENSIONS:
                continue
            if platform is None:
                platform = _EXTENSIONS[ext]
            # Skip cue companions that are not the main file when .bin/.img sit beside .cue
            if ext in (".bin", ".img") and rom.with_suffix(".cue").is_file():
                continue
            core_name = _CORE_HINTS.get(platform)
            core = _find_core(core_name) if core_name else None
            argv = ["retroarch"]
            if core:
                argv.extend(["-L", core])
            argv.append(str(rom))
            title = rom.stem
            safe = normalize_title(title) or rom.name
            games.append(
                Game(
                    id=f"roms:{platform}:{safe}",
                    title=title,
                    source="roms",
                    runner="emulator",
                    platform=platform,
                    launch=LaunchSpec(kind="argv", value=argv),
                    track=TrackSpec(window_class="com.libretro.RetroArch"),
                    art=ArtSpec(),
                    dedupe_keys=[
                        f"roms:{platform}:{safe}",
                        f"retroarch:{platform}:{safe}",
                        f"title:{safe}",
                    ],
                )
            )
    return games, errors
