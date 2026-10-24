"""Minimal Valve Data Format (text ACF/VDF and binary shortcuts.vDF) parsers.

Reimplemented from the public format; no third-party VDF libraries.
"""

from __future__ import annotations

from typing import Any


class VDFError(ValueError):
    pass


def parse_text(text: str) -> dict[str, Any]:
    """Parse a text VDF/ACF document into nested dicts."""
    tokens = _tokenize(text)
    if not tokens:
        return {}
    pos = 0

    def parse_value() -> Any:
        nonlocal pos
        if pos >= len(tokens):
            raise VDFError("unexpected end of VDF")
        tok = tokens[pos]
        if tok == "{":
            pos += 1
            obj: dict[str, Any] = {}
            while pos < len(tokens) and tokens[pos] != "}":
                key = tokens[pos]
                if key in ("{", "}"):
                    raise VDFError(f"expected key, got {key!r}")
                pos += 1
                if pos >= len(tokens):
                    raise VDFError(f"missing value for key {key!r}")
                if tokens[pos] == "{":
                    obj[key] = parse_value()
                else:
                    obj[key] = tokens[pos]
                    pos += 1
            if pos >= len(tokens) or tokens[pos] != "}":
                raise VDFError("unclosed object")
            pos += 1
            return obj
        raise VDFError(f"expected object, got {tok!r}")

    # Top level may be one or more "key" { … } pairs.
    root: dict[str, Any] = {}
    while pos < len(tokens):
        key = tokens[pos]
        pos += 1
        if pos >= len(tokens):
            raise VDFError(f"missing value for key {key!r}")
        root[key] = parse_value()
    return root


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c in "{}":
            tokens.append(c)
            i += 1
            continue
        if c == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                ch = text[i]
                if ch == "\\":
                    i += 1
                    if i >= n:
                        raise VDFError("trailing escape")
                    esc = text[i]
                    buf.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(esc, esc))
                    i += 1
                    continue
                if ch == '"':
                    i += 1
                    break
                buf.append(ch)
                i += 1
            tokens.append("".join(buf))
            continue
        # Bare token (rare in Valve files, but accepted)
        start = i
        while i < n and text[i] not in " \t\r\n{}\"":
            i += 1
        tokens.append(text[start:i])
    return tokens


# Binary VDF type tags used in shortcuts.vdf
_BIN_NONE = 0x00
_BIN_STRING = 0x01
_BIN_INT32 = 0x02
_BIN_FLOAT32 = 0x03
_BIN_POINTER = 0x04
_BIN_WIDESTRING = 0x05
_BIN_COLOR = 0x06
_BIN_UINT64 = 0x07
_BIN_END = 0x08
_BIN_INT64 = 0x0A


def parse_binary(data: bytes) -> dict[str, Any]:
    """Parse a binary VDF blob (e.g. Steam shortcuts.vdf)."""
    view = memoryview(data)
    pos = 0

    def read_cstring() -> str:
        nonlocal pos
        start = pos
        while pos < len(view) and view[pos] != 0:
            pos += 1
        s = bytes(view[start:pos]).decode("utf-8", errors="replace")
        if pos < len(view):
            pos += 1
        return s

    def parse_object() -> dict[str, Any]:
        nonlocal pos
        obj: dict[str, Any] = {}
        while pos < len(view):
            tag = view[pos]
            pos += 1
            if tag == _BIN_END:
                break
            key = read_cstring()
            if tag == _BIN_NONE:
                obj[key] = parse_object()
            elif tag == _BIN_STRING:
                obj[key] = read_cstring()
            elif tag == _BIN_INT32 or tag == _BIN_COLOR or tag == _BIN_POINTER:
                if pos + 4 > len(view):
                    raise VDFError("truncated int32")
                obj[key] = int.from_bytes(view[pos : pos + 4], "little", signed=True)
                pos += 4
            elif tag == _BIN_FLOAT32:
                if pos + 4 > len(view):
                    raise VDFError("truncated float32")
                import struct

                obj[key] = struct.unpack("<f", bytes(view[pos : pos + 4]))[0]
                pos += 4
            elif tag == _BIN_UINT64 or tag == _BIN_INT64:
                if pos + 8 > len(view):
                    raise VDFError("truncated int64")
                signed = tag == _BIN_INT64
                obj[key] = int.from_bytes(view[pos : pos + 8], "little", signed=signed)
                pos += 8
            elif tag == _BIN_WIDESTRING:
                # UTF-16LE, null-terminated (2 zero bytes)
                start = pos
                while pos + 1 < len(view) and not (view[pos] == 0 and view[pos + 1] == 0):
                    pos += 2
                obj[key] = bytes(view[start:pos]).decode("utf-16-le", errors="replace")
                pos += 2
            else:
                raise VDFError(f"unknown binary VDF type 0x{tag:02x} at key {key!r}")
        return obj

    return parse_object()


def steam_shortcut_app_id(shortcut_id: int) -> int:
    """Non-Steam shortcut app id used by steam://rungameid/."""
    return (int(shortcut_id) << 32) | 0x02000000
