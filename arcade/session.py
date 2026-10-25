"""Launch games in a systemd --user scope and track them until they exit.

Most launches hand off to another process: `xdg-open steam://…`, `gio launch
foo.desktop`, Heroic/Lutris URIs, GeForce NOW's `gfn-play.sh`. The process we
spawn exits within a second while the game keeps running elsewhere, so its
exit code says nothing. Instead the tracker polls for evidence that the game
is alive:

* a Hyprland client whose class matches the game (`steam_app_<id>`,
  `StartupWMClass`, `GeForceNOW`),
* Steam's `reaper SteamLaunch AppId=<id>` process,
* the launch scope / direct child, for launches that run the game in place,
* as a last resort, a window that appeared after launch and is not a launcher.

States: starting -> running -> exited. A launch that never shows evidence
becomes `lost`: Arcade stops tracking it quietly instead of claiming the game
ended and re-summoning itself over it.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from .model import Game

POLL_INTERVAL = 1.5
# Consecutive polls without evidence before a running game counts as exited.
MISSING_POLLS_TO_EXIT = 2
# How long a launch may take to show a window / process.
START_TIMEOUT = 90.0
HANDOFF_START_TIMEOUT = 180.0
# A direct launch whose process and scope are gone with no window by then failed.
DIRECT_FAIL_GRACE = 8.0

# Windows that appear during a launch but are launchers, not the game.
LAUNCHER_CLASSES = {
    "steam",
    "steamwebhelper",
    "heroic",
    "com.heroicgameslauncher.hgl",
    "lutris",
    "net.lutris.lutris",
    "bottles",
    "com.usebottles.bottles",
    "itch",
    "io.itch.itch",
    "legendary",
}


class Probe:
    """OS facade so the tracker can be tested without Hyprland or /proc."""

    def clients(self) -> list[dict[str, Any]] | None:
        """Hyprland clients, or None when hyprctl is unavailable."""
        if not shutil.which("hyprctl"):
            return None
        try:
            proc = subprocess.run(
                ["hyprctl", "-j", "clients"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        try:
            data = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, list) else None

    def steam_game_pids(self, app_id: int) -> list[int]:
        """Pids of Steam's `reaper SteamLaunch AppId=<id>` for this app."""
        needle = f"AppId={int(app_id)}".encode()
        pids: list[int] = []
        try:
            names = os.listdir("/proc")
        except OSError:
            return pids
        for name in names:
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/cmdline", "rb") as fh:
                    raw = fh.read(4096)
            except OSError:
                continue
            if b"SteamLaunch" not in raw:
                continue
            if needle in raw.split(b"\0"):
                pids.append(int(name))
        return pids

    def descendants(self, pids: list[int]) -> list[int]:
        """All children of `pids`, recursively (from /proc/*/stat ppid)."""
        children: dict[int, list[int]] = {}
        try:
            names = os.listdir("/proc")
        except OSError:
            return []
        for name in names:
            if not name.isdigit():
                continue
            try:
                with open(f"/proc/{name}/stat", "rb") as fh:
                    stat = fh.read().decode("utf-8", "replace")
            except OSError:
                continue
            # comm may contain spaces; ppid is the 2nd field after ')'.
            try:
                ppid = int(stat.rsplit(")", 1)[1].split()[1])
            except (IndexError, ValueError):
                continue
            children.setdefault(ppid, []).append(int(name))
        out: list[int] = []
        stack = list(pids)
        while stack:
            for child in children.get(stack.pop(), []):
                if child not in out:
                    out.append(child)
                    stack.append(child)
        return out

    def pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def unit_active(self, unit: str) -> bool:
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", "--quiet", unit],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def close_window(self, address: str) -> None:
        subprocess.run(
            ["hyprctl", "dispatch", "closewindow", f"address:{address}"],
            capture_output=True,
            timeout=2,
            check=False,
        )

    def kill_unit(self, unit: str, sig: str) -> None:
        subprocess.run(
            ["systemctl", "--user", "kill", "--kill-whom=all", f"-s{sig}", unit],
            capture_output=True,
            timeout=3,
            check=False,
        )

    def kill_pid(self, pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


@dataclass
class Session:
    game_id: str
    unit: str
    argv: list[str]
    started_at: float
    state: str = "starting"  # starting | running | exited | lost
    pid: int | None = None
    steam_app_id: int | None = None
    window_class: str | None = None
    handoff: bool = False
    exit_code: int | None = None
    running_at: float | None = None
    ended_at: float | None = None
    reason: str = ""
    baseline: set[str] = field(default_factory=set)
    window_address: str | None = None
    window_pid: int | None = None
    adopted: bool = False
    missing: int = 0

    @property
    def seconds(self) -> int:
        """Time actually spent running (0 if it never got there)."""
        if self.running_at is None:
            return 0
        end = self.ended_at if self.ended_at is not None else time.time()
        return max(0, int(end - self.running_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game_id,
            "state": self.state,
            "unit": self.unit,
            "pid": self.pid,
            "steamAppId": self.steam_app_id,
            "windowClass": self.window_class,
            "windowAddress": self.window_address,
            "startedAt": int(self.started_at),
            "seconds": self.seconds,
            "exitCode": self.exit_code,
            "reason": self.reason,
        }


def _class_matches(client: dict[str, Any], wanted: set[str]) -> bool:
    for key in ("class", "initialClass"):
        value = str(client.get(key) or "").casefold()
        if value and value in wanted:
            return True
    return False


def _is_launcher_window(client: dict[str, Any]) -> bool:
    for key in ("class", "initialClass"):
        value = str(client.get(key) or "").casefold()
        if value in LAUNCHER_CLASSES:
            return True
    return False


@dataclass
class SessionTracker:
    current: Session | None = None
    probe: Probe = field(default_factory=Probe)
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _last_poll: float = field(default=0.0, repr=False)

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
        kind = game.launch.kind if game.launch else ""
        # uri/desktop launchers return at once; the game lives elsewhere.
        handoff = bool(game.track.handoff) if game.track else False
        handoff = handoff or kind in ("uri", "desktop")
        # Prefer uwsm-app when present (Omarchy)
        if shutil.which("uwsm-app") and kind != "uri":
            # uwsm starts the app in its own unit, so our scope empties.
            handoff = True
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

        baseline = {
            str(c.get("address"))
            for c in (self.probe.clients() or [])
            if isinstance(c, dict) and c.get("address")
        }

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

        track = game.track
        session = Session(
            game_id=game.id,
            unit=unit,
            argv=argv,
            started_at=time.time(),
            pid=proc.pid,
            steam_app_id=game.steam_app_id or (track.steam_app_id if track else None),
            window_class=track.window_class if track else None,
            handoff=handoff,
            baseline=baseline,
        )
        self.current = session
        self._proc = proc
        self._last_poll = 0.0
        return session

    # -- evidence ---------------------------------------------------------

    def _wanted_classes(self, s: Session) -> set[str]:
        wanted: set[str] = set()
        if s.window_class:
            wanted.add(s.window_class.casefold())
        if s.steam_app_id:
            wanted.add(f"steam_app_{int(s.steam_app_id)}")
        return wanted

    def _direct_alive(self, s: Session) -> bool:
        """The spawned process or its scope still holds something."""
        if self._proc is not None and self._proc.poll() is None:
            return True
        if s.unit.startswith("arcade-"):
            return self.probe.unit_active(s.unit)
        return False

    def _evidence(self, s: Session, now: float) -> bool:
        clients = self.probe.clients()
        wanted = self._wanted_classes(s)
        if clients is not None:
            for client in clients:
                if not isinstance(client, dict):
                    continue
                if wanted and _class_matches(client, wanted):
                    s.window_address = str(client.get("address") or "") or s.window_address
                    pid = client.get("pid")
                    if isinstance(pid, int) and pid > 0:
                        s.window_pid = pid
                    return True
                if s.adopted and s.window_address and str(client.get("address")) == s.window_address:
                    return True

        if s.steam_app_id and self.probe.steam_game_pids(int(s.steam_app_id)):
            return True

        if s.adopted and s.window_pid and self.probe.pid_alive(s.window_pid):
            return True

        if not s.handoff and self._direct_alive(s):
            return True

        # Last resort while starting: adopt a new, non-launcher window.
        if s.state == "starting" and not s.adopted and clients is not None:
            for client in clients:
                if not isinstance(client, dict):
                    continue
                address = str(client.get("address") or "")
                if not address or address in s.baseline:
                    continue
                if _is_launcher_window(client):
                    continue
                if not str(client.get("class") or client.get("initialClass") or ""):
                    continue
                s.adopted = True
                s.window_address = address
                pid = client.get("pid")
                s.window_pid = pid if isinstance(pid, int) and pid > 0 else None
                return True
        return False

    # -- state machine ----------------------------------------------------

    def poll(self, now: float | None = None) -> Session | None:
        """Advance the session. Return it when its state changed, else None.

        Throttled to one probe every POLL_INTERVAL seconds so the daemon's
        50 ms select loop does not fork hyprctl/systemctl constantly.
        """
        s = self.current
        if not s or s.state in ("exited", "lost"):
            return None
        mono = time.monotonic() if now is None else now
        if self._last_poll and mono - self._last_poll < POLL_INTERVAL:
            return None
        self._last_poll = mono
        wall = time.time()
        alive = self._evidence(s, wall)
        elapsed = wall - s.started_at

        if s.state == "starting":
            if alive:
                s.state = "running"
                s.running_at = wall
                s.missing = 0
                return s
            code = self._proc.poll() if self._proc is not None else None
            if code not in (None, 0):
                # The launcher itself failed (bad .desktop, no URI handler, …).
                s.state = "exited"
                s.ended_at = wall
                s.reason = "failed"
                s.exit_code = code
                return s
            if not s.handoff and elapsed > DIRECT_FAIL_GRACE and not self._direct_alive(s):
                s.state = "exited"
                s.ended_at = wall
                s.reason = "no-window"
                if self._proc is not None:
                    s.exit_code = self._proc.poll()
                return s
            limit = HANDOFF_START_TIMEOUT if s.handoff else START_TIMEOUT
            if elapsed > limit:
                s.state = "lost"
                s.ended_at = wall
                s.reason = "timeout"
                return s
            return None

        # running
        if alive:
            s.missing = 0
            return None
        s.missing += 1
        if s.missing >= MISSING_POLLS_TO_EXIT:
            s.state = "exited"
            s.ended_at = wall
            s.reason = "closed"
            if self._proc is not None:
                s.exit_code = self._proc.poll()
            return s
        return None

    def mark_running(self) -> None:
        if self.current and self.current.state == "starting":
            self.current.state = "running"
            self.current.running_at = time.time()

    def close(self, force: bool = False) -> None:
        s = self.current
        if not s:
            return
        if not force and s.window_address:
            self.probe.close_window(s.window_address)
        if s.unit.startswith("arcade-"):
            self.probe.kill_unit(s.unit, "SIGKILL" if force else "SIGTERM")
        elif self._proc and self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass
        if force:
            pids: list[int] = []
            if s.window_pid:
                pids.append(s.window_pid)
            if s.steam_app_id:
                pids.extend(self.probe.steam_game_pids(int(s.steam_app_id)))
            pids.extend(self.probe.descendants(pids))
            for pid in dict.fromkeys(pids):
                self.probe.kill_pid(pid, signal.SIGKILL)
            s.state = "exited"
            s.ended_at = time.time()
            s.reason = "force"
            s.exit_code = -9

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
