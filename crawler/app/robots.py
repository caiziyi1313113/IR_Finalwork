from __future__ import annotations

from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urlparse

import aiohttp


@dataclass
class CachedRobots:
    parser: robotparser.RobotFileParser | None
    missing: bool = False


class RobotsCache:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.cache: dict[str, CachedRobots] = {}

    async def allowed(self, url: str, session: aiohttp.ClientSession) -> bool:
        host = urlparse(url).netloc
        if host not in self.cache:
            self.cache[host] = await self._fetch_robots(host=host, session=session)

        entry = self.cache[host]
        if entry.missing:
            return True
        if entry.parser is None:
            return False
        return entry.parser.can_fetch(self.user_agent, url)

    async def _fetch_robots(self, host: str, session: aiohttp.ClientSession) -> CachedRobots:
        robots_url = f"https://{host}/robots.txt"
        try:
            async with session.get(robots_url) as response:
                if response.status == 404:
                    return CachedRobots(parser=None, missing=True)
                if response.status != 200:
                    return CachedRobots(parser=None, missing=False)
                content = await response.text(encoding="utf-8", errors="ignore")
        except aiohttp.ClientError:
            return CachedRobots(parser=None, missing=False)

        parser = robotparser.RobotFileParser()
        parser.parse(content.splitlines())
        return CachedRobots(parser=parser, missing=False)

