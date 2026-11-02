"""Apply and probe Hyprland layer blur for the Arcade overlay.

Omarchy themes often ship ``decoration.blur.enabled = false``. A layer
rule alone then does nothing. This helper:

- detects the Hyprland config parser: Lua (0.55+/Omarchy 4) rejects
  ``hyprctl keyword`` with *keyword can't work with non-legacy parsers.
  Use eval.* (exit 0 — a silent no-op)
- on Lua, uses ``hyprctl eval`` for ``hl.config`` (decoration blur) and
  ``hl.layer_rule`` (named overlay rule)
- on hyprlang, still uses ``hyprctl keyword``
- never trusts exit codes: only an ``ok`` response counts, and
  ``active`` is true only after ``getoption decoration:blur:enabled``
  reads true

Do **not** query ``hyprctl -j layerrules`` — unknown on 0.56.2.
``hyprctl layers`` may omit the overlay if this runs before the layer
maps; do not gate frost on ``matched``.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

NAMESPACE = "matt-dance-arcade"
RULE_NAME = "matt-dance-arcade-blur"
FALLBACK_OPACITY = 0.7

# Hyprlang / keyword form (legacy parser only).
_NEW_RULES_ON = (
    "blur on, ignore_alpha 0.2, xray off, match:namespace {ns}",
    "blur on, match:namespace {ns}",
    "ignore_alpha 0.2, match:namespace {ns}",
    "xray off, match:namespace {ns}",
)
_OLD_RULES_ON = (
    "blur, {ns}",
    "ignorealpha 0.2, {ns}",
)
_NEW_RULES_OFF = (
    "blur off, ignore_alpha 1, match:namespace {ns}",
    "blur off, match:namespace {ns}",
    "ignore_alpha 1, match:namespace {ns}",
)
_OLD_RULES_OFF = (
    "noblur, {ns}",
    "ignorealpha 1, {ns}",
)


def _run(args: list[str], timeout: float = 2.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def hyprctl(*args: str) -> tuple[int, str, str]:
    return _run(["hyprctl", *args])


def response_text(out: str, err: str) -> str:
    return ((out or "").strip() or (err or "").strip())


def response_is_ok(out: str, err: str) -> bool:
    return response_text(out, err).lower() == "ok"


def response_wants_eval(out: str, err: str) -> bool:
    blob = f"{out}\n{err}".lower()
    return "non-legacy" in blob or "use eval" in blob


def probe_uses_eval() -> bool:
    """True when ``hyprctl keyword`` is rejected by the Lua config parser."""
    _, out, err = hyprctl("keyword", "arcade-probe-nonlegacy")
    return response_wants_eval(out, err)


def _parse_option(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("int", "set", "data", "float"):
        if key in data:
            return data[key]
    return data


def decoration_blur_enabled() -> bool | None:
    code, out, _ = hyprctl("-j", "getoption", "decoration:blur:enabled")
    if code != 0:
        return None
    value = _parse_option(out)
    if value is None:
        return None
    return bool(int(value)) if not isinstance(value, bool) else value


def decoration_blur_size() -> int | None:
    code, out, _ = hyprctl("-j", "getoption", "decoration:blur:size")
    if code != 0:
        return None
    value = _parse_option(out)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def collect_namespaces(payload: Any) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ns = node.get("namespace")
            if isinstance(ns, str) and ns and ns not in found:
                found.append(ns)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def list_layer_namespaces() -> list[str]:
    code, out, _ = hyprctl("-j", "layers")
    if code != 0 or not out.strip():
        return []
    try:
        payload = json.loads(out)
    except ValueError:
        return []
    return collect_namespaces(payload)


def _lua_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def decoration_enabled_lua(enabled: bool) -> str:
    return f"hl.config({{decoration={{blur={{enabled={'true' if enabled else 'false'}}}}}}})"


def decoration_size_lua(size: int) -> str:
    return f"hl.config({{decoration={{blur={{size={int(size)}}}}}}})"


def layer_rule_lua(namespace: str, enabled: bool) -> str:
    ns = _lua_str(namespace)
    name = _lua_str(RULE_NAME)
    if enabled:
        return (
            f"hl.layer_rule({{name={name},match={{namespace={ns}}},"
            f"blur=true,ignore_alpha=0.2,xray=false}})"
        )
    return (
        f"local r=hl.layer_rule({{name={name},match={{namespace={ns}}},"
        f"blur=false,ignore_alpha=1,xray=false}});"
        f"if r and r.set_enabled then r:set_enabled(false) end"
    )


def eval_lua(expr: str) -> tuple[bool, str]:
    code, out, err = hyprctl("eval", expr)
    if response_is_ok(out, err):
        return True, "ok"
    return False, response_text(out, err) or f"exit {code}"


def keyword(args: list[str]) -> tuple[bool, str]:
    code, out, err = hyprctl("keyword", *args)
    if response_wants_eval(out, err):
        return False, response_text(out, err) or "keyword rejected (use eval)"
    if response_is_ok(out, err):
        return True, "ok"
    return False, response_text(out, err) or f"exit {code}"


def keyword_layerrule(rule: str) -> tuple[bool, str]:
    last = "keyword layerrule failed"
    for args in (
        ["layerrule", rule],
        [f"layerrule = {rule}"],
    ):
        ok, detail = keyword(args)
        if ok:
            return True, rule
        last = detail
        if response_wants_eval("", detail):
            return False, detail
    return False, last


def _extra_namespaces(live: list[str], primary: str) -> list[str]:
    extra: list[str] = []
    for ns in live:
        if primary in ns:
            continue
        if ns == "quickshell" or ns.startswith("quickshell"):
            extra.append(ns)
    return extra


class _Setter:
    def __init__(self) -> None:
        self.use_eval = probe_uses_eval()
        self.errors: list[str] = []
        self.applied: list[str] = []

    def apply(self, keyword_args: list[str], lua: str, label: str) -> bool:
        if not self.use_eval:
            ok, detail = keyword(keyword_args)
            if ok:
                self.applied.append(label)
                return True
            if response_wants_eval("", detail):
                self.use_eval = True
            else:
                self.errors.append(detail)
                return False
        ok, detail = eval_lua(lua)
        if ok:
            self.applied.append(lua)
            return True
        self.errors.append(detail)
        return False


def apply_layer_blur(
    enabled: bool,
    namespace: str = NAMESPACE,
    restore_decoration: bool = False,
) -> dict[str, Any]:
    ns = namespace or NAMESPACE
    live = list_layer_namespaces()
    targets = [ns]
    extras = _extra_namespaces(live, ns)
    if extras:
        targets.extend(extras)

    original = decoration_blur_enabled()
    size = decoration_blur_size()
    setter = _Setter()
    flipped = False

    if restore_decoration and not enabled:
        # QML only sends --restore-decoration when Arcade flipped blur on.
        setter.apply(
            ["decoration:blur:enabled", "false"],
            decoration_enabled_lua(False),
            "decoration:blur:enabled false",
        )

    if enabled and original is False:
        if setter.apply(
            ["decoration:blur:enabled", "true"],
            decoration_enabled_lua(True),
            "decoration:blur:enabled true",
        ):
            flipped = True

    if enabled and size == 0:
        setter.apply(
            ["decoration:blur:size", "8"],
            decoration_size_lua(8),
            "decoration:blur:size 8",
        )

    if setter.use_eval:
        for target in (ns,):
            lua = layer_rule_lua(target, enabled)
            ok, detail = eval_lua(lua)
            if ok:
                setter.applied.append(lua)
            else:
                setter.errors.append(detail)
    else:
        templates = (_NEW_RULES_ON + _OLD_RULES_ON) if enabled else (_NEW_RULES_OFF + _OLD_RULES_OFF)
        for target in targets:
            for tmpl in templates:
                rule = tmpl.format(ns=target)
                ok, detail = keyword_layerrule(rule)
                if ok:
                    setter.applied.append(rule)
                elif response_wants_eval("", detail):
                    setter.use_eval = True
                    lua = layer_rule_lua(ns, enabled)
                    ev_ok, ev_detail = eval_lua(lua)
                    if ev_ok:
                        setter.applied.append(lua)
                    else:
                        setter.errors.append(ev_detail)
                    break
                elif detail:
                    setter.errors.append(detail)
            if setter.use_eval:
                break

    # Never trust keyword/eval exit codes. Frost is live only if getoption
    # says decoration blur is on. Do not require matched[] — layers often
    # omit the overlay if this runs before the surface maps.
    decoration = decoration_blur_enabled()
    if enabled and flipped and decoration is not True:
        flipped = False
        setter.errors.append("decoration:blur:enabled is not true after apply")
    elif enabled and decoration is not True:
        setter.errors.append("decoration:blur:enabled is not true after apply")

    live_after = list_layer_namespaces() or live
    matched = [item for item in live_after if any(t in item for t in targets)]
    active = bool(enabled and decoration is True)

    return {
        "ok": (not enabled) or active,
        "wanted": enabled,
        "active": active,
        "parser": "eval" if setter.use_eval else "keyword",
        "namespace": ns,
        "targets": targets,
        "namespaces": live_after,
        "matched": matched,
        "applied": setter.applied,
        "decorationBlur": decoration,
        "decorationWas": original,
        "enabledDecorationBlur": flipped,
        "fallbackOpacity": FALLBACK_OPACITY,
        "errors": setter.errors[:8],
    }
