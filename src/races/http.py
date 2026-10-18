"""Polite HTTP: identify ourselves, obey robots.txt, rate-limit per host, cache raw responses."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from protego import Protego

USER_AGENT = "races.sanch.pet/0.1 (+https://races.sanch.pet)"
ROBOTS_AGENT = "races.sanch.pet"
DEFAULT_DELAY_S = 2.0
CACHE_TTL_S = 20 * 3600
RETRIES = 2
RETRY_BACKOFF_S = 10.0

log = logging.getLogger(__name__)


class RobotsDisallowed(RuntimeError):
    pass


class PoliteClient:
    def __init__(
        self,
        cache_dir: Path | None = Path(".cache/raw"),
        ttl_s: float = CACHE_TTL_S,
        min_delay_s: float = DEFAULT_DELAY_S,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.ttl_s = ttl_s
        self.min_delay_s = min_delay_s
        self._http = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=timeout_s,
            follow_redirects=True,
            transport=transport,
        )
        self._robots: dict[str, Protego | None] = {}
        self._last_hit: dict[str, float] = {}

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _origin(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    def _robots_for(self, origin: str) -> Protego | None:
        if origin not in self._robots:
            try:
                resp = self._http.get(f"{origin}/robots.txt")
                self._last_hit[origin] = time.monotonic()
            except httpx.HTTPError as exc:
                # Unreachable robots.txt: refuse rather than guess.
                raise RobotsDisallowed(f"{origin}/robots.txt unreachable: {exc}") from exc
            if resp.status_code >= 500:
                raise RobotsDisallowed(f"{origin}/robots.txt returned {resp.status_code}")
            # 4xx means no robots.txt: everything is allowed (RFC 9309).
            self._robots[origin] = Protego.parse(resp.text) if resp.status_code < 400 else None
        return self._robots[origin]

    def _wait(self, origin: str, robots: Protego | None) -> None:
        delay = self.min_delay_s
        if robots is not None:
            delay = max(delay, robots.crawl_delay(ROBOTS_AGENT) or 0)
        elapsed = time.monotonic() - self._last_hit.get(origin, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_hit[origin] = time.monotonic()

    def _get_with_retry(self, url: str, origin: str, robots: Protego | None) -> str:
        for attempt in range(RETRIES + 1):
            self._wait(origin, robots)
            log.info("GET %s", url)
            try:
                resp = self._http.get(url)
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()
                    return resp.text
                error: Exception = httpx.HTTPStatusError(
                    f"{resp.status_code} for {url}", request=resp.request, response=resp
                )
            except httpx.TransportError as exc:
                error = exc
            if attempt == RETRIES:
                raise error
            log.warning("retrying %s after: %s", url, error)
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))
        raise AssertionError("unreachable")

    def _cache_path(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        host = urlsplit(url).netloc
        return self.cache_dir / host / (hashlib.sha1(url.encode()).hexdigest() + ".txt")

    def get_text(self, url: str) -> str:
        cached = self._cache_path(url)
        if cached and cached.exists() and time.time() - cached.stat().st_mtime < self.ttl_s:
            return cached.read_text(encoding="utf-8")

        origin = self._origin(url)
        robots = self._robots_for(origin)
        if robots is not None and not robots.can_fetch(url, ROBOTS_AGENT):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        text = self._get_with_retry(url, origin, robots)
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(text, encoding="utf-8")
        return text
