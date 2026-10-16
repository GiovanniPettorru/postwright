"""Types and helpers shared by every source."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

import httpx
from defusedxml.ElementTree import fromstring as xml_fromstring

if TYPE_CHECKING:
    from ..config import Settings

UA = "Mozilla/5.0 (compatible; postwright/1.0)"
MAX_FEED_BYTES = 5_000_000  # refuse to parse absurdly large documents


@dataclass
class RawPost:
    source: str
    title: str
    text: str = ""
    url: str = ""
    published_at: datetime | None = None
    key: str = ""  # alternative dedup key, used when the URL is not stable

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}|{self.key or self.url or self.title}".encode()).hexdigest()[:16]


class Source:
    """Interface of a source. See _template.py to create a new one."""

    name = "base"

    def __init__(self, settings: "Settings"):
        self.s = settings
        # Per-item failures a source handles internally (one dead feed out of ten).
        # fetch_all() merges these into FetchResult.failed so they reach the digest.
        self.failures: list[str] = []

    @classmethod
    def enabled(cls, settings: "Settings") -> bool:
        return True

    async def fetch(self) -> list[RawPost]:
        raise NotImplementedError


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean_text(s: str | None, limit: int = 500) -> str:
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:limit]


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def feed_text(r: httpx.Response) -> str:
    """Body of a feed response, refusing anything implausibly large."""
    if len(r.content) > MAX_FEED_BYTES:
        raise ValueError(f"feed too large ({len(r.content)} bytes)")
    return r.text


def parse_feed(xml_text: str, source: str, limit: int = 15) -> list[RawPost]:
    """Minimal RSS 2.0 / Atom parser. defusedxml refuses entity-expansion bombs."""
    root = xml_fromstring(xml_text)
    out: list[RawPost] = []
    for el in root.iter():
        if local_tag(el.tag) not in ("item", "entry"):
            continue
        f: dict[str, str] = {}
        link = ""
        for c in el:
            name = local_tag(c.tag)
            if name == "link" and not link:
                link = (c.text or "").strip() or c.get("href", "")
            elif name not in f:
                f[name] = (c.text or "").strip()
        title = clean_text(f.get("title"), 300)
        if not title:
            continue
        publisher = f.get("source", "")
        out.append(
            RawPost(
                source=f"{source} ({publisher})" if publisher else source,
                title=title,
                text=clean_text(f.get("description") or f.get("summary") or f.get("content")),
                url=link,
                published_at=parse_date(f.get("pubDate") or f.get("published") or f.get("updated")),
            )
        )
        if len(out) >= limit:
            break
    return out


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": UA})
