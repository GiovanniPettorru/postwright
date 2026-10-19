"""Google Trends (RSS) and Google News (RSS with localized queries). No API key required."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx

from .base import RawPost, Source, feed_text, http_client, local_tag, parse_feed, xml_fromstring

log = logging.getLogger("sources")


class GoogleTrendsSource(Source):
    name = "Google Trends"

    async def fetch(self) -> list[RawPost]:
        geo = self.s.google_trends_geo
        async with http_client() as c:
            r = await c.get(f"https://trends.google.com/trending/rss?geo={geo}")
            r.raise_for_status()
        root = xml_fromstring(feed_text(r))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = []
        for item in root.iter("item"):
            title, traffic, news = "", "", []
            for ch in item:
                n = local_tag(ch.tag)
                if n == "title":
                    title = (ch.text or "").strip()
                elif n == "approx_traffic":
                    traffic = (ch.text or "").strip()
                elif n == "news_item":
                    news.append({local_tag(x.tag): (x.text or "").strip() for x in ch})
            if not title:
                continue
            headlines = "; ".join(n.get("news_item_title", "") for n in news[:3])
            out.append(
                RawPost(
                    source=f"Google Trends {geo}",
                    title=f"Search trend: {title}",
                    text=f"Estimated searches: {traffic}. Related headlines: {headlines}",
                    url=(news[0].get("news_item_url") if news else "") or f"https://trends.google.com/trending?geo={geo}",
                    published_at=datetime.now(timezone.utc),
                    key=f"{title.lower()}|{today}",  # one alert per trend per day
                )
            )
        return out


class GoogleNewsSource(Source):
    name = "Google News"

    async def _one(self, c: httpx.AsyncClient, q: str) -> list[RawPost]:
        geo = self.s.google_trends_geo
        lang = self.s.news_language
        url = (
            f"https://news.google.com/rss/search?q={quote_plus(q + ' when:1d')}"
            f"&hl={lang}&gl={geo}&ceid={geo}:{lang}"
        )
        r = await c.get(url)
        r.raise_for_status()
        return parse_feed(feed_text(r), f"Google News [{q}]", limit=8)

    async def fetch(self) -> list[RawPost]:
        queries = self.s.news_queries
        self.failures = []
        async with http_client() as c:
            res = await asyncio.gather(*(self._one(c, q) for q in queries), return_exceptions=True)
        out: list[RawPost] = []
        seen: set[str] = set()
        for q, r in zip(queries, res):
            if isinstance(r, Exception):
                log.warning("Google News '%s' failed: %s", q, r)
                self.failures.append(f"Google News [{q}]")
                continue
            # The same article often matches more than one query. Its id is built from
            # the source label, which contains the query, so fetch_all() cannot dedupe it.
            for post in r:
                key = post.url or post.title
                if key not in seen:
                    seen.add(key)
                    out.append(post)
        return out
