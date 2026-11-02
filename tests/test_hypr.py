"""Hyprland layer-blur helper — parse and apply without a live compositor."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

from arcade.hypr import (
    FALLBACK_OPACITY,
    NAMESPACE,
    apply_layer_blur,
    collect_namespaces,
    orig_path,
    parse_getoption,
    restore_if_saved,
)

ROOT = Path(__file__).resolve().parent.parent

LAYERS = {
    "HDMI-A-1": {
        "levels": {
            "2": [{"namespace": "omarchy-bar", "w": 1920, "h": 36}],
            "3": [{"namespace": "matt-dance-arcade", "w": 1920, "h": 1080}],
        }
    }
}

EARLY_LAYERS = {
    "HDMI-A-1": {
        "levels": {
            "0": [{"namespace": "omarchy-background", "w": 1920, "h": 1080}],
            "2": [{"namespace": "omarchy-bar", "w": 1920, "h": 36}],
        }
    }
}

NONLEGACY = "keyword can't work with non-legacy parsers. Use eval."


class FakeHypr:
    """Stateful hyprctl stand-in. ``parser='eval'`` is Hyprland 0.56 Lua."""

    def __init__(
        self,
        *,
        parser: str = "keyword",
        blur: int = 0,
        size: int = 8,
        layers: dict | None = None,
        eval_ok: bool = True,
        getoption_text: str | None = None,
        getoption_json: str | None = None,
    ):
        self.parser = parser
        self.blur = blur
        self.size = size
        self.layers = layers if layers is not None else LAYERS
        self.eval_ok = eval_ok
        self.getoption_text = getoption_text
        self.getoption_json = getoption_json
        self.calls: list[tuple[str, ...]] = []

    def _enabled_json(self) -> str:
        if self.getoption_json is not None:
            return self.getoption_json
        return json.dumps({"int": int(self.blur), "set": True})

    def _enabled_text(self) -> str:
        if self.getoption_text is not None:
            return self.getoption_text
        return f"bool: {'true' if self.blur else 'false'}\nset: true"

    def __call__(self, *args: str):
        self.calls.append(args)
        if args[:3] == ("-j", "getoption", "decoration:blur:enabled"):
            return 0, self._enabled_json(), ""
        if args[:2] == ("getoption", "decoration:blur:enabled"):
            return 0, self._enabled_text(), ""
        if args[:3] == ("-j", "getoption", "decoration:blur:size"):
            return 0, json.dumps({"int": int(self.size)}), ""
        if args[:2] == ("getoption", "decoration:blur:size"):
            return 0, f"int: {int(self.size)}\nset: true", ""
        if args[:2] == ("-j", "layers"):
            return 0, json.dumps(self.layers), ""
        if args[0] == "keyword":
            if self.parser == "eval":
                return 0, NONLEGACY, ""
            if args[1:3] == ("decoration:blur:enabled", "true"):
                self.blur = 1
                return 0, "ok", ""
            if args[1:3] == ("decoration:blur:enabled", "false"):
                self.blur = 0
                return 0, "ok", ""
            if args[1] == "decoration:blur:size":
                self.size = int(args[2])
                return 0, "ok", ""
            return 0, "ok", ""
        if args[0] == "eval":
            if not self.eval_ok:
                return 0, "nope", ""
            expr = args[1] if len(args) > 1 else ""
            compact = expr.replace(" ", "")
            if "enabled=true" in compact:
                self.blur = 1
            if "enabled=false" in compact:
                self.blur = 0
            if "size=" in compact:
                self.size = 8
            return 0, "ok", ""
        return 1, "", "unknown"


class TestCollectNamespaces(unittest.TestCase):
    def test_walks_hyprctl_layers_json(self):
        self.assertEqual(
            collect_namespaces(LAYERS),
            ["omarchy-bar", "matt-dance-arcade"],
        )

    def test_empty(self):
        self.assertEqual(collect_namespaces({}), [])
        self.assertEqual(collect_namespaces(None), [])


class TestParseGetoption(unittest.TestCase):
    def test_plain_bool_false_set_true_is_false(self):
        self.assertIs(parse_getoption("bool: false\nset: true"), False)

    def test_plain_bool_true_set_true_is_true(self):
        self.assertIs(parse_getoption("bool: true\nset: true"), True)

    def test_json_bool_false_set_true_is_false(self):
        self.assertIs(parse_getoption('{"bool": false, "set": true}'), False)

    def test_json_int_zero_set_true_is_false(self):
        self.assertIs(parse_getoption('{"int": 0, "set": true}'), False)

    def test_json_set_true_alone_is_not_enabled(self):
        self.assertIsNone(parse_getoption('{"set": true}'))


class IsolatedRuntime:
    def setUp(self):
        self._runtime = tempfile.TemporaryDirectory()
        self.addCleanup(self._runtime.cleanup)
        env = mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self._runtime.name})
        env.start()
        self.addCleanup(env.stop)


class TestApplyLayerBlur(IsolatedRuntime, unittest.TestCase):
    def test_applies_new_and_old_syntax_and_enables_decoration(self):
        fake = FakeHypr(parser="keyword", blur=0)

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            result = apply_layer_blur(True, namespace=NAMESPACE)

        self.assertEqual(result["parser"], "keyword")
        self.assertTrue(result["enabledDecorationBlur"])
        self.assertTrue(result["decorationBlur"])
        self.assertTrue(result["active"])
        self.assertIn("matt-dance-arcade", result["matched"])
        self.assertTrue(any("blur on, match:namespace" in r for r in result["applied"]))
        self.assertTrue(any(r.startswith("blur, ") for r in result["applied"]))
        self.assertEqual(result["fallbackOpacity"], 0.7)
        self.assertIn(("keyword", "decoration:blur:enabled", "true"), fake.calls)

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
        fake = FakeHypr(parser="keyword", blur=1)

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            result = apply_layer_blur(False, namespace=NAMESPACE, restore_decoration=True)

        self.assertTrue(result["ok"])
        self.assertFalse(result["wanted"])
        self.assertFalse(result["active"])
        self.assertEqual(fake.blur, 0)
        self.assertIn(("keyword", "decoration:blur:enabled", "false"), fake.calls)
        self.assertTrue(any("blur off" in r for r in result["applied"]))

    def test_nonlegacy_keyword_is_not_success(self):
        """0.56.2: keyword exits 0 with 'Use eval' and getoption stays false."""
        fake = FakeHypr(parser="eval", blur=0, eval_ok=False)

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            result = apply_layer_blur(True, namespace=NAMESPACE)

        self.assertEqual(result["parser"], "eval")
        self.assertFalse(result["active"])
        self.assertFalse(result["decorationBlur"])
        self.assertFalse(result["ok"])
        self.assertGreaterEqual(result["fallbackOpacity"], FALLBACK_OPACITY)
        self.assertTrue(result["errors"])
        self.assertFalse(any("blur on" in r for r in result["applied"]))

    def test_eval_path_enables_decoration_and_layer_rule(self):
        fake = FakeHypr(parser="eval", blur=0)

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            result = apply_layer_blur(True, namespace=NAMESPACE)

        self.assertEqual(result["parser"], "eval")
        self.assertTrue(result["active"])
        self.assertTrue(result["decorationBlur"])
        self.assertTrue(result["enabledDecorationBlur"])
        self.assertTrue(any("hl.config" in r and "enabled=true" in r for r in result["applied"]))
        self.assertTrue(any("hl.layer_rule" in r and "blur=true" in r for r in result["applied"]))
        self.assertTrue(any(c[0] == "eval" for c in fake.calls))
        self.assertEqual(fake.blur, 1)

    def test_eval_restore_on_close(self):
        fake = FakeHypr(parser="eval", blur=1)

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            result = apply_layer_blur(False, namespace=NAMESPACE, restore_decoration=True)

        self.assertFalse(result["wanted"])
        self.assertFalse(result["active"])
        self.assertEqual(fake.blur, 0)
        self.assertTrue(any("enabled=false" in r for r in result["applied"]))
        self.assertTrue(any("blur=false" in r or "set_enabled" in r for r in result["applied"]))

    def test_open_then_close_restores_original_false(self):
        """Hardware: before open bool false; after close it must be false again."""
        fake = FakeHypr(parser="eval", blur=0)

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            opened = apply_layer_blur(True, namespace=NAMESPACE)

        self.assertTrue(opened["active"])
        self.assertEqual(fake.blur, 1)
        self.assertEqual(orig_path().read_text(encoding="utf-8").strip(), "false")
        self.assertFalse(opened["decorationOrig"])

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            # Close without --restore-decoration: the saved orig must be enough.
            closed = apply_layer_blur(False, namespace=NAMESPACE)

        self.assertFalse(closed["wanted"])
        self.assertFalse(closed["active"])
        self.assertFalse(closed["decorationBlur"])
        self.assertEqual(fake.blur, 0)
        self.assertTrue(any("enabled=false" in r for r in closed["applied"]))
        self.assertFalse(orig_path().exists())

    def test_restore_if_saved_noop_without_file(self):
        fake = FakeHypr(parser="eval", blur=1)
        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            self.assertIsNone(restore_if_saved())
        self.assertEqual(fake.blur, 1)

    def test_plain_bool_false_set_true_is_inactive(self):
        fake = FakeHypr(
            parser="eval",
            blur=0,
            getoption_text="bool: false\nset: true",
            getoption_json='{"bool": false, "set": true}',
        )

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            result = apply_layer_blur(True, namespace=NAMESPACE)

        self.assertFalse(result["active"])
        self.assertFalse(result["decorationBlur"])
        self.assertEqual(result["getoptionRaw"], "bool: false\nset: true")
        self.assertGreaterEqual(result["fallbackOpacity"], FALLBACK_OPACITY)
        self.assertTrue(any("enabled=true" in r for r in result["applied"]))

    def test_active_does_not_require_matched_layers(self):
        fake = FakeHypr(parser="eval", blur=0, layers=EARLY_LAYERS)

        with mock.patch("arcade.hypr.hyprctl", side_effect=fake):
            result = apply_layer_blur(True, namespace=NAMESPACE)

        self.assertEqual(result["namespaces"], ["omarchy-background", "omarchy-bar"])
        self.assertEqual(result["matched"], [])
        self.assertTrue(result["active"])
        self.assertTrue(result["decorationBlur"])


class TestArcadeHyprCli(IsolatedRuntime, unittest.TestCase):
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

    def test_qml_open_argv(self):
        mod = self._load()
        fake = FakeHypr(parser="eval", blur=0)
        buf = io.StringIO()
        with (
            mock.patch("arcade.hypr.hyprctl", side_effect=fake),
            mock.patch.object(sys, "stdout", buf),
        ):
            code = mod.main(list(self.QML_OPEN))
        data = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data["namespace"], "matt-dance-arcade")
        self.assertTrue(data["active"])
        self.assertTrue(data["enabledDecorationBlur"])
        self.assertEqual(data["parser"], "eval")

    def test_qml_close_argv_restores_decoration(self):
        mod = self._load()
        fake = FakeHypr(parser="eval", blur=1)
        buf = io.StringIO()
        with (
            mock.patch("arcade.hypr.hyprctl", side_effect=fake),
            mock.patch.object(sys, "stdout", buf),
        ):
            code = mod.main(list(self.QML_CLOSE))
        data = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(data["wanted"])
        self.assertFalse(data["active"])
        self.assertEqual(fake.blur, 0)

    def test_nonlegacy_cli_exits_nonzero_so_fallback_applies(self):
        mod = self._load()
        fake = FakeHypr(parser="eval", blur=0, eval_ok=False)
        buf = io.StringIO()
        with (
            mock.patch("arcade.hypr.hyprctl", side_effect=fake),
            mock.patch.object(sys, "stdout", buf),
        ):
            code = mod.main(list(self.QML_OPEN))
        data = json.loads(buf.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(data["active"])
        self.assertGreaterEqual(data["fallbackOpacity"], FALLBACK_OPACITY)

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
        fake = FakeHypr()
        buf = io.StringIO()
        with (
            mock.patch("arcade.hypr.hyprctl", side_effect=fake),
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
        self.assertIn("root.hyprBlurActive = false", qml)
        self.assertIn("frost unavailable", qml)
        self.assertIn("function scheduleLayerBlur()", qml)
        self.assertIn("hyprBlurPending", qml)
        self.assertIn("getoptionRaw", qml)
        self.assertIn('"apply", "--namespace", root.layerNamespace', qml)
        self.assertIn('args.push("--restore-decoration")', qml)
        self.assertNotIn("if (root.hyprEnabledDecoration)", qml)
        service = (ROOT / "Service.qml").read_text(encoding="utf-8")
        self.assertIn("Component.onDestruction", service)
        self.assertIn("apply", service)
        self.assertIn("--off", service)
        daemon = (ROOT / "arcade" / "daemon.py").read_text(encoding="utf-8")
        self.assertIn("restore_if_saved", daemon)
        self.assertIn("surfaceFormat.opaque: false", qml)
        self.assertIn("WlrLayershell.namespace: root.layerNamespace", qml)
        self.assertIn('readonly property string layerNamespace: "matt-dance-arcade"', qml)
        self.assertIn("blur on, match:namespace", lua)
        self.assertIn("hl.layer_rule", lua)
        self.assertIn("ignore_alpha", lua)
        self.assertIn('name = "matt-dance-arcade-blur"', lua)
        self.assertIn("match = { namespace = ARCADE_NS }", lua)
        self.assertIn("hyprctl eval", lua)
        hypr_py = (ROOT / "arcade" / "hypr.py").read_text(encoding="utf-8")
        self.assertNotIn('"layerrules"', hypr_py)
        self.assertNotIn("'layerrules'", hypr_py)
        self.assertIn("hl.config", hypr_py)
        self.assertIn("non-legacy", hypr_py)
        self.assertIn("probe_uses_eval", hypr_py)
        self.assertIn("parse_getoption", hypr_py)
        self.assertIn("Never treat", hypr_py)
        self.assertIn("blur-orig", hypr_py)
        self.assertIn("restore_if_saved", hypr_py)
        menu = (ROOT / "QuickMenu.qml").read_text(encoding="utf-8")
        self.assertIn("surfaceFormat.opaque: false", menu)
        self.assertIn('WlrLayershell.namespace: "matt-dance-arcade-quickmenu"', menu)
