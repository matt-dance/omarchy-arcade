"""ProtonDB summary API (Linux compatibility tier). No API key."""

from __future__ import annotations

from typing import Any

from .http import HttpClient, HttpError

SUMMARY_URL = "https://www.protondb.com/api/v1/reports/summaries/{appid}.json"

KNOWN_TIERS = ("platinum", "gold", "silver", "bronze", "borked", "pending")


def parse_summary(payload: Any, appid: int) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    tier = str(payload.get("tier") or "").strip().casefold()
    if not tier:
        return None
    best = str(payload.get("bestReportedTier") or tier).strip().casefold()
    try:
        total = int(payload.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    return {
        "steamAppId": int(appid),
        "tier": tier,
        "bestReportedTier": best,
        "trendingTier": str(payload.get("trendingTier") or "").strip().casefold() or None,
        "total": total,
    }


def fetch_summary(appid: int, http: HttpClient) -> dict[str, Any] | None:
    url = SUMMARY_URL.format(appid=int(appid))
    try:
        payload = http.get_json(url)
    except HttpError:
        return None
    return parse_summary(payload, int(appid))
