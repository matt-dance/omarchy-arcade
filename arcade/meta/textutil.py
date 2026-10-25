"""Shared text helpers for store / IGDB payloads."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

from ..model import normalize_title

_TAG = re.compile(r"<[^>]+>")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_WS = re.compile(r"\s+")


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = _TAG.sub(" ", str(value))
    text = html.unescape(text)
    return _WS.sub(" ", text).strip()


def parse_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
        if n > 10_000:
            try:
                return datetime.fromtimestamp(n, tz=timezone.utc).year
            except (OSError, OverflowError, ValueError):
                return None
        if 1970 <= n <= 2100:
            return n
        return None
    match = _YEAR.search(str(value))
    return int(match.group(1)) if match else None


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def best_title_match(title: str, names: list[str]) -> int | None:
    """Return the index of the best normalized-title match, or None."""
    want = normalize_title(title)
    if not want or not names:
        return None
    exact: list[int] = []
    contains: list[int] = []
    for i, name in enumerate(names):
        got = normalize_title(name)
        if not got:
            continue
        if got == want:
            exact.append(i)
        elif want in got or got in want:
            contains.append(i)
    if exact:
        return exact[0]
    if contains:
        return contains[0]
    return None
