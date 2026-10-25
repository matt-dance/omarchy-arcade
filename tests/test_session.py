"""Session tracking: evidence-based running/exited/lost transitions."""

from __future__ import annotations

import time
import unittest
from unittest import mock

from arcade import session as session_mod
from arcade.model import Game, LaunchSpec, TrackSpec
from arcade.session import Probe, Session, SessionTracker


class FakeProc:
    def __init__(self, code=None):
        self.code = code
        self.pid = 4242

    def poll(self):
        return self.code


class FakeProbe(Probe):
    def __init__(self):
        self.windows: list[dict] | None = []
        self.reapers: dict[int, list[int]] = {}
        self.alive: set[int] = set()
        self.units: set[str] = set()
        self.children: dict[int, list[int]] = {}
        self.calls = 0
        self.closed: list[str] = []
        self.killed: list[int] = []

    def clients(self):
        self.calls += 1
        return None if self.windows is None else list(self.windows)

    def steam_game_pids(self, app_id):
        return list(self.reapers.get(int(app_id), []))

    def descendants(self, pids):
        out = []
        for pid in pids:
            out.extend(self.children.get(pid, []))
        return out

    def pid_alive(self, pid):
        return pid in self.alive

    def unit_active(self, unit):
        return unit in self.units

    def close_window(self, address):
        self.closed.append(address)

    def kill_unit(self, unit, sig):
        pass

    def kill_pid(self, pid, sig):
        self.killed.append(pid)


def _tracker(probe, *, handoff=True, window_class=None, steam_app_id=None, proc_code=0, age=0.0, baseline=()):
    tracker = SessionTracker(probe=probe)
    tracker.current = Session(
        game_id="g",
        unit="arcade-g-1",
        argv=["xdg-open", "x"],
        started_at=time.time() - age,
        steam_app_id=steam_app_id,
        window_class=window_class,
        handoff=handoff,
        baseline=set(baseline),
    )
    tracker._proc = FakeProc(proc_code)
    return tracker


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        self.t += session_mod.POLL_INTERVAL + 0.01
        return self.t


class TestHandoff(unittest.TestCase):
    def test_steam_window_then_close(self):
        probe = FakeProbe()
        tick = Clock()
        tracker = _tracker(probe, window_class="steam_app_570", steam_app_id=570)
        # Launcher (xdg-open) exited 0 at once: not an exit of the game.
        self.assertIsNone(tracker.poll(tick()))
        self.assertEqual(tracker.current.state, "starting")

        probe.windows = [{"address": "0xabc", "class": "steam_app_570", "pid": 77}]
        changed = tracker.poll(tick())
        self.assertIsNotNone(changed)
        self.assertEqual(changed.state, "running")
        self.assertEqual(changed.window_address, "0xabc")

        probe.windows = []
        self.assertIsNone(tracker.poll(tick()))  # one miss is tolerated
        changed = tracker.poll(tick())
        self.assertEqual(changed.state, "exited")
        self.assertEqual(changed.reason, "closed")

    def test_reaper_keeps_session_running_without_window(self):
        probe = FakeProbe()
        tick = Clock()
        tracker = _tracker(probe, steam_app_id=1245620)
        probe.reapers[1245620] = [99]
        self.assertEqual(tracker.poll(tick()).state, "running")
        for _ in range(5):
            self.assertIsNone(tracker.poll(tick()))
        probe.reapers.clear()
        tracker.poll(tick())
        self.assertEqual(tracker.poll(tick()).state, "exited")

    def test_no_evidence_becomes_lost_not_exited(self):
        probe = FakeProbe()
        tracker = _tracker(probe, age=session_mod.HANDOFF_START_TIMEOUT + 5)
        changed = tracker.poll(5000.0)
        self.assertEqual(changed.state, "lost")
        self.assertEqual(changed.seconds, 0)

    def test_handoff_waits_past_old_90s_limit(self):
        probe = FakeProbe()
        tracker = _tracker(probe, age=120)
        self.assertIsNone(tracker.poll(5000.0))
        self.assertEqual(tracker.current.state, "starting")

    def test_launcher_failure_is_reported(self):
        probe = FakeProbe()
        tracker = _tracker(probe, proc_code=4)
        changed = tracker.poll(5000.0)
        self.assertEqual(changed.state, "exited")
        self.assertEqual(changed.reason, "failed")
        self.assertEqual(changed.exit_code, 4)

    def test_startup_wm_class_matches_case_insensitively(self):
        probe = FakeProbe()
        probe.windows = [{"address": "0x1", "class": "Steam_App_Battlenet", "pid": 5}]
        tracker = _tracker(probe, window_class="steam_app_battlenet")
        self.assertEqual(tracker.poll(5000.0).state, "running")


