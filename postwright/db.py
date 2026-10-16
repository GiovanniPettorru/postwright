"""SQLite persistence: scored posts, drafts, feedback, scan history (used by the digest)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    source TEXT, title TEXT, text TEXT, url TEXT,
    published_at TEXT, seen_at TEXT,
    score REAL, reason TEXT, topic TEXT, geo TEXT,
    notified INTEGER DEFAULT 0,
    used_in_draft INTEGER DEFAULT 0,
    vote INTEGER DEFAULT 0,          -- 1 up, -1 down, 0 none
    voted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_seen ON posts(seen_at);
CREATE INDEX IF NOT EXISTS idx_posts_score ON posts(score);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT, topic TEXT, angle TEXT, text TEXT, post_ids TEXT,
    status TEXT DEFAULT 'pending',   -- pending | approved | discarded
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT, fetched INTEGER, new INTEGER, saved INTEGER,
    source_counts TEXT, failed_sources TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def _chunks(ids: list[str], n: int = 500):
    for i in range(0, len(ids), n):
        yield ids[i : i + n]


class Database:
    def __init__(self, path: Path | str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock, self.conn:
            self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(posts)")}
            if "vote" not in cols:  # migration for databases created before voting existed
                self.conn.execute("ALTER TABLE posts ADD COLUMN vote INTEGER DEFAULT 0")  # 1 up, -1 down, 0 none
                self.conn.execute("ALTER TABLE posts ADD COLUMN voted_at TEXT")
            # Created after the migration so it also covers databases upgraded above.
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_vote ON posts(vote)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_candidates ON posts(used_in_draft, score)")

    def _q(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def _x(self, sql: str, params: tuple | list = ()) -> int:
        with self.lock, self.conn:
            return self.conn.execute(sql, params).lastrowid

    def _del(self, sql: str, params: tuple | list = ()) -> int:
        with self.lock, self.conn:
            return self.conn.execute(sql, params).rowcount

    # -- posts ----------------------------------------------------------------
    def known_ids(self, ids: list[str]) -> set[str]:
        found: set[str] = set()
        for chunk in _chunks(ids):
            rows = self._q(f"SELECT id FROM posts WHERE id IN ({','.join('?' * len(chunk))})", chunk)
            found.update(r["id"] for r in rows)
        return found

    def save_post(self, post, score: float, topic: str, geo: str, reason: str) -> None:
        self._x(
            "INSERT OR IGNORE INTO posts (id, source, title, text, url, published_at, seen_at, score, reason, topic, geo) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                post.id, post.source, post.title, post.text[:2000], post.url,
                post.published_at.isoformat() if post.published_at else None,
                now_iso(), score, reason, topic, geo,
            ),
        )

    def pending_alerts(self, min_score: float) -> list[dict]:
        return self._q(
            "SELECT * FROM posts WHERE notified=0 AND score>=? ORDER BY score DESC, seen_at DESC", (min_score,)
        )

    def mark_notified(self, ids: list[str]) -> None:
        for chunk in _chunks(ids):
            self._x(f"UPDATE posts SET notified=1 WHERE id IN ({','.join('?' * len(chunk))})", chunk)

    def recent_top(self, hours: float, min_score: float, limit: int, vote_hours: float = 48) -> list[dict]:
        """Draft candidates: upvoted items first (even if less recent, within vote_hours),
        then the highest scoring ones. Downvoted items are always excluded."""
        return self._q(
            "SELECT * FROM posts WHERE used_in_draft=0 AND COALESCE(vote,0)>=0 "
            "AND ((vote=1 AND voted_at>=?) OR (seen_at>=? AND score>=?)) "
            "ORDER BY COALESCE(vote,0) DESC, score DESC LIMIT ?",
            (_ago(vote_hours), _ago(hours), min_score, limit),
        )

    # -- up/down votes coming from the digest ----------------------------------
    def get_vote(self, post_id: str) -> int:
        rows = self._q("SELECT COALESCE(vote,0) AS v FROM posts WHERE id=?", (post_id,))
        return rows[0]["v"] if rows else 0

    def set_vote(self, post_id: str, vote: int) -> None:
        self._x("UPDATE posts SET vote=?, voted_at=? WHERE id=?", (vote, now_iso() if vote else None, post_id))

    def mark_used(self, ids: list[str]) -> None:
        for chunk in _chunks(ids):
            self._x(f"UPDATE posts SET used_in_draft=1 WHERE id IN ({','.join('?' * len(chunk))})", chunk)

    # -- scans (history used by the digest) ------------------------------------
    def record_scan(self, started_at: str, stats: dict) -> None:
        self._x(
            "INSERT INTO scan_runs (started_at, fetched, new, saved, source_counts, failed_sources) VALUES (?,?,?,?,?,?)",
            (
                started_at, stats.get("fetched", 0), stats.get("new", 0), stats.get("saved", 0),
                json.dumps(stats.get("counts", {})), json.dumps(stats.get("failed", [])),
            ),
        )

    def scans_since(self, since_iso: str) -> dict:
        """Aggregate every scan that happened from `since_iso` onwards."""
        rows = self._q("SELECT * FROM scan_runs WHERE started_at>=? ORDER BY started_at", (since_iso,))
        counts: dict[str, int] = {}
        failed: set[str] = set()
        for r in rows:
            for k, v in json.loads(r["source_counts"] or "{}").items():
                counts[k] = counts.get(k, 0) + v
            failed.update(json.loads(r["failed_sources"] or "[]"))
        return {
            "scans": len(rows),
            "fetched": sum(r["fetched"] or 0 for r in rows),
            "new": sum(r["new"] or 0 for r in rows),
            "saved": sum(r["saved"] or 0 for r in rows),
            "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "failed": sorted(failed - set(counts)),  # only sources that never succeeded in the period
        }

    def get_meta(self, key: str) -> str | None:
        rows = self._q("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        self._x("INSERT INTO meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))

    # -- drafts & feedback -------------------------------------------------------
    def add_draft(self, topic: str, angle: str, text: str, post_ids: list[str]) -> int:
        return self._x(
            "INSERT INTO drafts (created_at, topic, angle, text, post_ids) VALUES (?,?,?,?,?)",
            (now_iso(), topic, angle, text, json.dumps(post_ids)),
        )

    def get_draft(self, draft_id: int) -> dict | None:
        rows = self._q("SELECT * FROM drafts WHERE id=?", (draft_id,))
        return rows[0] if rows else None

    def set_draft_status(self, draft_id: int, status: str) -> None:
        self._x("UPDATE drafts SET status=?, decided_at=? WHERE id=?", (status, now_iso(), draft_id))

    def recent_drafts(self, n: int = 5) -> list[dict]:
        return self._q("SELECT * FROM drafts ORDER BY id DESC LIMIT ?", (n,))

    def feedback_summary(self, n: int = 8, n_votes: int = 10) -> str:
        """Text injected into the prompts (implicit learning):
        approved/discarded drafts and news items voted up/down in the digest."""
        ok = self._q("SELECT topic, angle FROM drafts WHERE status='approved' ORDER BY decided_at DESC LIMIT ?", (n,))
        no = self._q("SELECT topic, angle FROM drafts WHERE status='discarded' ORDER BY decided_at DESC LIMIT ?", (n,))
        up = self._q("SELECT topic, title FROM posts WHERE vote=1 ORDER BY voted_at DESC LIMIT ?", (n_votes,))
        down = self._q("SELECT topic, title FROM posts WHERE vote=-1 ORDER BY voted_at DESC LIMIT ?", (n_votes,))
        if not (ok or no or up or down):
            return ""
        fmt = lambda rows: "; ".join(f"{r['topic']} ({r['angle']})" for r in rows) or "none"  # noqa: E731
        fmt_v = lambda rows: "; ".join(f"{r['topic']}: {r['title'][:90]}" for r in rows) or "none"  # noqa: E731
        return (
            "USER FEEDBACK (implicit preference, use it to calibrate):\n"
            f"- APPROVED DRAFTS: {fmt(ok)}\n- DISCARDED DRAFTS: {fmt(no)}\n"
            f"- NEWS VOTED UP (topics the user wants to focus on): {fmt_v(up)}\n"
            f"- NEWS VOTED DOWN (topics the user is not interested in): {fmt_v(down)}\n"
        )

    # -- retention ---------------------------------------------------------------
    def prune(self, days: int) -> dict:
        """Drop posts and scan history older than `days`, and reclaim the space.

        Posts you voted on, and posts that produced a draft, are kept forever: they are
        the accumulated feedback that every prompt is calibrated on. Drafts are never
        deleted. `days <= 0` disables pruning entirely.

        An old post cannot come back and be re-scored: sources only return items from the
        last MAX_POST_AGE_HOURS, so anything past that window is gone from them already.
        """
        if days <= 0:
            return {"posts": 0, "scans": 0, "freed_kb": 0}
        cutoff = _ago(days * 24)
        before = Path(self.conn.execute("PRAGMA database_list").fetchone()[2]).stat().st_size
        posts = self._del(
            "DELETE FROM posts WHERE seen_at < ? AND COALESCE(vote,0) = 0 AND used_in_draft = 0",
            (cutoff,),
        )
        scans = self._del("DELETE FROM scan_runs WHERE started_at < ?", (cutoff,))
        freed = 0
        if posts or scans:
            with self.lock:
                self.conn.commit()
                self.conn.execute("VACUUM")  # rewrites the file, so the space is actually returned
            after = Path(self.conn.execute("PRAGMA database_list").fetchone()[2]).stat().st_size
            freed = max(0, before - after) // 1024
        return {"posts": posts, "scans": scans, "freed_kb": freed}

    def stats(self, min_score: float) -> dict:
        r = self._q(
            "SELECT COUNT(*) AS posts, SUM(score>=?) AS relevant, SUM(notified=0 AND score>=?) AS pending, "
            "(SELECT COUNT(*) FROM drafts) AS drafts, "
            "(SELECT COUNT(*) FROM drafts WHERE status='approved') AS approved, "
            "SUM(vote=1) AS up, SUM(vote=-1) AS down FROM posts",
            (min_score, min_score),
        )[0]
        return {k: (v or 0) for k, v in r.items()}
