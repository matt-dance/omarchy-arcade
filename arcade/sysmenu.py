"""Steam Deck-style system menu: probe tools, report status, run actions.

Prefers Omarchy's own `omarchy-*` scripts. Missing tools are omitted from
the menu instead of showing dead items.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Quickshell Process often inherits a stripped PATH. Search these too.
_BIN_DIRS = (
    "/usr/bin",
    "/usr/local/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


def extra_bin_dirs() -> list[Path]:
    home = Path.home()
    dirs = [
        home / ".local" / "bin",
        home / ".local" / "share" / "omarchy" / "bin",
        Path("/usr/share/omarchy/bin"),
        Path("/usr/lib/omarchy/bin"),
    ]
    omarchy = os.environ.get("OMARCHY_PATH")
    if omarchy:
        dirs.insert(0, Path(omarchy) / "bin")
    return dirs


def ensure_search_path() -> str:
    """Prepend standard bin dirs so shutil.which works inside Quickshell."""
    current = [p for p in os.environ.get("PATH", "").split(":") if p]
    extra = [str(Path(p)) for p in _BIN_DIRS] + [str(p) for p in extra_bin_dirs()]
    merged: list[str] = []
    for part in extra + current:
        if part and part not in merged:
            merged.append(part)
    os.environ["PATH"] = ":".join(merged)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    os.environ.setdefault("XDG_RUNTIME_DIR", runtime)
    bus = Path(runtime) / "bus"
    if "DBUS_SESSION_BUS_ADDRESS" not in os.environ and bus.exists():
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"
    return os.environ["PATH"]


def resolve_bin(name: str, *, search_path: bool = True) -> str | None:
    """Find an executable by PATH and well-known absolute directories."""
    if not name:
        return None
    path = Path(name)
    if path.is_absolute():
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    if search_path:
        found = shutil.which(name)
        if found:
            return found
    for directory in list(_BIN_DIRS) + [str(p) for p in extra_bin_dirs()]:
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


class Host:
    """OS facade so status/actions can be tested without real devices."""

    def which(self, name: str) -> str | None:
        return resolve_bin(name)

    def run(self, argv: list[str], timeout: float = 1.2) -> tuple[int, str, str]:
        if not argv:
            return 127, "", "empty command"
        resolved = list(argv)
        found = self.which(resolved[0])
        if found:
            resolved[0] = found
        try:
            proc = subprocess.run(
                resolved,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except FileNotFoundError:
            return 127, "", "not found"
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        except OSError as exc:
            return 1, "", str(exc)

    def read(self, path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None

    def listdir(self, path: str) -> list[str]:
        p = Path(path)
        if not p.is_dir():
            return []
        try:
            return sorted(x.name for x in p.iterdir())
        except OSError:
            return []


def first_bin(host: Host, names: list[str]) -> str | None:
    for name in names:
        if host.which(name):
            return name
    return None


def log_tool(name: str, value: str | None) -> None:
    print(f"matt-dance.arcade: tool {name}={value or 'missing'}", file=sys.stderr, flush=True)


def parse_wpctl_volume(text: str) -> tuple[int | None, bool]:
    """Parse `wpctl get-volume` → (percent, muted)."""
    muted = "[MUTED]" in text.upper() or "MUTED" in text.upper()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None, muted
    try:
        value = float(match.group(1))
    except ValueError:
        return None, muted
    if value <= 1.5:
        value *= 100.0
    return int(round(max(0.0, min(150.0, value)))), muted


def parse_wpctl_sinks(text: str) -> list[dict[str, Any]]:
    """Parse default-marked sinks from `wpctl status`."""
    sinks: list[dict[str, Any]] = []
    in_sinks = False
    for raw in text.splitlines():
        line = raw.replace("│", " ").replace("├", " ").replace("└", " ")
        stripped = line.strip()
        if re.search(r"\bSinks:\s*$", stripped):
            in_sinks = True
            continue
        if in_sinks and stripped.endswith(":") and "Sinks" not in stripped:
            break
        if not in_sinks:
            continue
        match = re.search(r"(\*)?\s*(\d+)\.\s+(.+)", stripped)
        if not match:
            continue
        name = re.sub(r"\s*\[.*$", "", match.group(3)).strip()
        sinks.append(
            {
                "id": match.group(2),
                "label": name or match.group(2),
                "current": bool(match.group(1)),
            }
        )
    return sinks


def parse_brightnessctl(text: str) -> int | None:
    """Parse `brightnessctl -m` percent field."""
    parts = [p.strip() for p in text.strip().split(",")]
    for part in parts:
        if part.endswith("%"):
            try:
                return int(round(float(part[:-1])))
            except ValueError:
                return None
    match = re.search(r"(\d+)\s*%", text)
    if match:
        return int(match.group(1))
    return None


def parse_nmcli_radio(text: str) -> bool | None:
    value = text.strip().splitlines()[0].strip().casefold() if text.strip() else ""
    if value in {"enabled", "on", "yes"}:
        return True
    if value in {"disabled", "off", "no"}:
        return False
    return None


def parse_nmcli_wifi(text: str) -> list[dict[str, Any]]:
    """Parse `nmcli -t` wifi list rows."""
    networks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split(":")
        if len(parts) < 2:
            continue
        in_use = parts[0].strip() in {"*", "yes", "true"}
        ssid = parts[1].strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        signal = 0
        if len(parts) > 2:
            try:
                signal = int(parts[2] or 0)
            except ValueError:
                signal = 0
        networks.append(
            {
                "id": ssid,
                "label": ssid,
                "current": in_use,
                "signal": signal,
            }
        )
    return networks


def parse_bluetoothctl_powered(text: str) -> bool | None:
    for line in text.splitlines():
        if "powered:" in line.casefold():
            return line.casefold().split("powered:", 1)[1].strip() in {"yes", "on"}
    return None


def parse_bluetoothctl_devices(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = re.search(
            r"Device\s+([0-9A-Fa-f:]{11,17})\s+(.*)$",
            line.strip(),
        )
        if not match:
            continue
        devices.append(
            {
                "mac": match.group(1).upper(),
                "name": (match.group(2) or match.group(1)).strip(),
            }
        )
    return devices


def parse_bluetoothctl_info(text: str) -> dict[str, Any]:
    info: dict[str, Any] = {"connected": False, "paired": False, "name": ""}
    for line in text.splitlines():
        lower = line.strip().casefold()
        if lower.startswith("name:"):
            info["name"] = line.split(":", 1)[1].strip()
        elif lower.startswith("connected:"):
            info["connected"] = "yes" in lower
        elif lower.startswith("paired:"):
            info["paired"] = "yes" in lower
    return info


def parse_powerprofiles(text: str) -> tuple[str | None, list[str]]:
    current = None
    profiles: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Driver:") or line.startswith("Degraded:"):
            continue
        star = line.startswith("*")
        name = line[1:].strip() if star else line
        name = name.split(":", 1)[0].strip()
        if not name or " " in name and name not in {"power-saver", "balanced", "performance"}:
            # `powerprofilesctl get` is a single token
            if not profiles and not star and name in {"power-saver", "balanced", "performance"}:
                current = name
            continue
        if name not in profiles:
            profiles.append(name)
        if star:
            current = name
    if current is None and profiles:
        current = profiles[0]
    if current and current not in profiles:
        profiles.insert(0, current)
    return current, profiles


def parse_hyprsunset_temp(text: str) -> int | None:
    match = re.search(r"(\d{3,5})", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _looks_controller(name: str) -> bool:
    n = name.casefold()
    needles = (
        "controller",
        "xbox",
        "sony",
        "dualsense",
        "dualshock",
        "playstation",
        "nintendo",
        "joy-con",
        "joycon",
        "8bitdo",
        "gamepad",
        "steam deck",
        "steam-controller",
    )
    if any(needle in n for needle in needles):
        return True
    if n.startswith("hidpp"):
        return False
    return False


def read_batteries(host: Host) -> dict[str, Any]:
    root = "/sys/class/power_supply"
    system = None
    controllers: list[dict[str, Any]] = []
    for name in host.listdir(root):
        typ = (host.read(f"{root}/{name}/type") or "").strip()
        if typ and typ.casefold() != "battery":
            continue
        cap_s = host.read(f"{root}/{name}/capacity")
        try:
            percent = int(cap_s) if cap_s is not None else None
        except ValueError:
            percent = None
        status = host.read(f"{root}/{name}/status") or ""
        model = host.read(f"{root}/{name}/model_name") or name
        rec = {
            "id": name,
            "name": model,
            "percent": percent,
            "charging": status.casefold() in {"charging", "full"},
            "status": status,
        }
        upper = name.upper()
        if upper.startswith("BAT") or upper.startswith("CMB"):
            if system is None:
                system = rec
            continue
        if _looks_controller(name) or _looks_controller(model):
            controllers.append(rec)
    return {"system": system, "controllers": controllers}


def _probe_tools(host: Host, *, log: bool = True) -> dict[str, str | None]:
    tools = {
        "volume": first_bin(host, ["omarchy-audio-output-volume", "wpctl"]),
        "volume_read": first_bin(host, ["wpctl"]),
        "mute": first_bin(host, ["omarchy-audio-output-volume", "wpctl"]),
        "sinks": first_bin(host, ["wpctl"]),
        "brightness": first_bin(host, ["omarchy-brightness-display", "brightnessctl"]),
        "brightness_read": first_bin(host, ["brightnessctl", "omarchy-brightness-display"]),
        "nightlight": first_bin(host, ["omarchy-toggle-nightlight", "hyprctl"]),
        "bluetooth": first_bin(host, ["omarchy-bluetooth-power", "bluetoothctl"]),
        "bluetoothctl": first_bin(host, ["bluetoothctl"]),
        "wifi": first_bin(host, ["nmcli", "iwctl"]),
        "powerprofiles": first_bin(host, ["omarchy-powerprofiles-list", "powerprofilesctl"]),
        "powerprofiles_set": first_bin(host, ["omarchy-powerprofiles-set", "powerprofilesctl"]),
        "screenshot": first_bin(host, ["omarchy-capture-screenshot"]),
        "record": first_bin(host, ["omarchy-capture-screenrecording"]),
        "dnd": first_bin(host, ["omarchy-toggle-notification-silencing", "makoctl"]),
        "lock": first_bin(host, ["omarchy-system-lock", "hyprlock", "loginctl"]) or "loginctl",
        "suspend": first_bin(host, ["systemctl"]) or "systemctl",
        "reboot": first_bin(host, ["omarchy-system-reboot", "systemctl"]) or "systemctl",
        "shutdown": first_bin(host, ["omarchy-system-shutdown", "systemctl"]) or "systemctl",
        "logout": first_bin(host, ["omarchy-system-logout", "hyprctl", "loginctl"]) or "loginctl",
        "mangohud": first_bin(host, ["mangohud"]) or "keys",
    }
    if log:
        print(f"matt-dance.arcade: tool PATH={os.environ.get('PATH', '')}", file=sys.stderr, flush=True)
        for key, value in tools.items():
            log_tool(key, value)
    return tools


def collect_status(host: Host | None = None) -> dict[str, Any]:
    host = host or Host()
    ensure_search_path()
    tools = _probe_tools(host)
    audio = {"volume": None, "muted": False, "sinks": []}
    if tools["volume_read"] == "wpctl":
        _code, out, _err = host.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        percent, muted = parse_wpctl_volume(out)
        audio["volume"] = percent
        audio["muted"] = muted
        _code, status_out, _err = host.run(["wpctl", "status"])
        audio["sinks"] = parse_wpctl_sinks(status_out)

    display = {"brightness": None, "nightlight": None}
    if tools["brightness_read"] == "brightnessctl":
        _code, out, _err = host.run(["brightnessctl", "-m"])
        display["brightness"] = parse_brightnessctl(out)
    elif tools["brightness"] == "omarchy-brightness-display":
        _code, out, _err = host.run(["omarchy-brightness-display"])
        display["brightness"] = parse_brightnessctl(out) or parse_hyprsunset_temp(out)

    if tools["nightlight"] == "omarchy-toggle-nightlight":
        _code, out, _err = host.run(["omarchy-toggle-nightlight", "--status"])
        lowered = out.casefold()
        if "on" in lowered and "off" not in lowered.split("on", 1)[0][-8:]:
            display["nightlight"] = "on" in lowered and "off" not in lowered
        temp = parse_hyprsunset_temp(out)
        if temp is not None:
            display["nightlight"] = temp <= 4500
        elif "night" in lowered or "on" in lowered:
            display["nightlight"] = True
        elif "day" in lowered or "off" in lowered:
            display["nightlight"] = False
    elif tools["nightlight"] == "hyprctl":
        _code, out, _err = host.run(["hyprctl", "hyprsunset", "temperature"])
        temp = parse_hyprsunset_temp(out)
        if temp is not None:
            display["nightlight"] = temp <= 4500

    bluetooth: dict[str, Any] = {"powered": None, "devices": [], "discovered": []}
    if tools["bluetooth"] == "omarchy-bluetooth-power":
        _code, out, _err = host.run(["omarchy-bluetooth-power", "is-on"])
        bluetooth["powered"] = parse_nmcli_radio(out)
        if bluetooth["powered"] is None:
            bluetooth["powered"] = out.strip().casefold() in {"1", "true", "yes", "on"}
    if tools["bluetoothctl"]:
        if bluetooth["powered"] is None:
            _code, out, _err = host.run(["bluetoothctl", "show"])
            bluetooth["powered"] = parse_bluetoothctl_powered(out)
        _code, paired_out, _err = host.run(["bluetoothctl", "devices", "Paired"])
        paired = parse_bluetoothctl_devices(paired_out)
        _code, connected_out, _err = host.run(["bluetoothctl", "devices", "Connected"])
        connected_macs = {d["mac"] for d in parse_bluetoothctl_devices(connected_out)}
        bluetooth["devices"] = [
            {
                "mac": dev["mac"],
                "name": dev["name"],
                "connected": dev["mac"] in connected_macs,
                "paired": True,
            }
            for dev in paired
        ]

    wifi: dict[str, Any] = {"powered": None, "ssid": "", "networks": [], "backend": tools["wifi"]}
    if tools["wifi"] == "nmcli":
        _code, out, _err = host.run(["nmcli", "-t", "-f", "WIFI", "radio"])
        wifi["powered"] = parse_nmcli_radio(out)
        _code, active, _err = host.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"]
        )
        for line in active.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and "wireless" in parts[1]:
                wifi["ssid"] = parts[0]
                break
        _code, listed, _err = host.run(
            ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no"],
            timeout=1.5,
        )
        wifi["networks"] = parse_nmcli_wifi(listed)
        if not wifi["ssid"]:
            for net in wifi["networks"]:
                if net.get("current"):
                    wifi["ssid"] = net["id"]
                    break
    elif tools["wifi"] == "iwctl":
        _code, out, _err = host.run(["iwctl", "device", "list"])
        wifi["powered"] = bool(out.strip())
        station = None
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0] not in {"Name", "Devices", "-"} and "wlan" in parts[0]:
                station = parts[0]
                break
        if station:
            _code, show, _err = host.run(["iwctl", "station", station, "show"])
            for line in show.splitlines():
                if "Connected network" in line:
                    wifi["ssid"] = line.split(":", 1)[-1].strip() or line.split()[-1]
            _code, nets, _err = host.run(["iwctl", "station", station, "get-networks"])
            for line in nets.splitlines():
                cols = line.split()
                if len(cols) >= 1 and cols[0] not in {"Network", "name", "-"}:
                    ssid = cols[0]
                    wifi["networks"].append(
                        {
                            "id": ssid,
                            "label": ssid,
                            "current": ssid == wifi["ssid"],
                        }
                    )
            wifi["station"] = station

    performance: dict[str, Any] = {"profile": None, "profiles": []}
    if tools["powerprofiles"] == "powerprofilesctl":
        _code, listed, _err = host.run(["powerprofilesctl", "list"])
        current, profiles = parse_powerprofiles(listed)
        if not current:
            _code, got, _err = host.run(["powerprofilesctl", "get"])
            current, extra = parse_powerprofiles(got)
            for name in extra:
                if name not in profiles:
                    profiles.append(name)
        performance["profile"] = current
        performance["profiles"] = profiles
    elif tools["powerprofiles"] == "omarchy-powerprofiles-list":
        _code, listed, _err = host.run(["omarchy-powerprofiles-list"])
        current, profiles = parse_powerprofiles(listed)
        performance["profile"] = current
        performance["profiles"] = profiles or ["power-saver", "balanced", "performance"]

    notifications = {"dnd": None}
    if tools["dnd"] == "makoctl" or host.which("makoctl"):
        _code, out, _err = host.run(["makoctl", "mode"])
        notifications["dnd"] = "do-not-disturb" in out

    capture = {"recording": False}
    if tools["record"]:
        for pattern in ("gpu-screen-recorder", "wf-recorder", "wl-screenrec"):
            code, out, _err = host.run(["pgrep", "-a", pattern])
            if code == 0 and out.strip():
                capture["recording"] = True
                break

    return {
        "tools": tools,
        "audio": audio,
        "display": display,
        "bluetooth": bluetooth,
        "wifi": wifi,
        "performance": performance,
        "notifications": notifications,
        "capture": capture,
        "battery": read_batteries(host),
    }


def _header(label: str) -> dict[str, Any]:
    return {"id": f"sec-{label.casefold()}", "kind": "header", "label": label, "section": label}


def _action(item_id: str, label: str, section: str, **extra: Any) -> dict[str, Any]:
    row = {"id": item_id, "kind": "action", "label": label, "section": section}
    row.update(extra)
    return row


def build_menu(status: dict[str, Any], session_title: str | None = None) -> list[dict[str, Any]]:
    """Visible, focusable menu rows. Headers are skipped by the UI."""
    tools = status.get("tools") or {}
    items: list[dict[str, Any]] = []

    items.append(_header("Game"))
    game = session_title or "No game running"
    items.append(_action("resume", "Resume", "Game", hint=game))
    items.append(_action("close", "Close game", "Game"))
    items.append(_action("force", "Force quit", "Game"))
    items.append(_action("arcade", "Back to Arcade", "Game"))

    audio = status.get("audio") or {}
    if tools.get("volume"):
        items.append(_header("Audio"))
        items.append(
            {
                "id": "volume",
                "kind": "slider",
                "label": "Volume",
                "section": "Audio",
                "value": audio.get("volume"),
                "min": 0,
                "max": 100,
                "step": 5,
            }
        )
        if tools.get("mute"):
            muted = bool(audio.get("muted"))
            items.append(
                {
                    "id": "mute",
                    "kind": "toggle",
                    "label": "Muted" if muted else "Mute",
                    "section": "Audio",
                    "value": muted,
                }
            )
        sinks = audio.get("sinks") or []
        if tools.get("sinks") and sinks:
            current = next((s["label"] for s in sinks if s.get("current")), sinks[0]["label"])
            items.append(
                {
                    "id": "output",
                    "kind": "picker",
                    "label": f"Output · {current}",
                    "section": "Audio",
                    "options": sinks,
                }
            )

    display = status.get("display") or {}
    if tools.get("brightness") or tools.get("nightlight"):
        items.append(_header("Display"))
        if tools.get("brightness"):
            items.append(
                {
                    "id": "brightness",
                    "kind": "slider",
                    "label": "Brightness",
                    "section": "Display",
                    "value": display.get("brightness"),
                    "min": 1,
                    "max": 100,
                    "step": 5,
                }
            )
        if tools.get("nightlight"):
            night = display.get("nightlight")
            items.append(
                {
                    "id": "nightlight",
                    "kind": "toggle",
                    "label": "Night light",
                    "section": "Display",
                    "value": bool(night),
                }
            )

    bt = status.get("bluetooth") or {}
    if tools.get("bluetooth") or tools.get("bluetoothctl"):
        items.append(_header("Bluetooth"))
        powered = bt.get("powered")
        items.append(
            {
                "id": "bluetooth_power",
                "kind": "toggle",
                "label": "Bluetooth",
                "section": "Bluetooth",
                "value": bool(powered),
            }
        )
        for dev in bt.get("devices") or []:
            connected = bool(dev.get("connected"))
            items.append(
                _action(
                    "bluetooth_disconnect" if connected else "bluetooth_connect",
                    f"{'Disconnect' if connected else 'Connect'} {dev.get('name') or dev.get('mac')}",
                    "Bluetooth",
                    arg={"mac": dev.get("mac")},
                )
            )
        for dev in bt.get("discovered") or []:
            items.append(
                _action(
                    "bluetooth_pair",
                    f"Pair {dev.get('name') or dev.get('mac')}",
                    "Bluetooth",
                    arg={"mac": dev.get("mac")},
                )
            )
        if tools.get("bluetoothctl"):
            items.append(_action("bluetooth_scan", "Scan for devices", "Bluetooth"))

    wifi = status.get("wifi") or {}
    if tools.get("wifi"):
        items.append(_header("Wi-Fi"))
        ssid = wifi.get("ssid") or "Not connected"
        items.append(
            {
                "id": "wifi_power",
                "kind": "toggle",
                "label": "Wi-Fi",
                "section": "Wi-Fi",
                "value": bool(wifi.get("powered")),
            }
        )
        networks = wifi.get("networks") or []
        items.append(
            {
                "id": "wifi_connect",
                "kind": "picker" if networks else "action",
                "label": f"Network · {ssid}",
                "section": "Wi-Fi",
                "options": networks,
            }
        )

    if tools.get("mangohud") or tools.get("powerprofiles"):
        items.append(_header("Performance"))
        if tools.get("mangohud"):
            items.append(_action("mangohud", "MangoHud overlay", "Performance"))
        profiles = (status.get("performance") or {}).get("profiles") or []
        current = (status.get("performance") or {}).get("profile")
        if tools.get("powerprofiles") and profiles:
            items.append(
                {
                    "id": "profile_set",
                    "kind": "picker",
                    "label": f"Power profile · {current or 'unknown'}",
                    "section": "Performance",
                    "options": [
                        {"id": name, "label": name, "current": name == current}
                        for name in profiles
                    ],
                }
            )

    if tools.get("screenshot") or tools.get("record"):
        items.append(_header("Capture"))
        if tools.get("screenshot"):
            items.append(_action("screenshot", "Screenshot", "Capture"))
        if tools.get("record"):
            rec = bool((status.get("capture") or {}).get("recording"))
            items.append(
                _action(
                    "record",
                    "Stop recording" if rec else "Start recording",
                    "Capture",
                )
            )

    if tools.get("dnd"):
        items.append(_header("Notifications"))
        dnd = bool((status.get("notifications") or {}).get("dnd"))
        items.append(
            {
                "id": "dnd",
                "kind": "toggle",
                "label": "Do not disturb",
                "section": "Notifications",
                "value": dnd,
            }
        )

    # systemctl / loginctl are always present on Omarchy; never hide Power.
    items.append(_header("Power"))
    for name, label in (
        ("lock", "Lock"),
        ("suspend", "Suspend"),
        ("reboot", "Restart"),
        ("shutdown", "Shut down"),
        ("logout", "Log out"),
    ):
        items.append(_action(name, label, "Power", confirm=True))

    return items


def apply_action(
    action: str,
    args: dict[str, Any] | None = None,
    host: Host | None = None,
) -> dict[str, Any]:
    host = host or Host()
    args = args or {}
    ensure_search_path()
    tools = _probe_tools(host, log=False)

    def ok(detail: str = "") -> dict[str, Any]:
        return {"ok": True, "action": action, "detail": detail}

    def fail(detail: str) -> dict[str, Any]:
        return {"ok": False, "action": action, "detail": detail}

    def run(argv: list[str], timeout: float = 4.0) -> tuple[int, str, str]:
        return host.run(argv, timeout=timeout)

    if action == "volume_nudge":
        delta = int(args.get("delta") or 5)
        tool = tools.get("volume")
        if tool == "omarchy-audio-output-volume":
            run([tool, "raise" if delta > 0 else "lower"])
            return ok()
        if tool == "wpctl":
            step = f"{abs(delta)}%{'+' if delta > 0 else '-'}"
            run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", step])
            return ok()
        return fail("volume tool missing")

    if action == "volume_set":
        value = max(0, min(150, int(args.get("value") or 0)))
        if tools.get("volume_read") == "wpctl" or tools.get("volume") == "wpctl":
            run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value}%"])
            return ok()
        if tools.get("volume") == "omarchy-audio-output-volume":
            run(["omarchy-audio-output-volume", f"{value}"])
            return ok()
        return fail("volume tool missing")

    if action == "mute":
        tool = tools.get("mute")
        if tool == "omarchy-audio-output-volume":
            run([tool, "mute-toggle"])
            return ok()
        if tool == "wpctl":
            run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
            return ok()
        return fail("mute tool missing")

    if action == "output":
        sink = str(args.get("sink") or args.get("value") or args.get("id") or "")
        if not sink:
            return fail("missing sink")
        if tools.get("sinks") == "wpctl":
            run(["wpctl", "set-default", sink])
            return ok(sink)
        return fail("output picker unavailable")

    if action == "brightness_nudge":
        delta = int(args.get("delta") or 5)
        tool = tools.get("brightness")
        if tool == "omarchy-brightness-display":
            run([tool, f"+{abs(delta)}%" if delta > 0 else f"{abs(delta)}%-"])
            return ok()
        if tool == "brightnessctl":
            run([tool, "set", f"{abs(delta)}%{'+' if delta > 0 else '-'}"])
            return ok()
        return fail("brightness tool missing")

    if action == "brightness_set":
        value = max(1, min(100, int(args.get("value") or 50)))
        tool = tools.get("brightness")
        if tool == "omarchy-brightness-display":
            run([tool, f"{value}%"])
            return ok()
        if tool == "brightnessctl":
            run([tool, "set", f"{value}%"])
            return ok()
        return fail("brightness tool missing")

    if action == "nightlight":
        if tools.get("nightlight") == "omarchy-toggle-nightlight":
            run(["omarchy-toggle-nightlight"])
            return ok()
        if tools.get("nightlight") == "hyprctl":
            _code, out, _err = run(["hyprctl", "hyprsunset", "temperature"])
            temp = parse_hyprsunset_temp(out) or 6000
            run(["hyprctl", "hyprsunset", "temperature", "4000" if temp > 4500 else "6000"])
            return ok()
        return fail("night light unavailable")

    if action == "bluetooth_power":
        if tools.get("bluetooth") == "omarchy-bluetooth-power":
            run(["omarchy-bluetooth-power", "toggle"])
            return ok()
        if tools.get("bluetoothctl"):
            _code, out, _err = run(["bluetoothctl", "show"])
            powered = parse_bluetoothctl_powered(out)
            run(["bluetoothctl", "power", "off" if powered else "on"])
            return ok()
        return fail("bluetooth unavailable")

    if action in {"bluetooth_connect", "bluetooth_disconnect", "bluetooth_pair"}:
        mac = str(args.get("mac") or args.get("value") or "")
        if not mac:
            return fail("missing mac")
        verb = {
            "bluetooth_connect": "connect",
            "bluetooth_disconnect": "disconnect",
            "bluetooth_pair": "pair",
        }[action]
        omarchy_dev = host.which("omarchy-bluetooth-device")
        if omarchy_dev:
            run([omarchy_dev, verb, mac], timeout=12)
            if verb == "pair":
                run([omarchy_dev, "connect", mac], timeout=12)
            return ok(mac)
        if tools.get("bluetoothctl"):
            run(["bluetoothctl", verb, mac], timeout=12)
            if verb == "pair":
                run(["bluetoothctl", "connect", mac], timeout=12)
            return ok(mac)
        return fail("bluetooth unavailable")

    if action == "bluetooth_scan":
        if not tools.get("bluetoothctl"):
            return fail("bluetoothctl missing")
        run(["bluetoothctl", "--timeout", "8", "scan", "on"], timeout=12)
        _code, listed, _err = run(["bluetoothctl", "devices"])
        discovered = parse_bluetoothctl_devices(listed)
        paired_macs = {d["mac"] for d in parse_bluetoothctl_devices(
            run(["bluetoothctl", "devices", "Paired"])[1]
        )}
        fresh = [d for d in discovered if d["mac"] not in paired_macs]
        return {"ok": True, "action": action, "discovered": fresh}

    if action == "wifi_power":
        if tools.get("wifi") == "nmcli":
            _code, out, _err = run(["nmcli", "-t", "-f", "WIFI", "radio"])
            on = parse_nmcli_radio(out)
            run(["nmcli", "radio", "wifi", "off" if on else "on"])
            return ok()
        if tools.get("wifi") == "iwctl":
            station = str(args.get("station") or "wlan0")
            run(["iwctl", "device", station, "set-property", "Powered", "on"])
            return ok()
        return fail("wifi tool missing")

    if action == "wifi_connect":
        ssid = str(args.get("ssid") or args.get("value") or args.get("id") or "")
        if not ssid:
            return fail("missing ssid")
        if tools.get("wifi") == "nmcli":
            code, _out, err = run(["nmcli", "connection", "up", ssid], timeout=15)
            if code != 0:
                code, _out, err = run(["nmcli", "device", "wifi", "connect", ssid], timeout=15)
            return ok(ssid) if code == 0 else fail(err.strip() or "connect failed")
        if tools.get("wifi") == "iwctl":
            station = str(args.get("station") or "wlan0")
            code, _out, err = run(["iwctl", "station", station, "connect", ssid], timeout=15)
            return ok(ssid) if code == 0 else fail(err.strip() or "connect failed")
        return fail("wifi tool missing")

    if action == "profile_set":
        name = str(args.get("profile") or args.get("value") or args.get("id") or "")
        if not name:
            return fail("missing profile")
        if tools.get("powerprofiles_set") == "omarchy-powerprofiles-set":
            run(["omarchy-powerprofiles-set", "autodetect", name])
            return ok(name)
        if host.which("powerprofilesctl"):
            run(["powerprofilesctl", "set", name])
            return ok(name)
        return fail("power profile unavailable")

    if action == "screenshot":
        if not tools.get("screenshot"):
            return fail("screenshot tool missing")
        run(["omarchy-capture-screenshot", "fullscreen"])
        return ok()

    if action == "record":
        if not tools.get("record"):
            return fail("recording tool missing")
        run(["omarchy-capture-screenrecording"])
        return ok()

    if action == "dnd":
        if tools.get("dnd") == "omarchy-toggle-notification-silencing":
            run(["omarchy-toggle-notification-silencing"])
            return ok()
        if host.which("makoctl"):
            run(["makoctl", "mode", "-t", "do-not-disturb"])
            return ok()
        return fail("do-not-disturb unavailable")

    if action == "lock":
        if tools.get("lock") == "omarchy-system-lock":
            run(["omarchy-system-lock"])
            return ok()
        if host.which("hyprlock"):
            run(["hyprlock"])
            return ok()
        run(["loginctl", "lock-session"])
        return ok()

    if action == "suspend":
        run(["systemctl", "suspend"])
        return ok()

    if action == "reboot":
        if tools.get("reboot") == "omarchy-system-reboot":
            run(["omarchy-system-reboot"])
            return ok()
        run(["systemctl", "reboot"])
        return ok()

    if action == "shutdown":
        if tools.get("shutdown") == "omarchy-system-shutdown":
            run(["omarchy-system-shutdown"])
            return ok()
        run(["systemctl", "poweroff"])
        return ok()

    if action == "logout":
        if tools.get("logout") == "omarchy-system-logout":
            run(["omarchy-system-logout"])
            return ok()
        if host.which("hyprctl"):
            run(["hyprctl", "dispatch", "exit"])
            return ok()
        run(["loginctl", "terminate-session", ""])
        return ok()

    return fail(f"unknown action {action}")


def menu_payload(session_title: str | None = None, host: Host | None = None) -> dict[str, Any]:
    host = host or Host()
    ensure_search_path()
    try:
        status = collect_status(host)
    except Exception as exc:  # noqa: BLE001
        print(f"matt-dance.arcade: collect_status failed: {exc}", file=sys.stderr, flush=True)
        status = {"tools": _probe_tools(host)}
    items = build_menu(status, session_title)
    sections = [i["label"] for i in items if i.get("kind") == "header"]
    print(
        f"matt-dance.arcade: sysmenu items={len(items)} sections={','.join(sections)}",
        file=sys.stderr,
        flush=True,
    )
    return {
        "status": status,
        "items": items,
        "sessionTitle": session_title or "",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Arcade system menu helper")
    parser.add_argument(
        "command",
        choices=("status", "items", "do"),
        help="status snapshot, menu items, or run an action",
    )
    parser.add_argument("action", nargs="?", help="Action name for `do`")
    parser.add_argument("--session-title", default="", help="Running game title")
    parser.add_argument("--json-args", default="", help="JSON object of action arguments")
    args, unknown = parser.parse_known_args(argv)

    extra: dict[str, Any] = {}
    if args.json_args:
        extra.update(json.loads(args.json_args))
    key = None
    for token in unknown:
        if token.startswith("--") and token != "--":
            key = token[2:].replace("-", "_")
        elif key:
            extra[key] = token
            key = None

    if args.command == "status":
        print(json.dumps(collect_status(), ensure_ascii=False))
        return 0
    if args.command == "items":
        print(json.dumps(menu_payload(args.session_title or None), ensure_ascii=False))
        return 0
    if not args.action:
        print(json.dumps({"ok": False, "detail": "missing action"}))
        return 2
    result = apply_action(args.action, extra)
    if args.action == "bluetooth_scan":
        status = collect_status()
        status.setdefault("bluetooth", {})["discovered"] = result.get("discovered") or []
        result["items"] = build_menu(status, args.session_title or None)
        result["status"] = status
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
