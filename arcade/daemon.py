"""arcaded — long-lived input + session helper for Omarchy Arcade.

Speaks newline-delimited JSON on stdout. Reads newline-delimited JSON on stdin.
Exits when stdin closes (--exit-with-stdin).
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, TextIO

from .combos import ComboEngine
from .config import ArcadeConfig, Binding, load_config
from .linux_input import (
    ABS_HAT0X,
    ABS_HAT0Y,
    ABS_X,
    ABS_Y,
    ABS_Z,
    ABS_RZ,
    BUTTON_MAP,
    EV_ABS,
    EV_KEY,
    EV_SYN,
    SYN_DROPPED,
    DeviceInfo,
    VirtualKeyboard,
    inspect_device,
    list_gamepads,
    read_abs_range,
    read_events,
)
from .model import Game
from .nav import DPAD_DIRS, NavRepeater, normalize_axis, stick_direction
from .paths import default_config_path, library_path
from .session import SessionTracker


def emit(obj: dict[str, Any], out: TextIO = sys.stdout) -> None:
    out.write(json.dumps(obj, separators=(",", ":")) + "\n")
    out.flush()


class ArcadeDaemon:
    def __init__(self, plugin_dir: Path | None = None, exit_with_stdin: bool = True):
        self.plugin_dir = plugin_dir
        self.exit_with_stdin = exit_with_stdin
        self.cfg: ArcadeConfig = load_config(plugin_dir)
        self.engine = ComboEngine(self.cfg.bindings, self.cfg.input)
        self.tracker = SessionTracker()
        self.keyboard = VirtualKeyboard()
        self.ui_mode = False  # when True, emit nav/intents; always emit global actions
        self._fds: dict[int, DeviceInfo] = {}
        self._hat: dict[str, dict[str, int]] = {}  # path -> {x,y}
        self._running = True
        self._games_by_id: dict[str, Game] = {}
        self.nav = NavRepeater()
        self.nav.configure(self.cfg.input)
        self._ranges: dict[int, dict[int, tuple[int, int]]] = {}  # fd -> axis -> (min, max)
        self._stick: dict[str, dict[str, float]] = {}  # path -> {x, y} normalized
        self._pads_payload: list[dict] | None = None
        self._known_pads: set[str] | None = None  # None until the first device scan

    def reload(self) -> None:
        self.cfg = load_config(self.plugin_dir)
        self.engine.set_bindings(self.cfg.bindings, self.cfg.input)
        self.engine.reset()
        self.nav.configure(self.cfg.input)
        self.nav.reset()
        emit({"t": "config", "ok": not self.cfg.errors, "errors": self.cfg.errors})

    def refresh_devices(self) -> None:
        ignore = self.cfg.input.get("ignore_steam_virtual_pad", "auto")
        pads = list_gamepads()
        physical = [p for p in pads if not p.is_steam_virtual]
        if ignore == "auto" and physical:
            pads = physical
        elif ignore is True or ignore == "always":
            pads = physical

        wanted = {p.path: p for p in pads}
        # Close removed
        for fd, info in list(self._fds.items()):
            if info.path not in wanted:
                try:
                    os.close(fd)
                except OSError:
                    pass
                del self._fds[fd]
                self._ranges.pop(fd, None)
                self._hat.pop(info.path, None)
                self._stick.pop(info.path, None)
                self.nav.release(f"stick:{info.path}", time.monotonic())
        # Open new
        open_paths = {i.path for i in self._fds.values()}
        for path, info in wanted.items():
            if path in open_paths:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self._fds[fd] = info
            self._hat[path] = {"x": 0, "y": 0}
            ranges: dict[int, tuple[int, int]] = {}
            for axis in (ABS_X, ABS_Y, ABS_Z, ABS_RZ):
                rng = read_abs_range(fd, axis)
                if rng:
                    ranges[axis] = rng
            self._ranges[fd] = ranges

        payload = [i.to_dict() for i in self._fds.values()]
        if payload != self._pads_payload:
            self._pads_payload = payload
            emit({"t": "pads", "pads": payload})

        # Auto-open only when a pad is newly connected, not on every scan
        # and not for pads that were already there when arcaded started.
        current = {i.path for i in self._fds.values()}
        added = current - self._known_pads if self._known_pads is not None else set()
        self._known_pads = current
        if self.cfg.input.get("auto_open_on_connect") and added:
            emit({"t": "action", "name": "arcade.toggle", "reason": "connect"})

    def _handle_activation(self, binding: Binding, reason: str) -> None:
        if binding.exec:
            subprocess.Popen(
                binding.exec,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            emit({"t": "action", "name": "exec", "exec": binding.exec, "reason": reason})
            return
        if binding.keys:
            try:
                self.keyboard.tap_combo(binding.keys)
                emit({"t": "action", "name": "keys", "keys": binding.keys, "reason": reason})
            except Exception as exc:  # noqa: BLE001
                emit({"t": "error", "error": f"keys: {exc}"})
            return
        if binding.action:
            emit({"t": "action", "name": binding.action, "reason": reason})

    def _modifier_held(self) -> bool:
        return self.cfg.input.get("modifier", "GUIDE") in self.engine.held

    def _emit_nav(self, direction: str, repeat: bool) -> None:
        if self.ui_mode and not self._modifier_held():
            emit({"t": "nav", "dir": direction, "repeat": repeat})

    def _nav_or_button(self, button: str, pressed: bool, now: float) -> None:
        if not pressed:
            if button in DPAD_DIRS:
                self.nav.release_direction("dpad", DPAD_DIRS[button], now)
            for act in self.engine.on_release(button, now):
                self._handle_activation(act.binding, act.reason)
            return

        # In UI mode, bare navigation buttons become intents (unless part of a chord with modifier)
        intent_map = {
            "A": "accept",
            "B": "back",
            "X": "options",
            "Y": "search",
            "LB": "tab_prev",
            "RB": "tab_next",
            "LT": "page_up",
            "RT": "page_down",
            "SELECT": "sort",
            "START": "menu",
            "R3": "favorite",
        }

        # Always feed the engine so global chords work
        activations = self.engine.on_press(button, now)
        if activations:
            for act in activations:
                self._handle_activation(act.binding, act.reason)
            return

        # If modifier is held, don't emit nav for face buttons — wait for chord
        if self.cfg.input.get("modifier", "GUIDE") in self.engine.held:
            return

        if self.ui_mode:
            if button in DPAD_DIRS:
                direction = self.nav.press("dpad", DPAD_DIRS[button], now)
                if direction:
                    self._emit_nav(direction, False)
            elif button in intent_map:
                emit({"t": "intent", "name": intent_map[button]})

    def _handle_events(self, fd: int, info: DeviceInfo) -> None:
        now = time.monotonic()
        events = read_events(fd)
        for etype, code, value in events:
            if etype == EV_SYN and code == SYN_DROPPED:
                self.engine.reset()
                self.nav.reset()
                continue
            if etype == EV_KEY and code in BUTTON_MAP:
                button = BUTTON_MAP[code]
                if value == 2:
                    continue  # key repeat from kernel — we do our own
                self._nav_or_button(button, value == 1, now)
            elif etype == EV_ABS:
                if code in (ABS_HAT0X, ABS_HAT0Y):
                    hat = self._hat.setdefault(info.path, {"x": 0, "y": 0})
                    axis = "x" if code == ABS_HAT0X else "y"
                    prev = hat[axis]
                    # value -1/0/1
                    if value == prev:
                        continue
                    # release old
                    if prev != 0:
                        btn = _hat_button(axis, prev)
                        if btn:
                            self._nav_or_button(btn, False, now)
                    hat[axis] = value
                    if value != 0:
                        btn = _hat_button(axis, value)
                        if btn:
                            self._nav_or_button(btn, True, now)
                elif code in (ABS_X, ABS_Y):
                    self._handle_stick(fd, info, code, value, now)
                elif code in (ABS_Z, ABS_RZ):
                    # Analog triggers: press past 60 % of the device's range
                    # (xpad reports 0..1023, DualSense 0..255).
                    button = "LT" if code == ABS_Z else "RT"
                    rng = self._ranges.get(fd, {}).get(code)
                    threshold = rng[0] + 0.6 * (rng[1] - rng[0]) if rng else 150
                    pressed = value > threshold
                    held = button in self.engine.held
                    if pressed and not held:
                        self._nav_or_button(button, True, now)
                    elif not pressed and held:
                        self._nav_or_button(button, False, now)

    def _handle_stick(self, fd: int, info: DeviceInfo, code: int, value: int, now: float) -> None:
        rng = self._ranges.get(fd, {}).get(code)
        if not rng:
            return
        pos = self._stick.setdefault(info.path, {"x": 0.0, "y": 0.0})
        pos["x" if code == ABS_X else "y"] = normalize_axis(value, rng[0], rng[1])
        deadzone = float(self.cfg.input.get("stick_deadzone", 0.35))
        direction = stick_direction(pos["x"], pos["y"], deadzone)
        source = f"stick:{info.path}"
        if direction is None:
            self.nav.release(source, now)
            return
        if not self.ui_mode:
            return
        fired = self.nav.press(source, direction, now)
        if fired:
            self._emit_nav(fired, False)

    def _handle_stdin_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            emit({"t": "error", "error": "bad json"})
            return
        typ = msg.get("t")
        if typ == "mode":
            self.ui_mode = bool(msg.get("ui"))
            if not self.ui_mode:
                self.nav.reset()
            emit({"t": "mode", "ui": self.ui_mode})
        elif typ == "reload":
            self.reload()
            self.refresh_devices()
        elif typ == "launch":
            self._launch(msg)
        elif typ == "close":
            force = bool(msg.get("force"))
            self.tracker.close(force=force)
            if self.tracker.current:
                emit({"t": "session", **self.tracker.current.to_dict(), "state": self.tracker.current.state})
            if force:
                self.tracker.clear()
        elif typ == "ping":
            emit({"t": "pong"})
        elif typ == "keys":
            combo = str(msg.get("keys") or "")
            try:
                self.keyboard.tap_combo(combo)
                emit({"t": "action", "name": "keys", "keys": combo, "reason": "service"})
            except Exception as exc:  # noqa: BLE001
                emit({"t": "error", "error": f"keys: {exc}"})
        else:
            emit({"t": "error", "error": f"unknown type {typ!r}"})

    def _launch(self, msg: dict) -> None:
        game_id = msg.get("game")
        argv = msg.get("argv")
        track = msg.get("track") or {}
        # Prefer library lookup; allow inline argv
        game = self._games_by_id.get(game_id) if game_id else None
        if game is None and argv:
            game = Game(
                id=str(game_id or "inline"),
                title=str(game_id or "game"),
                source="desktop",
                launch=__import__("arcade.model", fromlist=["LaunchSpec"]).LaunchSpec(
                    kind="argv", value=list(argv)
                ),
                track=__import__("arcade.model", fromlist=["TrackSpec"]).TrackSpec(
                    window_class=track.get("windowClass"),
                    steam_app_id=track.get("steamAppId") or track.get("steam_appid"),
                    handoff=bool(track.get("handoff", False)),
                ),
            )
        if game is None:
            # Reload library once
            self._load_library()
            game = self._games_by_id.get(game_id)
        if game is None:
            emit({"t": "error", "error": f"unknown game {game_id!r}"})
            return
        try:
            session = self.tracker.launch(game)
            emit({"t": "session", **session.to_dict()})
        except Exception as exc:  # noqa: BLE001
            emit({"t": "error", "error": f"launch: {exc}"})

    def _load_library(self) -> None:
        path = library_path()
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        from .model import LaunchSpec, TrackSpec, art_from_dict

        self._games_by_id.clear()
        for g in data.get("games") or []:
            launch = None
            if g.get("launch"):
                launch = LaunchSpec(
                    kind=g["launch"]["kind"],
                    value=g["launch"]["value"],
                    cwd=g["launch"].get("cwd"),
                    env=g["launch"].get("env") or {},
                )
            track_d = g.get("track") or {}
            game = Game(
                id=g["id"],
                title=g["title"],
                source=g.get("source") or "desktop",
                store=g.get("store"),
                runner=g.get("runner") or "native",
                platform=g.get("platform"),
                installed=bool(g.get("installed", True)),
                launch=launch,
                track=TrackSpec(
                    window_class=track_d.get("windowClass"),
                    steam_app_id=track_d.get("steamAppId"),
                    handoff=bool(track_d.get("handoff")),
                ),
                art=art_from_dict(g.get("art") or {}),
                steam_app_id=g.get("steamAppId"),
                playtime_minutes=g.get("playtimeMinutes"),
                last_played=g.get("lastPlayed"),
                dedupe_keys=list(g.get("dedupeKeys") or []),
                also_on=list(g.get("alsoOn") or []),
            )
            self._games_by_id[game.id] = game

    def run(self) -> int:
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_running", False))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_running", False))

        emit({"t": "hello", "version": 1, "pid": os.getpid()})
        if self.cfg.errors:
            emit({"t": "config", "ok": False, "errors": self.cfg.errors})
        else:
            emit({"t": "config", "ok": True, "errors": []})
        self._load_library()
        self.refresh_devices()

        stdin_fd = sys.stdin.fileno()
        # Make stdin non-blocking
        os.set_blocking(stdin_fd, False)
        buf = ""
        last_device_scan = 0.0

        while self._running:
            now = time.monotonic()
            if now - last_device_scan > 2.0:
                self.refresh_devices()
                last_device_scan = now

            for act in self.engine.tick(now):
                self._handle_activation(act.binding, act.reason)

            repeated = self.nav.tick(now)
            if repeated:
                self._emit_nav(repeated, True)

            done = self.tracker.poll()
            if done and done.state == "exited":
                emit({"t": "session", **done.to_dict()})
                self.tracker.clear()

            deadlines = [d for d in (self.engine.next_deadline(), self.nav.next_deadline()) if d is not None]
            timeout = 0.05
            if deadlines:
                timeout = max(0.0, min(timeout, min(deadlines) - now))

            rlist = list(self._fds.keys()) + [stdin_fd]
            try:
                readable, _, _ = select.select(rlist, [], [], timeout)
            except InterruptedError:
                continue

            if stdin_fd in readable:
                try:
                    chunk = os.read(stdin_fd, 65536)
                except BlockingIOError:
                    chunk = b""
                if not chunk:
                    if self.exit_with_stdin:
                        self._running = False
                        break
                else:
                    buf += chunk.decode("utf-8", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._handle_stdin_line(line)

            for fd in readable:
                if fd == stdin_fd:
                    continue
                info = self._fds.get(fd)
                if info:
                    try:
                        self._handle_events(fd, info)
                    except OSError:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        self._fds.pop(fd, None)

        self.keyboard.close()
        for fd in list(self._fds):
            try:
                os.close(fd)
            except OSError:
                pass
        return 0


def _hat_button(axis: str, value: int) -> str | None:
    if axis == "x":
        if value < 0:
            return "DPAD_LEFT"
        if value > 0:
            return "DPAD_RIGHT"
    else:
        if value < 0:
            return "DPAD_UP"
        if value > 0:
            return "DPAD_DOWN"
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    exit_with_stdin = "--exit-with-stdin" in argv
    plugin_dir = None
    if "--plugin-dir" in argv:
        i = argv.index("--plugin-dir")
        plugin_dir = Path(argv[i + 1])
    else:
        # default: repo / install root
        plugin_dir = default_config_path().parent.parent
    print(
        f"matt-dance.arcade: arcaded starting pid={os.getpid()} plugin_dir={plugin_dir}",
        file=sys.stderr,
        flush=True,
    )
    return ArcadeDaemon(plugin_dir=plugin_dir, exit_with_stdin=exit_with_stdin).run()


if __name__ == "__main__":
    raise SystemExit(main())
