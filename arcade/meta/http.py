"""Small urllib wrapper. Callers inject a fake in tests — no live net in CI."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

USER_AGENT = "OmarchyArcade/0.1 (+https://github.com/matt-dance/omarchy-arcade)"


class HttpError(Exception):
    """Network or HTTP failure. Message must never include secrets or query strings."""


def _safe_host(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc or "unknown"
        path = parsed.path or "/"
        return f"{host}{path}"
    except Exception:
        return "request"


def _headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    out = {"User-Agent": USER_AGENT}
    if extra:
        out.update(extra)
    return out


class HttpClient:
    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        req = urllib.request.Request(url, headers=_headers(headers), method="GET")
        return self._open(req, url)

    def post(
        self,
        url: str,
        data: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        req = urllib.request.Request(
            url, data=data, headers=_headers(headers), method="POST"
        )
        return self._open(req, url)

    def get_json(self, url: str, headers: Mapping[str, str] | None = None) -> Any:
        raw = self.get(url, headers)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HttpError(f"invalid JSON from {_safe_host(url)}") from exc

    def post_json(
        self,
        url: str,
        data: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        raw = self.post(url, data, headers)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HttpError(f"invalid JSON from {_safe_host(url)}") from exc

    def download(
        self,
        url: str,
        dest: Path,
        headers: Mapping[str, str] | None = None,
    ) -> bool:
        try:
            payload = self.get(url, headers)
        except HttpError:
            return False
        if not payload:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(payload)
        tmp.replace(dest)
        return True

    def _open(self, req: urllib.request.Request, url: str) -> bytes:
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise HttpError(f"HTTP {exc.code} from {_safe_host(url)}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise HttpError(f"request failed: {_safe_host(url)}") from None
