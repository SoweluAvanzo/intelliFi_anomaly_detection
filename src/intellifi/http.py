"""Minimal HTTP helper with exponential backoff on 429 and 5xx.

The notebook used a one-liner; in the package we want a single shared session
(connection pooling), a structured User-Agent (some Polymarket-adjacent
endpoints reject blank UAs), and explicit backoff on the codes the spec calls
out (§v1 §10.1, §v2 reliability conventions).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from . import config

log = logging.getLogger(__name__)

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": config.USER_AGENT, "Accept": "application/json"})
        _session = s
    return _session


class HTTPError(RuntimeError):
    """Raised when retries are exhausted."""


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    """GET ``url`` and parse JSON, retrying on 429/5xx with exponential backoff.

    Raises ``HTTPError`` after ``config.HTTP_RETRIES`` failed attempts. Raises
    ``requests.HTTPError`` for non-retryable 4xx responses.
    """
    last_exc: Exception | None = None
    for attempt in range(config.HTTP_RETRIES):
        try:
            r = session().get(url, params=params, timeout=config.HTTP_TIMEOUT)
        except requests.RequestException as exc:
            last_exc = exc
            wait = config.HTTP_BACKOFF_BASE**attempt
            log.warning("transport error on %s (attempt %d/%d): %s — sleeping %.1fs",
                        url, attempt + 1, config.HTTP_RETRIES, exc, wait)
            time.sleep(wait)
            continue

        if r.status_code in (429, 500, 502, 503, 504):
            wait = config.HTTP_BACKOFF_BASE**attempt
            log.warning("HTTP %d on %s (attempt %d/%d) — sleeping %.1fs",
                        r.status_code, url, attempt + 1, config.HTTP_RETRIES, wait)
            time.sleep(wait)
            continue

        r.raise_for_status()
        return r.json()

    raise HTTPError(f"giving up on {url} after {config.HTTP_RETRIES} attempts") from last_exc
