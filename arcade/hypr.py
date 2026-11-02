"""Apply and probe Hyprland layer blur for the Arcade overlay.

Omarchy themes often ship ``decoration.blur.enabled = false``. A layer
rule alone then does nothing. This helper:

- applies 0.53+ ``match:namespace`` rules and the older ``blur, ns`` form
- turns decoration blur on while Arcade is open if it was off
- reports the live ``hyprctl layers`` namespaces so QML can log them
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

NAMESPACE = "matt-dance-arcade"
FALLBACK_OPACITY = 0.7

_NEW_RULES_ON = (
    "blur on, match:namespace {ns}",
    "ignore_alpha 0.2, match:namespace {ns}",
    "xray off, match:namespace {ns}",
)
_OLD_RULES_ON = (
    "blur, {ns}",
    "ignorealpha 0.2, {ns}",
)
_NEW_RULES_OFF = (
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


def keyword_layerrule(rule: str) -> tuple[bool, str]:
    # Prefer `hyprctl keyword layerrule VALUE`. Some builds want `=`.
    for args in (
        ["keyword", "layerrule", rule],
        ["keyword", f"layerrule = {rule}"],
    ):
        code, out, err = hyprctl(*args)
        if code == 0:
            return True, rule
        last = (err or out or f"exit {code}").strip()
    return False, last


def _extra_namespaces(live: list[str], primary: str) -> list[str]:
    extra: list[str] = []
    for ns in live:
        if primary in ns:
            continue
        if ns == "quickshell" or ns.startswith("quickshell"):
            extra.append(ns)
    return extra


def apply_layer_blur(
    enabled: bool,
    namespace: str = NAMESPACE,
    restore_decoration: bool = False,
) -> dict[str, Any]:
    ns = namespace or NAMESPACE
    live = list_layer_namespaces()
    targets = [ns]
    if not any(ns in item for item in live):
        targets.extend(_extra_namespaces(live, ns))

    decoration = decoration_blur_enabled()
    size = decoration_blur_size()
    flipped = False
    errors: list[str] = []
    applied: list[str] = []

    if restore_decoration and not enabled:
        code, out, err = hyprctl("keyword", "decoration:blur:enabled", "false")
        if code == 0:
            decoration = False
        elif (err or out).strip():
            errors.append((err or out).strip())

    if enabled and decoration is False:
        code, out, err = hyprctl("keyword", "decoration:blur:enabled", "true")
        if code == 0:
            flipped = True
            decoration = True
        else:
            errors.append((err or out or "could not enable decoration:blur").strip())

    if enabled and size == 0:
        code, _, err = hyprctl("keyword", "decoration:blur:size", "8")
        if code != 0 and err.strip():
            errors.append(err.strip())

    templates = (_NEW_RULES_ON + _OLD_RULES_ON) if enabled else (_NEW_RULES_OFF + _OLD_RULES_OFF)
    ok_any = False
    for target in targets:
        for tmpl in templates:
            rule = tmpl.format(ns=target)
            ok, detail = keyword_layerrule(rule)
            if ok:
                ok_any = True
                applied.append(rule)
            elif detail:
                errors.append(detail)

    live_after = list_layer_namespaces() or live
    matched = [item for item in live_after if any(t in item for t in targets)]
    active = bool(enabled and decoration is not False and ok_any)

    return {
        "ok": ok_any or not enabled,
        "wanted": enabled,
        "active": active,
        "namespace": ns,
        "targets": targets,
        "namespaces": live_after,
        "matched": matched,
        "applied": applied,
        "decorationBlur": decoration,
        "enabledDecorationBlur": flipped,
        "fallbackOpacity": FALLBACK_OPACITY,
        "errors": errors[:8],
    }
