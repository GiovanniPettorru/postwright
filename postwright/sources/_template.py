"""TEMPLATE for a new source. Copy this file (e.g. sources/mastodon.py), then:

  1. rename the class and set `name`;
  2. in `enabled()` return True only when the required configuration is present
     (add the variables to config.py -> Settings and to .env.example);
  3. in `fetch()` return a list of RawPost (title is required; url, text and published_at recommended);
  4. add the class to SOURCES in sources/__init__.py.

If your source handles per-item failures itself (one dead feed out of ten), append a label to
`self.failures`: fetch_all() merges those into the digest's "Unreachable" line instead of losing
them in the log. Raising from fetch() marks the whole source unreachable instead.

Ideas that fit this project:
  - Grok (xAI) with X / web search, as an alternative to the paid X API;
  - Perplexity or another web-search model, for questions like "what is new in <your field> today";
  - Mastodon / Bluesky (public APIs), or institutional websites and grant portals through RSS.
If the source is an LLM with web search, ask it to return JSON with title, URL and summary,
and drop any item without a verifiable URL.
"""
from __future__ import annotations

from .base import RawPost, Source


class ExampleSource(Source):
    name = "Example"

    @classmethod
    def enabled(cls, s) -> bool:
        return False  # e.g.: return bool(s.example_api_key)

    async def fetch(self) -> list[RawPost]:
        return []
