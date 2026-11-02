"""Hyprland layer-blur helper — parse and apply without a live compositor."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import unittest
from importlib.machinery import SourceFileLoader
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

    def test_restore_decoration_on_close(self):
        calls: list[tuple[str, ...]] = []

        def fake_hyprctl(*args: str):
            calls.append(args)
            if args[:3] == ("-j", "getoption", "decoration:blur:enabled"):
                return 0, json.dumps({"int": 1}), ""
            if args[:3] == ("-j", "getoption", "decoration:blur:size"):
                return 0, json.dumps({"int": 8}), ""
            if args[:2] == ("-j", "layers"):
                return 0, json.dumps(LAYERS), ""
            if args[0] == "keyword":
                return 0, "ok", ""
            return 1, "", "unknown"

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake_hyprctl):
            result = apply_layer_blur(False, namespace=NAMESPACE, restore_decoration=True)

        self.assertTrue(result["ok"])
        self.assertFalse(result["wanted"])
        self.assertFalse(result["active"])
        self.assertIn(("keyword", "decoration:blur:enabled", "false"), calls)
        self.assertTrue(any("blur off" in r for r in result["applied"]))


class TestArcadeHyprCli(unittest.TestCase):
    """QML builds `apply --namespace …` after the subcommand. That must parse."""

    QML_OPEN = ["apply", "--namespace", "matt-dance-arcade"]
    QML_CLOSE = ["apply", "--namespace", "matt-dance-arcade", "--off", "--restore-decoration"]

    def _load(self):
        loader = SourceFileLoader("arcade_hypr_bin", str(ROOT / "bin" / "arcade-hypr"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def _fake_hyprctl(self, *args: str):
        if args[:3] == ("-j", "getoption", "decoration:blur:enabled"):
            return 0, json.dumps({"int": 0}), ""
        if args[:3] == ("-j", "getoption", "decoration:blur:size"):
            return 0, json.dumps({"int": 8}), ""
        if args[:2] == ("-j", "layers"):
            return 0, json.dumps(LAYERS), ""
        if args[0] == "keyword":
            return 0, "ok", ""
        return 1, "", "unknown"

    def test_qml_open_argv(self):
        mod = self._load()
        buf = io.StringIO()
        with (
            mock.patch("arcade.hypr.hyprctl", side_effect=self._fake_hyprctl),
            mock.patch.object(sys, "stdout", buf),
        ):
            code = mod.main(list(self.QML_OPEN))
        data = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data["namespace"], "matt-dance-arcade")
        self.assertTrue(data["active"])
        self.assertTrue(data["enabledDecorationBlur"])

    def test_qml_close_argv_restores_decoration(self):
        mod = self._load()
        buf = io.StringIO()
        with (
            mock.patch("arcade.hypr.hyprctl", side_effect=self._fake_hyprctl),
            mock.patch.object(sys, "stdout", buf),
        ):
            code = mod.main(list(self.QML_CLOSE))
        data = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(data["wanted"])
        self.assertFalse(data["active"])

    def test_subprocess_exact_qml_argv(self):
        """Spawn the same argv list Arcade.qml builds (python + apply --namespace)."""
        proc = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "arcade-hypr"), *self.QML_OPEN],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotIn("unrecognized arguments", proc.stderr)
        self.assertNotIn("usage:", proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["namespace"], "matt-dance-arcade")
        if data.get("wanted") and not data.get("active"):
            self.assertNotEqual(proc.returncode, 0)

    def test_parent_namespace_still_works(self):
        mod = self._load()
        buf = io.StringIO()
        with (
            mock.patch("arcade.hypr.hyprctl", side_effect=self._fake_hyprctl),
            mock.patch.object(sys, "stdout", buf),
        ):
            code = mod.main(["--namespace", "matt-dance-arcade", "status"])
        data = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data["namespace"], "matt-dance-arcade")


class TestOverlayHyprWiring(unittest.TestCase):
    def test_qml_logs_namespace_and_falls_back(self):
        qml = (ROOT / "Arcade.qml").read_text(encoding="utf-8")
        lua = (ROOT / "hypr" / "arcade.lua").read_text(encoding="utf-8")
        self.assertIn("function logLayerNamespace()", qml)
        self.assertIn("layer namespace=", qml)
        self.assertIn("bin/arcade-hypr", qml)
        self.assertIn("effectiveOpacity", qml)
        self.assertIn("blurUnavailable", qml)
        self.assertIn("property bool hyprBlurActive: false", qml)
        self.assertIn('root.hyprBlurActive = false', qml)
        self.assertIn("frost unavailable", qml)
        self.assertIn('"apply", "--namespace", root.layerNamespace', qml)
        self.assertIn("--restore-decoration", qml)
        self.assertIn("surfaceFormat.opaque: false", qml)
        self.assertIn("WlrLayershell.namespace: root.layerNamespace", qml)
        self.assertIn('readonly property string layerNamespace: "matt-dance-arcade"', qml)
        self.assertIn("blur on, match:namespace", lua)
        self.assertIn("hl.layer_rule", lua)
        self.assertIn("ignore_alpha", lua)
        self.assertIn('name = "matt-dance-arcade-blur"', lua)
        self.assertIn("match = { namespace = ARCADE_NS }", lua)
        hypr_py = (ROOT / "arcade" / "hypr.py").read_text(encoding="utf-8")
        self.assertNotIn('"layerrules"', hypr_py)
        self.assertNotIn("'layerrules'", hypr_py)
        menu = (ROOT / "QuickMenu.qml").read_text(encoding="utf-8")
        self.assertIn("surfaceFormat.opaque: false", menu)
        self.assertIn('WlrLayershell.namespace: "matt-dance-arcade-quickmenu"', menu)
