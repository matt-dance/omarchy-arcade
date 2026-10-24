"""Launch games in a systemd --user scope and track exit."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from .model import Game


@dataclass
class Session:
    game_id: str
    unit: str
    argv: list[str]
    started_at: float
    state: str = "starting"  # starting | running | exited
    pid: int | None = None
    steam_app_id: int | None = None
    window_class: str | None = None
    handoff: bool = False
    exit_code: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game_id,
            "state": self.state,
            "unit": self.unit,
            "pid": self.pid,
            "steamAppId": self.steam_app_id,
            "windowClass": self.window_class,
            "seconds": int(time.time() - self.started_at),
            "exitCode": self.exit_code,
        }


@dataclass
class SessionTracker:
    current: Session | None = None
    _proc: subprocess.Popen | None = field(default=None, repr=False)

    def launch(self, game: Game) -> Session:
        if self.current and self.current.state in ("starting", "running"):
            raise RuntimeError(f"already tracking {self.current.game_id}")

        argv = _launch_argv(game)
        slug = game.id.replace(":", "-").replace("/", "-")[:48]
        unit = f"arcade-{slug}-{int(time.time())}"
        env = os.environ.copy()
        if game.launch and game.launch.env:
            env.update(game.launch.env)

        cmd = [
            "systemd-run",
            "--user",
            "--scope",
            f"--unit={unit}",
            "--collect",
            "--same-dir",
            "--",
            *argv,
        ]
        # Prefer uwsm-app when present (Omarchy)
        if shutil.which("uwsm-app") and game.launch and game.launch.kind != "uri":
            cmd = [
                "systemd-run",
                "--user",
                "--scope",
                f"--unit={unit}",
                "--collect",
                "--",
                "uwsm-app",
                "--",
                *argv,
            ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
        except FileNotFoundError:
            # No systemd-run — fall back to plain Popen
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            unit = f"pid-{proc.pid}"

        session = Session(
            game_id=game.id,
            unit=unit,
            argv=argv,
            started_at=time.time(),
            pid=proc.pid,
            steam_app_id=game.steam_app_id or (game.track.steam_app_id if game.track else None),
            window_class=game.track.window_class if game.track else None,
            handoff=bool(game.track.handoff) if game.track else False,
        )
        self.current = session
        self._proc = proc
        return session

    def mark_running(self) -> None:
        if self.current and self.current.state == "starting":
            self.current.state = "running"

    def poll(self) -> Session | None:
        """Return the session if it just exited, else None."""
        if not self.current or self.current.state == "exited":
            return None
        # For handoff launchers, the systemd-run helper exits immediately —
        # exit is detected by the QML Hyprland watcher / reaper, not here.
        if self.current.handoff:
            if self.current.state == "starting" and time.time() - self.current.started_at > 90:
                self.current.state = "exited"
                self.current.exit_code = -1
                done = self.current
                return done
            return None
        if self._proc is not None:
            code = self._proc.poll()
            if code is not None:
                self.current.state = "exited"
                self.current.exit_code = code
                done = self.current
                return done
        # Also check scope
        if self.current.unit.startswith("arcade-"):
            r = subprocess.run(
                ["systemctl", "--user", "is-active", self.current.unit],
                capture_output=True,
                text=True,
            )
            if r.returncode != 0 and self.current.state == "running":
                self.current.state = "exited"
                self.current.exit_code = r.returncode
                return self.current
        return None

    def close(self, force: bool = False) -> None:
        if not self.current:
            return
        unit = self.current.unit
        if unit.startswith("arcade-"):
            sig = "SIGKILL" if force else "SIGTERM"
            subprocess.run(
                ["systemctl", "--user", "kill", f"--kill-whom=all", f"-s{sig}", unit],
                capture_output=True,
            )
        elif self._proc and self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass
        if force:
            self.current.state = "exited"
            self.current.exit_code = -9

    def clear(self) -> None:
        self.current = None
        self._proc = None


def _launch_argv(game: Game) -> list[str]:
    if not game.launch:
        raise ValueError(f"game {game.id} has no launch spec")
    kind = game.launch.kind
    value = game.launch.value
    if kind == "uri":
        return ["xdg-open", str(value)]
    if kind == "desktop":
        # gio launch handles Field codes / Flatpak
        if shutil.which("gio"):
            return ["gio", "launch", str(value)]
        return ["gtk-launch", Path_stem(str(value))]
    if kind == "argv":
        if isinstance(value, list):
            return [str(x) for x in value]
        return [str(value)]
    raise ValueError(f"unknown launch kind {kind}")


def Path_stem(desktop_path: str) -> str:
    return os.path.basename(desktop_path).removesuffix(".desktop")
