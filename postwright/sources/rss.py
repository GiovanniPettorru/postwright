"""Extra RSS/Atom feeds (newsletters, blogs, bridges to other social networks)."""
from __future__ import annotations

import asyncio
import logging
import re

from .base import RawPost, Source, feed_text, http_client, parse_feed

log = logging.getLogger("sources")


class RSSSource(Source):
    name = "RSS custom"

    @classmethod
    def enabled(cls, s) -> bool:
        return bool(s.rss_feeds)

    async def fetch(self) -> list[RawPost]:
        feeds = self.s.rss_feeds
        self.failures = []
        async with http_client() as c:
            res = await asyncio.gather(*(c.get(u) for u in feeds), return_exceptions=True)
        out: list[RawPost] = []
        for u, r in zip(feeds, res):
            host = re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
            try:
                if isinstance(r, Exception):
                    raise r
                r.raise_for_status()
                out += parse_feed(feed_text(r), f"RSS {host}")
            except Exception as e:  # noqa: BLE001
                log.warning("RSS %s failed: %s", u, e)
                self.failures.append(f"RSS {host}")
        return out
