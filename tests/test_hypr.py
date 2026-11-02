"""Hyprland layer-blur helper — parse and apply without a live compositor."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from arcade.hypr import FALLBACK_OPACITY, NAMESPACE, apply_layer_blur, collect_namespaces

ROOT = Path(__file__).resolve().parent.parent

LAYERS = {
    "HDMI-A-1": {
        "levels": {
            "2": [{"namespace": "omarchy-bar", "w": 1920, "h": 36}],
            "3": [{"namespace": "matt-dance-arcade", "w": 1920, "h": 1080}],
        }
    }
}


class TestCollectNamespaces(unittest.TestCase):
    def test_walks_hyprctl_layers_json(self):
        self.assertEqual(
            collect_namespaces(LAYERS),
            ["omarchy-bar", "matt-dance-arcade"],
        )

    def test_empty(self):
        self.assertEqual(collect_namespaces({}), [])
        self.assertEqual(collect_namespaces(None), [])


class TestApplyLayerBlur(unittest.TestCase):
    def test_applies_new_and_old_syntax_and_enables_decoration(self):
        calls: list[tuple[str, ...]] = []

        def fake_hyprctl(*args: str):
            calls.append(args)
            if args[:3] == ("-j", "getoption", "decoration:blur:enabled"):
                return 0, json.dumps({"int": 0}), ""
            if args[:3] == ("-j", "getoption", "decoration:blur:size"):
                return 0, json.dumps({"int": 8}), ""
            if args[:2] == ("-j", "layers"):
                return 0, json.dumps(LAYERS), ""
            if args[0] == "keyword":
                return 0, "ok", ""
            return 1, "", "unknown"

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake_hyprctl):
            result = apply_layer_blur(True, namespace=NAMESPACE)

        self.assertTrue(result["enabledDecorationBlur"])
        self.assertTrue(result["decorationBlur"])
        self.assertTrue(result["active"])
        self.assertIn("matt-dance-arcade", result["matched"])
        self.assertTrue(any("blur on, match:namespace" in r for r in result["applied"]))
        self.assertTrue(any(r.startswith("blur, ") for r in result["applied"]))
        self.assertEqual(result["fallbackOpacity"], 0.7)
        self.assertIn(("keyword", "decoration:blur:enabled", "true"), calls)

    def test_stays_inactive_when_decoration_blur_cannot_enable(self):
        def fake_hyprctl(*args: str):
            if args[:3] == ("-j", "getoption", "decoration:blur:enabled"):
                return 0, json.dumps({"int": 0}), ""
            if args[:3] == ("-j", "getoption", "decoration:blur:size"):
                return 0, json.dumps({"int": 8}), ""
            if args[:2] == ("-j", "layers"):
                return 0, json.dumps({"DP-1": {"levels": {"3": [{"namespace": "quickshell"}]}}}), ""
            if args[:3] == ("keyword", "decoration:blur:enabled", "true"):
                return 1, "", "nope"
            if args[0] == "keyword":
                return 0, "ok", ""
            return 1, "", "unknown"

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake_hyprctl):
            result = apply_layer_blur(True)

        self.assertFalse(result["active"])
        self.assertIn("quickshell", result["targets"])
        self.assertGreaterEqual(result["fallbackOpacity"], FALLBACK_OPACITY)


class TestOverlayHyprWiring(unittest.TestCase):
    def test_qml_logs_namespace_and_falls_back(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        lua = (ROOT / "hypr" / "arcade.lua").read_text(encoding="utf-8")
        self.assertIn("function logLayerNamespace()", qml)
        self.assertIn("layer namespace=", qml)
        self.assertIn("bin/arcade-hypr", qml)
        self.assertIn("effectiveOpacity", qml)
        self.assertIn("blurUnavailable", qml)
        self.assertIn("surfaceFormat.opaque: false", qml)
        self.assertIn("WlrLayershell.namespace: root.layerNamespace", qml)
        self.assertIn('readonly property string layerNamespace: "matt-dance-arcade"', qml)
        self.assertIn("blur on, match:namespace", lua)
        self.assertIn("hl.layer_rule", lua)
        self.assertIn("ignore_alpha", lua)
        menu = (ROOT / "QuickMenu.qml").read_text(encoding="utf-8")
        self.assertIn("surfaceFormat.opaque: false", menu)
        self.assertIn('WlrLayershell.namespace: "matt-dance-arcade-quickmenu"', menu)
