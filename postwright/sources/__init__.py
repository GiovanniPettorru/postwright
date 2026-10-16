"""Source registry and parallel collection.

To add a source: see _template.py and add the class to SOURCES.
LinkedIn, Instagram and Facebook expose no API for reading feeds or trends, and scraping them
violates their terms of service: to include them, use RSS_FEEDS with a service whose terms you accept.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import zip_longest

from .base import RawPost, Source
from .google import GoogleNewsSource, GoogleTrendsSource
from .hackernews import HackerNewsSource
from .reddit import RedditSource
from .rss import RSSSource
from .x import XSource

log = logging.getLogger("sources")

SOURCES: list[type[Source]] = [
    GoogleTrendsSource,
    GoogleNewsSource,
    RedditSource,
    HackerNewsSource,
    XSource,
    RSSSource,
    # ---- Room for new sources ----
]


@dataclass
class FetchResult:
    posts: list[RawPost]
    counts: dict[str, int] = field(default_factory=dict)  # posts retrieved per source
    failed: list[str] = field(default_factory=list)       # unreachable sources


def build_sources(settings) -> list[Source]:
    return [cls(settings) for cls in SOURCES if cls.enabled(settings)]


async def fetch_all(settings) -> FetchResult:
    sources = build_sources(settings)
    results = await asyncio.gather(*(x.fetch() for x in sources), return_exceptions=True)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.max_post_age_hours)
    buckets: list[list[RawPost]] = []
    counts: dict[str, int] = {}
    failed: list[str] = []
    for src, res in zip(sources, results):
        if isinstance(res, Exception):
            log.warning("Source %s failed: %s", src.name, res)
            failed.append(src.name)
            continue
        log.info("Source %s: %d posts", src.name, len(res))
        counts[src.name] = len(res)
        failed.extend(src.failures)  # per-item failures the source handled internally
        buckets.append([p for p in res if not (p.published_at and p.published_at < cutoff)])

    # Round-robin across sources instead of concatenating them: the scanner later truncates to
    # MAX_NEW_POSTS_PER_SCAN, and a plain concatenation would always sacrifice the last sources
    # in SOURCES order - which are the paid and the hand-curated ones.
    posts: dict[str, RawPost] = {}
    for group in zip_longest(*buckets):
        for p in group:
            if p is not None:
                posts.setdefault(p.id, p)
    return FetchResult(list(posts.values()), counts, failed)


__all__ = ["RawPost", "Source", "SOURCES", "FetchResult", "build_sources", "fetch_all"]
