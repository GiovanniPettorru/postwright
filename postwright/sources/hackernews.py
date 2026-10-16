"""Hacker News (public Firebase API)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .base import RawPost, Source, http_client


class HackerNewsSource(Source):
    name = "Hacker News"

    @classmethod
    def enabled(cls, s) -> bool:
        return s.hn_enabled

    async def fetch(self) -> list[RawPost]:
        base = "https://hacker-news.firebaseio.com/v0"
        async with http_client() as c:
            top = await c.get(f"{base}/topstories.json")
            top.raise_for_status()
            ids = top.json()[:30]
            items = await asyncio.gather(*(c.get(f"{base}/item/{i}.json") for i in ids), return_exceptions=True)
        out = []
        for r in items:
            if isinstance(r, Exception):
                continue
            try:
                d = r.json() or {}
            except ValueError:  # an error page instead of JSON
                continue
            if not d.get("title"):
                continue
            out.append(
                RawPost(
                    source="Hacker News",
                    title=d["title"],
                    text=f"[points {d.get('score', 0)}, comments {d.get('descendants', 0)}]",
                    url=d.get("url") or f"https://news.ycombinator.com/item?id={d['id']}",
                    published_at=datetime.fromtimestamp(d.get("time", 0), tz=timezone.utc),
                    key=str(d["id"]),
                )
            )
        return out
