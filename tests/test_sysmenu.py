"""System menu capability probing, parsers, and hidden-if-missing items."""

from __future__ import annotations

import unittest

from arcade.sysmenu import (
    Host,
    apply_action,
    build_menu,
    parse_bluetoothctl_devices,
    parse_nmcli_wifi,
    parse_powerprofiles,
    parse_wpctl_sinks,
    parse_wpctl_volume,
    read_batteries,
)


class FakeHost(Host):
    def __init__(self, bins=None, outputs=None, files=None, dirs=None):
        self.bins = set(bins or [])
        self.outputs = outputs or {}
        self.files = files or {}
        self.dirs = dirs or {}
        self.calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return name if name in self.bins else None

    def run(self, argv: list[str], timeout: float = 3.0) -> tuple[int, str, str]:
        self.calls.append(list(argv))
        key = tuple(argv)
        if key in self.outputs:
            return self.outputs[key]
        for stored, result in self.outputs.items():
            if tuple(argv[: len(stored)]) == stored:
                return result
        return 0, "", ""

    def read(self, path: str) -> str | None:
        return self.files.get(path)

    def listdir(self, path: str) -> list[str]:
        return list(self.dirs.get(path, []))


def _ids(items):
    return [i["id"] for i in items if i.get("kind") != "header"]


def _sections(items):
    return [i["label"] for i in items if i.get("kind") == "header"]


