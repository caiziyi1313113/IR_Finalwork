from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

from app.config import CrawlSettings


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes


class HostRateLimiter:
    def __init__(self, settings: CrawlSettings):
        self.settings = settings
        self.host_locks = defaultdict(lambda: asyncio.Semaphore(2))
        self.last_access: dict[str, float] = defaultdict(float)

    async def acquire(self, url: str) -> asyncio.Semaphore:
        host = urlparse(url).netloc
        semaphore = self.host_locks[host]
        await semaphore.acquire()
        elapsed = time.monotonic() - self.last_access[host]
        delay = self.settings.crawl_per_host_delay_seconds - elapsed
        if delay > 0:
            await asyncio.sleep(delay)
        return semaphore

    def release(self, url: str, semaphore: asyncio.Semaphore) -> None:
        host = urlparse(url).netloc
        self.last_access[host] = time.monotonic()
        semaphore.release()


class Fetcher:
    def __init__(self, settings: CrawlSettings):
        timeout = aiohttp.ClientTimeout(total=settings.crawl_timeout_seconds)
        headers = {"User-Agent": settings.crawl_user_agent}
        self.session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        self.rate_limiter = HostRateLimiter(settings)

    async def close(self) -> None:
        await self.session.close()

    async def fetch(self, url: str) -> FetchResult | None:
        limiter = await self.rate_limiter.acquire(url)
        try:
            async with self.session.get(url, allow_redirects=True) as response:
                if response.status >= 400:
                    return None
                body = await response.read()
                content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
                return FetchResult(
                    url=str(response.url),
                    status=response.status,
                    content_type=content_type,
                    body=body,
                )
        except aiohttp.ClientError:
            return None
        finally:
            self.rate_limiter.release(url, limiter)

