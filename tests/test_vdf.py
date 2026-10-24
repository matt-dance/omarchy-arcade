"""Tests for the VDF parsers."""

from __future__ import annotations

import struct
import unittest

from arcade.vdf import parse_binary, parse_text, steam_shortcut_app_id


class TextTextVDF(unittest.TestCase):
    def test_simple(self):
        data = parse_text(
            '''
            "AppState"
            {
                "appid" "570"
                "name" "Dota 2"
                "StateFlags" "4"
            }
            '''
        )
        self.assertEqual(data["AppState"]["appid"], "570")
        self.assertEqual(data["AppState"]["name"], "Dota 2")

    def test_nested_and_comments(self):
        data = parse_text(
            '''
            "libraryfolders"
            {
                // a comment
                "0"
                {
                    "path" "/games"
                    "apps"
                    {
                        "570" "1"
                    }
                }
            }
            '''
        )
        self.assertEqual(data["libraryfolders"]["0"]["path"], "/games")
        self.assertEqual(data["libraryfolders"]["0"]["apps"]["570"], "1")

    def test_escaped_quotes(self):
        data = parse_text('"root" { "name" "Say \\"hi\\"" }')
        self.assertEqual(data["root"]["name"], 'Say "hi"')


class TestBinaryVDF(unittest.TestCase):
    def test_shortcuts_shape(self):
        # Manually craft a tiny binary VDF:
        # shortcuts { 0 { AppName "Celeste" appid <int32> } }
        def cstring(s: str) -> bytes:
            return s.encode("utf-8") + b"\x00"

        body = b"".join(
            [
                b"\x00",
                cstring("shortcuts"),
                b"\x00",
                cstring("0"),
                b"\x01",
                cstring("AppName"),
                cstring("Celeste"),
                b"\x02",
                cstring("appid"),
                struct.pack("<i", 12345),
                b"\x08",  # end of 0
                b"\x08",  # end of shortcuts
            ]
        )
        data = parse_binary(body)
        self.assertEqual(data["shortcuts"]["0"]["AppName"], "Celeste")
        self.assertEqual(data["shortcuts"]["0"]["appid"], 12345)

    def test_shortcut_app_id(self):
        self.assertEqual(steam_shortcut_app_id(1), (1 << 32) | 0x02000000)


if __name__ == "__main__":
    unittest.main()