class TestParsers(unittest.TestCase):
    def test_wpctl_volume(self):
        self.assertEqual(parse_wpctl_volume("Volume: 0.45"), (45, False))
        self.assertEqual(parse_wpctl_volume("Volume: 0.45 [MUTED]"), (45, True))

    def test_wpctl_sinks(self):
        text = """
Audio
 ├─ Sinks:
 │  *   48. Built-in Audio Analog Stereo [vol: 0.50]
 │      55. HDMI Output [vol: 0.80]
 ├─ Sources:
 │  *   49. Mic
"""
        sinks = parse_wpctl_sinks(text)
        self.assertEqual(len(sinks), 2)
        self.assertEqual(sinks[0]["id"], "48")
        self.assertTrue(sinks[0]["current"])
        self.assertEqual(sinks[1]["label"], "HDMI Output")

    def test_nmcli_wifi(self):
        nets = parse_nmcli_wifi("*:Home:80:WPA2\n:Cafe:40:WPA2\n:Home:10:WPA2\n")
        self.assertEqual([n["id"] for n in nets], ["Home", "Cafe"])
        self.assertTrue(nets[0]["current"])

    def test_bluetooth_devices(self):
        text = "Device AA:BB:CC:DD:EE:FF Xbox Wireless Controller\nDevice 11:22:33:44:55:66 WH-1000XM5\n"
        devices = parse_bluetoothctl_devices(text)
        self.assertEqual(devices[0]["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(devices[1]["name"], "WH-1000XM5")

    def test_powerprofiles(self):
        current, profiles = parse_powerprofiles(
            "* balanced\n  performance\n  power-saver\n"
        )
        self.assertEqual(current, "balanced")
        self.assertEqual(profiles, ["balanced", "performance", "power-saver"])


class TestBuildMenuHidesMissing(unittest.TestCase):
    def test_game_section_always_present(self):
        items = build_menu({"tools": {}}, "Elden Ring")
        self.assertIn("Game", _sections(items))
        self.assertEqual(_ids(items)[:4], ["resume", "close", "force", "arcade"])
        self.assertNotIn("Audio", _sections(items))
        self.assertNotIn("Wi-Fi", _sections(items))
        self.assertNotIn("Power", _sections(items))

    def test_volume_and_power_only_when_tooled(self):
        status = {
            "tools": {
                "volume": "wpctl",
                "mute": "wpctl",
                "sinks": "wpctl",
                "lock": "omarchy-system-lock",
                "suspend": "systemctl",
            },
            "audio": {
                "volume": 40,
                "muted": False,
                "sinks": [{"id": "1", "label": "Speakers", "current": True}],
            },
        }
        items = build_menu(status)
        self.assertIn("Audio", _sections(items))
        self.assertIn("volume", _ids(items))
        self.assertIn("mute", _ids(items))
        self.assertIn("output", _ids(items))
        self.assertIn("Power", _sections(items))
        self.assertIn("lock", _ids(items))
        self.assertIn("suspend", _ids(items))
        self.assertNotIn("reboot", _ids(items))
        lock = next(i for i in items if i["id"] == "lock")
        self.assertTrue(lock.get("confirm"))

    def test_bluetooth_device_rows(self):
        status = {
            "tools": {"bluetooth": "bluetoothctl", "bluetoothctl": "bluetoothctl"},
            "bluetooth": {
                "powered": True,
                "devices": [
                    {"mac": "AA:BB:CC:DD:EE:FF", "name": "Xbox", "connected": True}
                ],
                "discovered": [{"mac": "11:22:33:44:55:66", "name": "Headset"}],
            },
        }
        ids = _ids(build_menu(status))
        self.assertIn("bluetooth_power", ids)
        self.assertIn("bluetooth_disconnect", ids)
        self.assertIn("bluetooth_pair", ids)
        self.assertIn("bluetooth_scan", ids)


class TestActions(unittest.TestCase):
    def test_volume_nudge_prefers_omarchy(self):
        host = FakeHost(bins=["omarchy-audio-output-volume", "wpctl"])
        result = apply_action("volume_nudge", {"delta": 5}, host)
        self.assertTrue(result["ok"])
        self.assertEqual(host.calls[0], ["omarchy-audio-output-volume", "raise"])

    def test_volume_nudge_wpctl_fallback(self):
        host = FakeHost(bins=["wpctl"])
        result = apply_action("volume_nudge", {"delta": -5}, host)
        self.assertTrue(result["ok"])
        self.assertEqual(host.calls[0][:3], ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@"])

    def test_missing_tool_fails(self):
        host = FakeHost(bins=[])
        result = apply_action("screenshot", {}, host)
        self.assertFalse(result["ok"])

    def test_lock_uses_omarchy(self):
        host = FakeHost(bins=["omarchy-system-lock"])
        self.assertTrue(apply_action("lock", {}, host)["ok"])
        self.assertEqual(host.calls[0], ["omarchy-system-lock"])

    def test_wifi_connect_nmcli(self):
        host = FakeHost(
            bins=["nmcli"],
            outputs={("nmcli", "connection", "up", "Home"): (0, "", "")},
        )
        result = apply_action("wifi_connect", {"ssid": "Home"}, host)
        self.assertTrue(result["ok"])


class TestBatteries(unittest.TestCase):
    def test_system_and_controller(self):
        host = FakeHost(
            files={
                "/sys/class/power_supply/BAT0/type": "Battery",
                "/sys/class/power_supply/BAT0/capacity": "82",
                "/sys/class/power_supply/BAT0/status": "Charging",
                "/sys/class/power_supply/BAT0/model_name": "Built-in",
                "/sys/class/power_supply/sony_controller_battery_aa/type": "Battery",
                "/sys/class/power_supply/sony_controller_battery_aa/capacity": "54",
                "/sys/class/power_supply/sony_controller_battery_aa/status": "Discharging",
                "/sys/class/power_supply/sony_controller_battery_aa/model_name": "DualSense",
            },
            dirs={
                "/sys/class/power_supply": [
                    "BAT0",
                    "sony_controller_battery_aa",
                    "AC",
                ]
            },
        )
        # AC has no type battery in files → skipped
        host.files["/sys/class/power_supply/AC/type"] = "Mains"
        bats = read_batteries(host)
        self.assertEqual(bats["system"]["percent"], 82)
        self.assertTrue(bats["system"]["charging"])
        self.assertEqual(len(bats["controllers"]), 1)
        self.assertEqual(bats["controllers"][0]["percent"], 54)


class TestQmlContracts(unittest.TestCase):
    def test_quick_menu_is_sectioned_and_confirmable(self):
        from pathlib import Path

        qml = (Path(__file__).resolve().parent.parent / "QuickMenu.qml").read_text(
            encoding="utf-8"
        )
        arcade = (Path(__file__).resolve().parent.parent / "Arcade.qml").read_text(
            encoding="utf-8"
        )
        self.assertIn("arcade-sys", qml)
        self.assertIn('view: "menu"', qml)
        self.assertIn('root.view = "confirm"', qml)
        self.assertIn("A confirm", qml)
        self.assertIn("bluetooth_scan", qml)
        self.assertIn("homeRow", arcade)
        self.assertIn("focusZone", arcade)
        self.assertIn("detailButton", arcade)
        self.assertIn("Play", arcade)
        self.assertIn("Options", arcade)
        self.assertIn("showQuickMenu", arcade)
        self.assertIn("menuPinned", arcade)
        self.assertIn("surface", arcade)


if __name__ == "__main__":
    unittest.main()
