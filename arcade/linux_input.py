"""Minimal Linux evdev bindings (stdlib only)."""

from __future__ import annotations

import ctypes
import fcntl
import glob
import os
import struct
from dataclasses import dataclass

# ioctl helpers
_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2


def _ioc(direction: int, letter: str, number: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(letter) << 8) | number


EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0
SYN_DROPPED = 3

BTN_GAMEPAD = 0x130
BTN_SOUTH = 0x130
BTN_EAST = 0x131
BTN_NORTH = 0x133
BTN_WEST = 0x134
BTN_TL = 0x136
BTN_TR = 0x137
BTN_TL2 = 0x138
BTN_TR2 = 0x139
BTN_SELECT = 0x13A
BTN_START = 0x13B
BTN_MODE = 0x13C
BTN_THUMBL = 0x13D
BTN_THUMBR = 0x13E
BTN_DPAD_UP = 0x220
BTN_DPAD_DOWN = 0x221
BTN_DPAD_LEFT = 0x222
BTN_DPAD_RIGHT = 0x223

ABS_X = 0x00
ABS_Y = 0x01
ABS_Z = 0x02
ABS_RX = 0x03
ABS_RY = 0x04
ABS_RZ = 0x05
ABS_HAT0X = 0x10
ABS_HAT0Y = 0x11
ABS_MAX = 0x3F
KEY_MAX = 0x2FF

EVIOCGID = _ioc(_IOC_READ, "E", 0x02, 8)


def EVIOCGNAME(length: int) -> int:
    return _ioc(_IOC_READ, "E", 0x06, length)


def EVIOCGBIT(ev_type: int, length: int) -> int:
    return _ioc(_IOC_READ, "E", 0x20 + ev_type, length)


def EVIOCGABS(axis: int) -> int:
    return _ioc(_IOC_READ, "E", 0x40 + axis, struct.calcsize("iiiiii"))


# input_event: timeval + type + code + value. timeval is 16 bytes on 64-bit, 8 on 32-bit.
_IS_64 = struct.calcsize("l") == 8
EVENT_FORMAT = "QQHHi" if _IS_64 else "IIHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

BUTTON_MAP = {
    BTN_SOUTH: "A",
    BTN_EAST: "B",
    BTN_WEST: "X",
    BTN_NORTH: "Y",
    BTN_TL: "LB",
    BTN_TR: "RB",
    BTN_TL2: "LT",
    BTN_TR2: "RT",
    BTN_SELECT: "SELECT",
    BTN_START: "START",
    BTN_MODE: "GUIDE",
    BTN_THUMBL: "L3",
    BTN_THUMBR: "R3",
    BTN_DPAD_UP: "DPAD_UP",
    BTN_DPAD_DOWN: "DPAD_DOWN",
    BTN_DPAD_LEFT: "DPAD_LEFT",
    BTN_DPAD_RIGHT: "DPAD_RIGHT",
}

# Steam virtual Xbox pad
STEAM_VIRTUAL_VID = 0x28DE
STEAM_VIRTUAL_PID = 0x11FF


@dataclass
class DeviceInfo:
    path: str
    name: str
    bustype: int
    vendor: int
    product: int
    version: int

    @property
    def is_steam_virtual(self) -> bool:
        return self.vendor == STEAM_VIRTUAL_VID and self.product == STEAM_VIRTUAL_PID

    @property
    def kind(self) -> str:
        name = self.name.lower()
        if "dualsense" in name or "dualshock" in name or "sony" in name or "playstation" in name:
            return "playstation"
        if "xbox" in name or "microsoft" in name or "x-box" in name:
            return "xbox"
        if "nintendo" in name or "joy-con" in name or "pro controller" in name:
            return "nintendo"
        if "8bitdo" in name:
            return "xbox"
        if self.is_steam_virtual:
            return "steam"
        return "generic"

    def to_dict(self) -> dict:
        return {
            "id": f"{self.vendor:04x}:{self.product:04x}:{os.path.basename(self.path)}",
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "virtual": self.is_steam_virtual,
            "vendor": self.vendor,
            "product": self.product,
        }