class TestAdoption(unittest.TestCase):
    def test_adopts_new_non_launcher_window(self):
        probe = FakeProbe()
        tick = Clock()
        probe.windows = [{"address": "0xold", "class": "firefox", "pid": 1}]
        tracker = _tracker(probe, baseline={"0xold"})
        self.assertIsNone(tracker.poll(tick()))

        probe.windows.append({"address": "0xsteam", "class": "steam", "pid": 2})
        self.assertIsNone(tracker.poll(tick()))  # launcher windows are not the game

        probe.windows.append({"address": "0xgame", "class": "wow.exe", "pid": 3})
        changed = tracker.poll(tick())
        self.assertEqual(changed.state, "running")
        self.assertTrue(changed.adopted)
        self.assertEqual(changed.window_address, "0xgame")

        probe.windows = [w for w in probe.windows if w["address"] != "0xgame"]
        tracker.poll(tick())
        self.assertEqual(tracker.poll(tick()).state, "exited")

    def test_adopted_pid_counts_while_window_is_unmapped(self):
        probe = FakeProbe()
        tick = Clock()
        probe.windows = [{"address": "0xgame", "class": "game", "pid": 3}]
        tracker = _tracker(probe)
        tracker.poll(tick())
        probe.windows = []
        probe.alive.add(3)
        for _ in range(4):
            self.assertIsNone(tracker.poll(tick()))
        self.assertEqual(tracker.current.state, "running")


class TestDirect(unittest.TestCase):
    def test_direct_child_alive_counts(self):
        probe = FakeProbe()
        probe.windows = None  # no hyprctl
        tracker = _tracker(probe, handoff=False, proc_code=None)
        self.assertEqual(tracker.poll(5000.0).state, "running")

    def test_direct_scope_gone_without_window_fails(self):
        probe = FakeProbe()
        tracker = _tracker(probe, handoff=False, proc_code=0, age=session_mod.DIRECT_FAIL_GRACE + 1)
        changed = tracker.poll(5000.0)
        self.assertEqual(changed.state, "exited")
        self.assertEqual(changed.reason, "no-window")


class TestThrottle(unittest.TestCase):
    def test_polls_at_most_once_per_interval(self):
        probe = FakeProbe()
        tracker = _tracker(probe)
        tracker.poll(100.0)
        calls = probe.calls
        for i in range(20):
            tracker.poll(100.0 + i * 0.05)
        self.assertEqual(probe.calls, calls)
        tracker.poll(100.0 + session_mod.POLL_INTERVAL + 0.1)
        self.assertEqual(probe.calls, calls + 1)


class TestClose(unittest.TestCase):
    def test_close_targets_tracked_window(self):
        probe = FakeProbe()
        tracker = _tracker(probe)
        tracker.current.window_address = "0xgame"
        tracker.close(force=False)
        self.assertEqual(probe.closed, ["0xgame"])
        self.assertEqual(tracker.current.state, "starting")

    def test_force_kills_reaper_and_descendants(self):
        probe = FakeProbe()
        tracker = _tracker(probe, steam_app_id=570)
        probe.reapers[570] = [10]
        probe.children[10] = [11, 12]
        tracker.close(force=True)
        self.assertEqual(sorted(probe.killed), [10, 11, 12])
        self.assertEqual(tracker.current.state, "exited")
        self.assertEqual(tracker.current.reason, "force")


class TestLaunch(unittest.TestCase):
    def _launch(self, game, which=None):
        probe = FakeProbe()
        probe.windows = [{"address": "0xold", "class": "kitty"}]
        tracker = SessionTracker(probe=probe)
        with mock.patch.object(session_mod.subprocess, "Popen", return_value=FakeProc(None)), \
             mock.patch.object(session_mod.shutil, "which", side_effect=lambda n: which.get(n) if which else None):
            s = tracker.launch(game)
        return s

    def test_desktop_launch_is_handoff_and_snapshots_windows(self):
        game = Game(
            id="desktop:wow",
            title="World of Warcraft",
            source="desktop",
            launch=LaunchSpec(kind="desktop", value="/x/wow.desktop"),
            track=TrackSpec(window_class="steam_app_battlenet"),
        )
        s = self._launch(game, which={"gio": "/usr/bin/gio"})
        self.assertTrue(s.handoff)
        self.assertEqual(s.baseline, {"0xold"})
        self.assertEqual(s.window_class, "steam_app_battlenet")

    def test_argv_without_uwsm_is_direct(self):
        game = Game(
            id="retroarch:x",
            title="X",
            source="retroarch",
            launch=LaunchSpec(kind="argv", value=["retroarch", "rom"]),
        )
        self.assertFalse(self._launch(game).handoff)
        self.assertTrue(self._launch(game, which={"uwsm-app": "/usr/bin/uwsm-app"}).handoff)


class TestDaemonSessionEvents(unittest.TestCase):
    def test_unknown_game_resets_service_session(self):
        from arcade import daemon as daemon_mod

        sent: list[dict] = []
        with mock.patch.object(daemon_mod, "emit", side_effect=lambda obj, *a, **k: sent.append(obj)):
            d = daemon_mod.ArcadeDaemon(plugin_dir=None)
            d._load_library = lambda: None
            d._launch({"t": "launch", "game": "nope:1"})
        states = [m.get("state") for m in sent if m.get("t") == "session"]
        self.assertEqual(states, ["failed"])

    def test_session_payload_carries_reason_and_start(self):
        probe = FakeProbe()
        tracker = _tracker(probe, age=session_mod.HANDOFF_START_TIMEOUT + 1)
        payload = tracker.poll(9000.0).to_dict()
        self.assertEqual(payload["state"], "lost")
        self.assertEqual(payload["reason"], "timeout")
        self.assertIn("startedAt", payload)


if __name__ == "__main__":
    unittest.main()
