"""Job orchestration: search (scan), delivery (digest) and drafts (draft).

Searching and messaging are deliberately separate:
- scan   every SCAN_INTERVAL_MINUTES   -> scores and stores, does NOT write to Telegram
- digest every DIGEST_INTERVAL_MINUTES -> sends one message with the scans performed and the trends above threshold
- draft  at DRAFT_HOURS                -> agents 2 and 3

A shared lock prevents overlap: the :00 digest starts 30 s later and waits for the :00 scan to finish,
so it always includes the freshest results.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from .agents.editorial import run_linkedin_cycle
from .agents.scanner import collect_alerts, scan_and_score
from .config import Settings
from .db import Database, now_iso
from .llm import BaseLLM

log = logging.getLogger("scheduler")


def interval_trigger_kwargs(minutes: int) -> dict:
    """Turn an interval in minutes into the fields of a clock-aligned CronTrigger (:00, :30...)."""
    if minutes <= 0:
        raise ValueError("must be > 0")
    if minutes < 60 and 60 % minutes == 0:
        return {"minute": f"*/{minutes}"}
    if minutes % 60 == 0 and 24 % (minutes // 60) == 0:
        return {"hour": f"*/{minutes // 60}", "minute": 0}
    raise ValueError(f"{minutes} is not valid: use a divisor of 60 (5, 10, 15, 20, 30) or 60, 120, 180, 240, 360...")


class Pipeline:
    def __init__(self, settings: Settings, db: Database, fast_llms: list[BaseLLM], writer_llms: list[BaseLLM]):
        self.s, self.db = settings, db
        self.fast_llms, self.writer_llms = fast_llms, writer_llms
        self.bot = None  # set by main once the bot has been created
        self.scheduler = None  # set by build_scheduler; absent in one-shot commands
        self._undelivered: dict | None = None  # a draft that was written but never sent
        self.lock = asyncio.Lock()

    # ------------------------------------------------------------------ jobs
    async def scan(self, send_digest: bool = False) -> None:
        async with self.lock:
            started = now_iso()
            try:
                stats = await scan_and_score(self.s, self.db, self.fast_llms)
                self.db.record_scan(started, stats)
            except Exception:  # noqa: BLE001
                log.exception("Scan failed")
        if send_digest:
            await self.digest(force=True)

    async def digest(self, force: bool = False) -> None:
        async with self.lock:
            try:
                until = now_iso()
                default_since = datetime.now(timezone.utc) - timedelta(minutes=self.s.digest_interval_minutes)
                since = self.db.get_meta("last_digest_at") or default_since.isoformat(timespec="seconds")
                window = self.db.scans_since(since)
                top, overflow, all_ids = collect_alerts(self.s, self.db)
                if top or force or self.s.send_empty_heartbeat:
                    await self.bot.send_digest(top, overflow, window, since, until)
                    self.db.mark_notified(all_ids)
                self.db.set_meta("last_digest_at", until)
            except Exception:  # noqa: BLE001
                log.exception("Digest failed")

    async def draft(self, retry: bool = False) -> None:
        """Run the editorial cycle and deliver the draft.

        A genuine failure - the models erroring out, or Telegram refusing the message - is
        retried once after DRAFT_RETRY_MINUTES. A slot the editor deliberately skips is not
        a failure and is never retried: the answer would be the same five minutes later.
        """
        if not retry:  # a fresh slot supersedes anything still pending from the last one
            self._cancel_retry()
            self._undelivered = None

        res = self._undelivered
        if res is None:
            async with self.lock:
                try:
                    res = await run_linkedin_cycle(self.s, self.db, self.writer_llms)
                except Exception:  # noqa: BLE001
                    log.exception("Editorial cycle failed")
                    await self._after_failure(retry, "could not generate the draft")
                    return
            if res["status"] != "draft":
                await self._notify(res["message"])  # a decision, not a failure
                return

        try:
            await self.bot.send_draft(res)
        except Exception:  # noqa: BLE001
            # Keep it: the retry resends this draft instead of paying for a new one. Its
            # source posts stay unmarked, so nothing is lost even if the retry fails too.
            log.exception("Draft %s was written but could not be delivered", res["id"])
            self._undelivered = res
            await self._after_failure(retry, "could not send the draft")
            return

        self._undelivered = None
        self.db.mark_used(res["post_ids"])
        if retry:
            log.info("Draft delivered on the retry")

    async def _after_failure(self, was_retry: bool, what: str) -> None:
        mins = self.s.draft_retry_minutes
        if was_retry or mins <= 0 or self.scheduler is None:
            self._undelivered = None
            await self._notify(f"⚠️ Postwright {what} (see the log). "
                               "I will try again at the next scheduled slot.")
            return
        self.scheduler.add_job(
            self.draft,
            DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(minutes=mins)),
            kwargs={"retry": True},
            id="draft-retry",
            replace_existing=True,
            misfire_grace_time=600,
        )
        log.warning("%s - retrying once in %d minutes", what, mins)
        await self._notify(f"⚠️ Postwright {what}. Trying again in {mins} minutes.")

    def _cancel_retry(self) -> None:
        if self.scheduler is None:
            return
        try:
            self.scheduler.remove_job("draft-retry")
            log.info("Pending draft retry dropped: a new slot has started")
        except Exception:  # noqa: BLE001 - JobLookupError when there is nothing pending
            pass

    async def prune(self) -> None:
        """Weekly housekeeping. Silent unless something was actually removed."""
        async with self.lock:
            try:
                r = await asyncio.to_thread(self.db.prune, self.s.retention_days)
            except Exception:  # noqa: BLE001
                log.exception("Pruning failed")
                return
        if r["posts"] or r["scans"]:
            log.info("Pruned %d posts and %d scan records older than %d days, freed %d KB",
                     r["posts"], r["scans"], self.s.retention_days, r["freed_kb"])

    async def _notify(self, text: str) -> None:
        """Best-effort message to the owner: the failure we are reporting often breaks this too."""
        try:
            await self.bot.send_info(text)
        except Exception:  # noqa: BLE001
            log.exception("Could not deliver the notification: %s", text)

    # ------------------------------------------------------------------ scheduling
    def build_scheduler(self) -> AsyncIOScheduler:
        tz = self.s.timezone
        sch = AsyncIOScheduler(timezone=tz)

        # Scan: 30 minutes of tolerance (1800 s)
        sch.add_job(
            self.scan,
            CronTrigger(timezone=tz, **interval_trigger_kwargs(self.s.scan_interval_minutes)),
            id="scan",
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=15),
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

        # Periodic digest: 1 hour of tolerance (3600 s)
        sch.add_job(
            self.digest,
            CronTrigger(timezone=tz, second=30, **interval_trigger_kwargs(self.s.digest_interval_minutes)),
            id="digest",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # Retention: weekly, at a quiet hour. Skipped entirely when RETENTION_DAYS=0.
        if self.s.retention_days > 0:
            sch.add_job(
                self.prune,
                CronTrigger(timezone=tz, day_of_week="sun", hour=4, minute=10),
                id="prune",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=86400,
            )

        # LinkedIn drafts (agents 2 and 3): 2 hours of tolerance (7200 s)
        # If the machine wakes up to 2 hours after the scheduled time, the draft is still produced.
        sch.add_job(
            self.draft,
            CronTrigger(timezone=tz, hour=self.s.draft_hours, minute=0),
            id="draft",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=7200,
        )

        self.scheduler = sch  # needed to schedule the one-shot draft retry
        return sch