def _bit_set(buf: bytes, bit: int) -> bool:
    return bool(buf[bit // 8] & (1 << (bit % 8)))


def list_gamepads() -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for path in sorted(glob.glob("/dev/input/event*")):
        info = inspect_device(path)
        if info:
            devices.append(info)
    return devices


def inspect_device(path: str) -> DeviceInfo | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        name_buf = ctypes.create_string_buffer(256)
        try:
            fcntl.ioctl(fd, EVIOCGNAME(256), name_buf)
        except OSError:
            return None
        name = name_buf.value.decode("utf-8", errors="replace") or path

        id_buf = ctypes.create_string_buffer(8)
        try:
            fcntl.ioctl(fd, EVIOCGID, id_buf)
        except OSError:
            return None
        bustype, vendor, product, version = struct.unpack("HHHH", id_buf.raw[:8])

        key_bits = ctypes.create_string_buffer((KEY_MAX + 7) // 8)
        try:
            fcntl.ioctl(fd, EVIOCGBIT(EV_KEY, len(key_bits)), key_bits)
        except OSError:
            return None
        # Must look like a gamepad
        if not (_bit_set(key_bits.raw, BTN_GAMEPAD) or _bit_set(key_bits.raw, BTN_SOUTH)):
            return None
        # Skip motion-sensor-only nodes (DualSense gyro often has few gamepad buttons)
        return DeviceInfo(
            path=path,
            name=name,
            bustype=bustype,
            vendor=vendor,
            product=product,
            version=version,
        )
    finally:
        os.close(fd)


def read_events(fd: int) -> list[tuple[int, int, int]]:
    """Read available input_events; return list of (type, code, value)."""
    out: list[tuple[int, int, int]] = []
    while True:
        try:
            data = os.read(fd, EVENT_SIZE)
        except BlockingIOError:
            break
        except OSError:
            break
        if len(data) < EVENT_SIZE:
            break
        _sec, _usec, etype, code, value = struct.unpack(EVENT_FORMAT, data)
        out.append((etype, code, value))
    return out


# --- uinput virtual keyboard (for keys= bindings) ---------------------------

UI_DEV_CREATE = _ioc(_IOC_NONE, "U", 1, 0)
UI_DEV_DESTROY = _ioc(_IOC_NONE, "U", 2, 0)
UI_SET_EVBIT = _ioc(_IOC_WRITE, "U", 100, 4)
UI_SET_KEYBIT = _ioc(_IOC_WRITE, "U", 101, 4)
UI_DEV_SETUP = _ioc(_IOC_WRITE, "U", 3, struct.calcsize("HHHH80sI"))

KEY_CODES = {
    "ESC": 1,
    "ESCAPE": 1,
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "0": 11,
    "MINUS": 12,
    "EQUAL": 13,
    "BACKSPACE": 14,
    "TAB": 15,
    "Q": 16,
    "W": 17,
    "E": 18,
    "R": 19,
    "T": 20,
    "Y": 21,
    "U": 22,
    "I": 23,
    "O": 24,
    "P": 25,
    "ENTER": 28,
    "RETURN": 28,
    "CTRL": 29,
    "LEFTCTRL": 29,
    "A": 30,
    "S": 31,
    "D": 32,
    "F": 33,
    "G": 34,
    "H": 35,
    "J": 36,
    "K": 37,
    "L": 38,
    "SHIFT": 42,
    "LEFTSHIFT": 42,
    "Z": 44,
    "X": 45,
    "C": 46,
    "V": 47,
    "B": 48,
    "N": 49,
    "M": 50,
    "SPACE": 57,
    "F12": 88,
    "RIGHTSHIFT": 54,
    "SHIFT_R": 54,
    "RIGHTCTRL": 97,
    "CTRL_R": 97,
    "ALT": 56,
    "LEFTALT": 56,
    "ALT_R": 100,
    "RIGHTALT": 100,
    "SUPER": 125,
    "LEFTMETA": 125,
    "META": 125,
    "RIGHTMETA": 126,
    "UP": 103,
    "LEFT": 105,
    "RIGHT": 106,
    "DOWN": 108,
    "PRINT": 99,
    "VOLUMEUP": 115,
    "VOLUMEDOWN": 114,
}


class VirtualKeyboard:
    def __init__(self) -> None:
        self.fd = -1

    def open(self) -> None:
        if self.fd >= 0:
            return
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        for code in set(KEY_CODES.values()):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        name = b"Omarchy Arcade Keyboard"
        setup = struct.pack("HHHH80sI", 0x03, 0x0000, 0x0000, 1, name.ljust(80, b"\0"), 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)

    def close(self) -> None:
        if self.fd < 0:
            return
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)
        self.fd = -1

    def _emit(self, etype: int, code: int, value: int) -> None:
        import time

        now = time.time()
        sec = int(now)
        usec = int((now - sec) * 1_000_000)
        if _IS_64:
            data = struct.pack(EVENT_FORMAT, sec, usec, etype, code, value)
        else:
            data = struct.pack(EVENT_FORMAT, sec, usec, etype, code, value)
        os.write(self.fd, data)

    def tap_combo(self, keys: str) -> None:
        """Type a combo like 'SUPER + SPACE' or 'SHIFT_R + F12'."""
        self.open()
        parts = [p.strip().upper().replace("-", "_") for p in keys.split("+")]
        codes: list[int] = []
        for part in parts:
            aliases = {
                "CTRL": "LEFTCTRL",
                "CONTROL": "LEFTCTRL",
                "SHIFT": "LEFTSHIFT",
                "ALT": "LEFTALT",
                "SUPER": "LEFTMETA",
                "META": "LEFTMETA",
                "WIN": "LEFTMETA",
                "CMD": "LEFTMETA",
            }
            name = aliases.get(part, part)
            if name not in KEY_CODES:
                raise ValueError(f"unknown key {part!r}")
            codes.append(KEY_CODES[name])
        for code in codes:
            self._emit(EV_KEY, code, 1)
        self._emit(EV_SYN, SYN_REPORT, 0)
        for code in reversed(codes):
            self._emit(EV_KEY, code, 0)
        self._emit(EV_SYN, SYN_REPORT, 0)
