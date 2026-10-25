"""Controller navigation: hold-to-repeat, left stick, pad hotplug events."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from arcade import daemon as daemon_mod
from arcade.linux_input import ABS_X, ABS_Y, ABS_Z, DeviceInfo
from arcade.nav import NavRepeater, normalize_axis, stick_direction


class TestNavRepeater(unittest.TestCase):
    def test_press_then_repeat_after_delay(self):
        nav = NavRepeater(repeat_delay=0.4, repeat_interval=0.1)
        self.assertEqual(nav.press("dpad", "down", 0.0), "down")
        self.assertIsNone(nav.tick(0.39))
        self.assertEqual(nav.tick(0.40), "down")
        self.assertIsNone(nav.tick(0.45))
        self.assertEqual(nav.tick(0.50), "down")
        nav.release("dpad", 0.55)
        self.assertIsNone(nav.tick(10.0))
        self.assertIsNone(nav.next_deadline())

    def test_same_direction_does_not_refire(self):
        nav = NavRepeater()
        self.assertEqual(nav.press("stick:a", "left", 0.0), "left")
        self.assertIsNone(nav.press("stick:a", "left", 0.01))

    def test_latest_source_wins_and_falls_back(self):
        nav = NavRepeater(repeat_delay=0.4, repeat_interval=0.1)
        nav.press("dpad", "down", 0.0)
        self.assertEqual(nav.press("stick:a", "right", 0.1), "right")
        self.assertEqual(nav.tick(0.5), "right")
        nav.release("stick:a", 0.6)
        self.assertEqual(nav.tick(1.0), "down")

    def test_release_direction_ignores_other_direction(self):
        nav = NavRepeater()
        nav.press("dpad", "up", 0.0)
        nav.release_direction("dpad", "down", 0.1)
        self.assertEqual(nav.tick(1.0), "up")

    def test_configure_from_input_settings(self):
        nav = NavRepeater()
        nav.configure({"repeat_delay_ms": 250, "repeat_interval_ms": 60})
        self.assertAlmostEqual(nav.repeat_delay, 0.25)
        self.assertAlmostEqual(nav.repeat_interval, 0.06)


class TestStick(unittest.TestCase):
    def test_deadzone_and_dominant_axis(self):
        self.assertIsNone(stick_direction(0.2, -0.3, 0.35))
        self.assertEqual(stick_direction(0.9, 0.4, 0.35), "right")
        self.assertEqual(stick_direction(-0.5, 0.2, 0.35), "left")
        self.assertEqual(stick_direction(0.1, -0.8, 0.35), "up")
        self.assertEqual(stick_direction(0.1, 0.8, 0.35), "down")

    def test_normalize_axis(self):
        self.assertAlmostEqual(normalize_axis(0, -32768, 32767), 0.0, places=3)
        self.assertEqual(normalize_axis(32767, -32768, 32767), 1.0)
        self.assertEqual(normalize_axis(0, 0, 255), -1.0)
        self.assertEqual(normalize_axis(5, 5, 5), 0.0)


def _daemon():
    d = daemon_mod.ArcadeDaemon(plugin_dir=None)
    d.ui_mode = True
    return d


class TestDaemonNav(unittest.TestCase):
    def setUp(self):
        self.sent: list[dict] = []
        patcher = mock.patch.object(daemon_mod, "emit", side_effect=lambda obj, *a, **k: self.sent.append(obj))
        patcher.start()
        self.addCleanup(patcher.stop)

    def navs(self):
        return [(m["dir"], m["repeat"]) for m in self.sent if m.get("t") == "nav"]

    def test_held_dpad_repeats_until_release(self):
        d = _daemon()
        d._nav_or_button("DPAD_RIGHT", True, 0.0)
        for t in (0.2, 0.41, 0.53, 0.65):
            repeated = d.nav.tick(t)
            if repeated:
                d._emit_nav(repeated, True)
        d._nav_or_button("DPAD_RIGHT", False, 0.7)
        self.assertIsNone(d.nav.tick(5.0))
        self.assertEqual(self.navs(), [("right", False), ("right", True), ("right", True), ("right", True)])

    def test_no_nav_outside_ui_mode(self):
        d = _daemon()
        d.ui_mode = False
        d._nav_or_button("DPAD_DOWN", True, 0.0)
        self.assertEqual(self.navs(), [])

    def test_stick_navigates_with_device_range(self):
        d = _daemon()
        info = DeviceInfo(path="/dev/input/event9", name="Xbox", bustype=3, vendor=1, product=2, version=1)
        d._ranges[7] = {ABS_X: (-32768, 32767), ABS_Y: (-32768, 32767)}
        d._handle_stick(7, info, ABS_X, 30000, 0.0)
        d._handle_stick(7, info, ABS_X, 31000, 0.05)  # still right: no duplicate
        d._handle_stick(7, info, ABS_X, 0, 0.1)  # back to centre
        d._handle_stick(7, info, ABS_Y, -32000, 0.2)
        self.assertEqual(self.navs(), [("right", False), ("up", False)])

    def test_modifier_held_suppresses_nav(self):
        d = _daemon()
        d.engine.held.add("GUIDE")
        d._emit_nav("down", False)
        self.assertEqual(self.navs(), [])

    def test_trigger_threshold_uses_device_range(self):
        d = _daemon()
        info = DeviceInfo(path="/dev/input/event9", name="Xbox", bustype=3, vendor=1, product=2, version=1)
        d._ranges[7] = {ABS_Z: (0, 1023)}
        pressed: list[tuple[str, bool]] = []
        d._nav_or_button = lambda b, p, n: pressed.append((b, p))
        with mock.patch.object(daemon_mod, "read_events", return_value=[(3, ABS_Z, 200)]):
            d._handle_events(7, info)
        self.assertEqual(pressed, [])  # 200/1023 is a light touch on xpad
        with mock.patch.object(daemon_mod, "read_events", return_value=[(3, ABS_Z, 900)]):
            d._handle_events(7, info)
        self.assertEqual(pressed, [("LT", True)])


class TestPadHotplug(unittest.TestCase):
    def setUp(self):
        self.sent: list[dict] = []
        patcher = mock.patch.object(daemon_mod, "emit", side_effect=lambda obj, *a, **k: self.sent.append(obj))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _pad(self, name):
        path = os.path.join(self.tmp.name, name)
        open(path, "w").close()
        return DeviceInfo(path=path, name="Pad " + name, bustype=3, vendor=0x45E, product=0xB12, version=1)

    def test_pads_sent_only_on_change_and_auto_open_only_for_new_pads(self):
        d = daemon_mod.ArcadeDaemon(plugin_dir=None)
        d.cfg.raw.setdefault("input", {})["auto_open_on_connect"] = True
        first = self._pad("event1")
        with mock.patch.object(daemon_mod, "list_gamepads", return_value=[first]):
            d.refresh_devices()
            d.refresh_devices()
            d.refresh_devices()
        pads_msgs = [m for m in self.sent if m.get("t") == "pads"]
        toggles = [m for m in self.sent if m.get("name") == "arcade.toggle"]
        self.assertEqual(len(pads_msgs), 1)
        self.assertEqual(toggles, [])  # already connected at startup

        second = self._pad("event2")
        with mock.patch.object(daemon_mod, "list_gamepads", return_value=[first, second]):
            d.refresh_devices()
            d.refresh_devices()
        toggles = [m for m in self.sent if m.get("name") == "arcade.toggle"]
        self.assertEqual(len(toggles), 1)
        self.assertEqual(len([m for m in self.sent if m.get("t") == "pads"]), 2)
        for fd in list(d._fds):
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
