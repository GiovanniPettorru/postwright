"""Reddit through praw (read-only "script" app)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .base import RawPost, Source

log = logging.getLogger("sources")


class RedditSource(Source):
    name = "Reddit"
    per_sub = 12

    @classmethod
    def enabled(cls, s) -> bool:
        return bool(s.reddit_client_id and s.reddit_client_secret)

    def _fetch_sync(self) -> list[RawPost]:
        import praw  # local import: only needed when Reddit is configured

        reddit = praw.Reddit(
            client_id=self.s.reddit_client_id,
            client_secret=self.s.reddit_client_secret,
            user_agent=self.s.reddit_user_agent,
            check_for_async=False,
        )
        reddit.read_only = True
        out = []
        for sub in self.s.subreddits:
            try:
                for p in reddit.subreddit(sub).hot(limit=self.per_sub):
                    if p.stickied:
                        continue
                    out.append(
                        RawPost(
                            source=f"Reddit r/{sub}",
                            title=p.title,
                            text=f"{(p.selftext or '')[:700]} [upvotes {p.score}, comments {p.num_comments}]",
                            url=f"https://www.reddit.com{p.permalink}",
                            published_at=datetime.fromtimestamp(p.created_utc, tz=timezone.utc),
                        )
                    )
            except Exception as e:  # noqa: BLE001
                log.warning("Reddit r/%s failed: %s", sub, e)
        return out

    async def fetch(self) -> list[RawPost]:
        return await asyncio.to_thread(self._fetch_sync)  # praw is synchronous
