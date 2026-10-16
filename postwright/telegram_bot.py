"""Telegram bot (python-telegram-bot v20+, async).

- send_digest(): periodic summary (scans performed + trends above threshold) with up/down buttons per item
- send_draft(): LinkedIn draft with "Approve / Copy" and "Discard" buttons
- Votes and decisions are stored in SQLite and fed back into the prompts as implicit feedback;
  upvoted items get priority in the next draft, downvoted ones are excluded.
- Commands: /start, /scan, /digest, /draft, /status
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from .config import Settings
from .db import Database

log = logging.getLogger("telegram")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
MAX_MSG = 3900  # Telegram limit is 4096, keep a margin


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def trim(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def pack_blocks(blocks: list[tuple[str, dict | None]], limit: int = MAX_MSG) -> list[tuple[str, list[dict]]]:
    """Group complete HTML blocks into messages under the limit, never splitting a block.
    A block can carry an item (a news entry) with it, so each message knows which buttons to show."""
    msgs: list[tuple[str, list[dict]]] = []
    cur, cur_items = "", []
    for b, item in blocks:
        b = b if len(b) <= limit else b[: limit - 1] + "…"
        if cur and len(cur) + 2 + len(b) > limit:
            msgs.append((cur, cur_items))
            cur, cur_items = b, []
        else:
            cur = f"{cur}\n\n{b}" if cur else b
        if item:
            cur_items.append(item)
    if cur:
        msgs.append((cur, cur_items))
    return msgs


def vote_label(n: int, kind: int, current: int) -> str:
    """Label of one vote button. `n` is the item's number in the digest, NOT a vote count:
    it is written as "#3" so nobody reads it as "three people voted"."""
    icon = "👍" if kind == 1 else "👎"
    return f"✅ #{n} {icon}" if current == kind else f"#{n} {icon}"


def vote_keyboard(items: list[dict]) -> InlineKeyboardMarkup | None:
    """One row per news item: [👍 n] [👎 n]. callback_data: v:<post_id>:<1|-1>"""
    if not items:
        return None
    rows = [
        [
            InlineKeyboardButton(vote_label(it["_n"], 1, it.get("vote") or 0), callback_data=f"v:{it['id']}:1"),
            InlineKeyboardButton(vote_label(it["_n"], -1, it.get("vote") or 0), callback_data=f"v:{it['id']}:-1"),
        ]
        for it in items
    ]
    return InlineKeyboardMarkup(rows)


class TelegramBot:
    def __init__(self, settings: Settings, db: Database, scan_cb=None, digest_cb=None, draft_cb=None):
        self.s, self.db = settings, db
        self.scan_cb, self.digest_cb, self.draft_cb = scan_cb, digest_cb, draft_cb
        self._tasks: set[asyncio.Task] = set()
        self.app = Application.builder().token(settings.telegram_token).build()
        for name, fn in (("start", self._cmd_start), ("scan", self._cmd_scan), ("digest", self._cmd_digest),
                         ("draft", self._cmd_draft), ("status", self._cmd_status)):
            self.app.add_handler(CommandHandler(name, fn))
        self.app.add_handler(CallbackQueryHandler(self._on_button, pattern=r"^(ok|no):\d+$"))
        self.app.add_handler(CallbackQueryHandler(self._on_vote, pattern=r"^v:[0-9a-f]+:-?1$"))
        self.app.add_error_handler(self._on_error)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram bot started")

    async def stop(self) -> None:
        # A /scan still running at SIGTERM would otherwise log "Task was destroyed but it is pending".
        pending = list(self._tasks)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await self.app.updater.stop()
        await self.app.stop()
        await self.app.shutdown()

    # ------------------------------------------------------------------ sending
    async def _send(self, text: str, **kw):
        return await self.app.bot.send_message(
            chat_id=self.s.telegram_chat_id, text=text, parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW, **kw,
        )

    async def send_info(self, text: str) -> None:
        await self._send(esc(text))

    def _hhmm(self, iso: str | datetime) -> str:
        d = datetime.fromisoformat(iso) if isinstance(iso, str) else iso
        return d.astimezone(ZoneInfo(self.s.timezone)).strftime("%H:%M")

    async def send_digest(self, items: list[dict], overflow: int, window: dict, since: str, until: str) -> None:
        """window: aggregate from Database.scans_since(); since/until: bounds of the period (ISO)."""
        header = [f"🔔 <b>Trend digest</b> · {self._hhmm(since)}–{self._hhmm(until)}"]
        read = sum(window["counts"].values()) or window["fetched"]
        header.append(
            f"🔎 {window['scans']} scans · {read} posts read · "
            f"{window['new']} newly scored · <b>{len(items) + overflow}</b> above threshold"
        )
        if window["counts"]:
            header.append("<i>Sources: " + " · ".join(f"{esc(k)} {v}" for k, v in window["counts"].items()) + "</i>")
        if window["failed"]:
            header.append("⚠️ Unreachable: " + esc(", ".join(window["failed"])))
        if not items:
            header.append("\nNo new trend above threshold in this period.")

        if items:
            header.append("<i>Vote the items with 👍/👎 (or leave them): the next draft will favour your 👍.</i>")

        blocks: list[tuple[str, dict | None]] = [("\n".join(header), None)]
        for i, it in enumerate(items, 1):
            it = {**it, "_n": i}
            title = esc(trim(it["title"], 140))
            # Only http(s) becomes a link: a feed-supplied scheme Telegram rejects would make the
            # whole message fail, and it would fail again on every later digest.
            url = it.get("url") or ""
            link = f'<a href="{esc(url)}">{title}</a>' if url.startswith(("http://", "https://")) else title
            blocks.append((
                f"{i}. <b>{it['score']:.1f}</b> · {link}\n"
                f"<i>{esc(it['source'])} · {esc(it['geo'])}</i>\n{esc(trim(it['reason'], 170))}",
                it,
            ))
        if overflow:
            blocks.append((f"➕ {overflow} more trends above threshold saved (available for LinkedIn drafts).", None))
        for msg, msg_items in pack_blocks(blocks):
            kb = vote_keyboard(msg_items)
            await self._send(msg, **({"reply_markup": kb} if kb else {}))
            # Mark as we go: if a later message fails, the ones already delivered are not re-sent.
            if msg_items:
                self.db.mark_notified([it["id"] for it in msg_items])

    async def send_draft(self, d: dict) -> None:
        sources = "\n".join(
            f'• <a href="{esc(s["url"])}">{esc(trim(s["title"], 90))}</a>' for s in d["sources"] if s.get("url")
        )
        msg = (
            f"📝 <b>LinkedIn draft #{d['id']}</b>\n<i>{esc(d['topic'])} — {esc(d['angle'])}</i>\n\n"
            f"<pre>{esc(d['text'])}</pre>\n\n<b>Sources</b>\n{sources}"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Approve / Copy", callback_data=f"ok:{d['id']}"),
            InlineKeyboardButton("🗑 Discard", callback_data=f"no:{d['id']}"),
        ]])
        await self._send(msg, reply_markup=kb)

    # ------------------------------------------------------------------ handlers
    def _authorized(self, update: Update) -> bool:
        return bool(update.effective_chat) and update.effective_chat.id == self.s.telegram_chat_id

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)  # does not block the reception of updates
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # Deliberately not restricted to the owner: this is how you read your own chat id.
    # It discloses nothing but the caller's own id.
    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            f"Hi! Your chat id is {update.effective_chat.id}.\n"
            "Put it in .env as TELEGRAM_CHAT_ID, then restart the service.\n\n"
            "Commands: /scan · /digest · /draft · /status"
        )

    async def _cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if self._authorized(update) and self.scan_cb:
            await update.effective_message.reply_text("Scan started, I will send you the digest when it finishes…")
            self._spawn(self.scan_cb(send_digest=True))

    async def _cmd_digest(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if self._authorized(update) and self.digest_cb:
            self._spawn(self.digest_cb(force=True))

    async def _cmd_draft(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if self._authorized(update) and self.draft_cb:
            await update.effective_message.reply_text("Editorial evaluation started…")
            self._spawn(self.draft_cb())

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        st = self.db.stats(self.s.min_score)
        last = self.db.get_meta("last_digest_at")
        await update.effective_message.reply_text(
            f"Posts stored: {st['posts']}\nAbove threshold: {st['relevant']} (waiting for a digest: {st['pending']})\n"
            f"Drafts: {st['drafts']} (approved: {st['approved']})\n"
            f"Votes: {st['up']} 👍 · {st['down']} 👎\n"
            f"Scan every {self.s.scan_interval_minutes} min · digest every {self.s.digest_interval_minutes} min"
            + (f"\nLast digest: {self._hhmm(last)}" if last else "")
        )

    async def _on_button(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if not self._authorized(update):
            await q.answer("Not authorized", show_alert=True)
            return
        action, raw_id = q.data.split(":")
        draft = self.db.get_draft(int(raw_id))
        if not draft:
            await q.answer("Draft not found", show_alert=True)
            return
        if draft["status"] != "pending":
            await q.answer(f"Already {draft['status']}", show_alert=True)
            return

        if action == "ok":
            self.db.set_draft_status(draft["id"], "approved")
            await q.answer("Approved ✅")
            await q.edit_message_reply_markup(reply_markup=None)
            await q.message.reply_html(  # <pre> block: on Telegram a single tap copies it
                f"✅ <b>Draft #{draft['id']} approved.</b> Tap the text to copy it, then paste it into LinkedIn:\n\n"
                f"<pre>{esc(draft['text'])}</pre>"
            )
        else:
            self.db.set_draft_status(draft["id"], "discarded")
            await q.answer("Discarded 🗑")
            await q.edit_message_text(
                f"🗑 Draft #{draft['id']} discarded ({draft['topic']}). I will take it into account."
            )

    async def _on_vote(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Tap on 👍/👎: store the vote; a second tap on the same button cancels it."""
        q = update.callback_query
        if not self._authorized(update):
            await q.answer("Not authorized", show_alert=True)
            return
        _, post_id, raw = q.data.split(":")
        kind = int(raw)
        new = 0 if self.db.get_vote(post_id) == kind else kind
        self.db.set_vote(post_id, new)

        # Acknowledge first: the vote is already stored, and everything below is cosmetic.
        # Without this the client spins forever whenever the refresh fails.
        await q.answer({1: "👍 Saved: the next draft will also look at this",
                        -1: "👎 Saved: I will avoid similar topics",
                        0: "Vote removed"}[new])

        # Refresh only the two buttons of that item, leaving the others untouched.
        # A message older than 48h arrives as InaccessibleMessage, which has no reply_markup.
        try:
            rows = []
            for row in q.message.reply_markup.inline_keyboard:
                new_row = []
                for b in row:
                    if b.callback_data and b.callback_data.startswith(f"v:{post_id}:"):
                        n = int(re.search(r"#(\d+)", b.text).group(1))
                        b = InlineKeyboardButton(vote_label(n, int(b.callback_data.split(":")[2]), new),
                                                 callback_data=b.callback_data)
                    new_row.append(b)
                rows.append(new_row)
            await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
        except Exception as e:  # noqa: BLE001 - message too old, inaccessible, or unchanged
            log.debug("Keyboard refresh failed: %s", e)

    async def _on_error(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Last resort for handler exceptions: without this they vanish into a PTB log line.

        Log only - trying to message the owner from here can fail for the same reason and loop."""
        log.error("Unhandled error in a Telegram handler", exc_info=ctx.error)
