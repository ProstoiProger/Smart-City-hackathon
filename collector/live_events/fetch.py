"""Polite page fetcher: honours robots.txt, waits between requests to one host, identifies itself."""

import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import httpx

USER_AGENT = "AstanaWalkBot/1.0 (hackathon prototype; low request rate; contact: project repository)"
DEFAULT_DELAY_S = 1.5
TIMEOUT_S = 20
MAX_BYTES = 3_000_000


class FetchError(Exception):
    pass


@dataclass
class Page:
    url: str
    text: str
    fetched_at: float


class PoliteFetcher:
    def __init__(self, delay_s=DEFAULT_DELAY_S, client=None):
        self.delay_s = delay_s
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,kk;q=0.8,en;q=0.5"},
            timeout=TIMEOUT_S,
            follow_redirects=True,
        )
        self._last = {}
        self._robots = {}

    def allowed(self, url):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = RobotFileParser()
            try:
                response = self.client.get(origin + "/robots.txt")
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                else:
                    parser.parse([])
            except httpx.HTTPError:
                # No readable robots.txt means no stated limits, but the page fetch will still fail loudly.
                parser.parse([])
            self._robots[origin] = parser
        return self._robots[origin].can_fetch(USER_AGENT, url)

    def get(self, url):
        if not self.allowed(url):
            raise FetchError(f"robots.txt disallows {url}")
        host = urlsplit(url).netloc
        wait = self._last.get(host, 0) + self.delay_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.client.get(url)
        except httpx.HTTPError as e:
            raise FetchError(f"{url}: {e.__class__.__name__}") from e
        finally:
            self._last[host] = time.monotonic()
        if response.status_code != 200:
            raise FetchError(f"{url}: HTTP {response.status_code}")
        if len(response.content) > MAX_BYTES:
            raise FetchError(f"{url}: page too large")
        return Page(str(response.url), response.text, time.time())
