"""X (Twitter) API v2. Requires a plan that includes /2/tweets/search/recent (paid)."""
from __future__ import annotations

from .base import RawPost, Source, http_client, parse_date


class XSource(Source):
    name = "X"

    @classmethod
    def enabled(cls, s) -> bool:
        return bool(s.x_bearer_token)

    async def fetch(self) -> list[RawPost]:
        async with http_client() as c:
            r = await c.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers={"Authorization": f"Bearer {self.s.x_bearer_token}"},
                params={"query": self.s.x_query, "max_results": 30, "tweet.fields": "created_at,public_metrics"},
            )
            r.raise_for_status()
        out = []
        for t in r.json().get("data", []):
            m = t.get("public_metrics", {})
            out.append(
                RawPost(
                    source="X",
                    title=t["text"][:200],
                    text=f"{t['text']} [likes {m.get('like_count', 0)}, rt {m.get('retweet_count', 0)}]",
                    url=f"https://x.com/i/web/status/{t['id']}",
                    published_at=parse_date(t.get("created_at")),
                )
            )
        return out
