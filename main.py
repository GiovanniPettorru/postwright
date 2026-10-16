"""Single entry point.

    python main.py                                   # continuous service (bot + scheduler)
    python main.py scan                              # one scan + digest on Telegram, then exit
    python main.py draft                             # one editorial cycle (agents 2 and 3), then exit
    python main.py persona --cv data/cv.txt --posts data/posts.txt [--extra "..."]
    python main.py convert-linkedin data/Rich_Media.csv [--limit 40]
    python main.py providers                         # show which AI providers are configured
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # keeps the bot token out of the logs
log = logging.getLogger("main")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Postwright")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run", help="continuous service (default)")
    sub.add_parser("scan", help="one scan + digest, then exit")
    sub.add_parser("draft", help="one editorial cycle, then exit")
    sub.add_parser("providers", help="list the LLM providers and their state")
    p = sub.add_parser("persona", help="build the persona card (agent 0)")
    p.add_argument("--cv", required=True, type=Path)
    p.add_argument("--posts", required=True, type=Path)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--extra", default="", help="additional interests, free text")
    c = sub.add_parser("convert-linkedin", help="LinkedIn export (Shares.csv / Rich_Media.csv) -> posts.txt")
    c.add_argument("csv_file", type=Path)
    c.add_argument("--out", type=Path, default=Path("data/posts.txt"))
    c.add_argument("--limit", type=int, default=0, help="0 = no limit")
    c.add_argument("--min-chars", type=int, default=120)
    return ap.parse_args()


async def run_service(once: str | None = None) -> None:
    from postwright.config import Settings, load_persona
    from postwright.db import Database
    from postwright.llm import build_llms
    from postwright.scheduler import Pipeline
    from postwright.telegram_bot import TelegramBot

    s = Settings()
    s.validate()
    load_persona(s.persona_path)  # fail immediately if the persona card is missing

    db = Database(s.db_path)
    fast, writer = build_llms(s, "fast"), build_llms(s, "writer")
    log.info("Scoring models (ensemble): %s", [m.name for m in fast])
    log.info("Editorial models (fallback order): %s", [m.name for m in writer])

    pipe = Pipeline(s, db, fast, writer)
    bot = TelegramBot(s, db, scan_cb=pipe.scan, digest_cb=pipe.digest, draft_cb=pipe.draft)
    pipe.bot = bot
    await bot.start()

    try:
        if once:
            await (pipe.scan(send_digest=True) if once == "scan" else pipe.draft())
            return

        scheduler = pipe.build_scheduler()
        scheduler.start()
        log.info("Scan every %d min · Telegram digest every %d min · drafts at %s (%s)",
                 s.scan_interval_minutes, s.digest_interval_minutes, s.draft_hours, s.timezone)

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows
                signal.signal(sig, lambda *_: stop.set())
        await stop.wait()

        log.info("Shutting down…")
        scheduler.shutdown(wait=False)
    finally:
        await bot.stop()
        await asyncio.gather(*(m.aclose() for m in (*fast, *writer)), return_exceptions=True)


def show_providers() -> None:
    from postwright.config import Settings

    s = Settings()
    active = {p.spec.name for p in s.active_providers()}
    print(f"{'provider':<12} {'state':<10} {'model':<28} writer")
    for p in s.providers:
        state = "ACTIVE" if p.spec.name in active else ("no model" if p.api_key else "-")
        star = " (primary)" if p.spec.name == s.primary_llm and p.spec.name in active else ""
        print(f"{p.spec.name:<12} {state:<10} {p.model or '-':<28} {p.writer_model or '-'}{star}")


def main() -> None:
    args = parse_args()
    cmd = args.cmd or "run"
    if cmd == "convert-linkedin":
        from postwright.linkedin_export import convert

        convert(args.csv_file, args.out, args.limit, args.min_chars)
    elif cmd == "providers":
        show_providers()
    elif cmd == "persona":
        from postwright.agents.persona import build_and_save
        from postwright.config import Settings

        s = Settings()
        s.validate(need_telegram=False)
        asyncio.run(build_and_save(args.cv, args.posts, args.out or s.persona_path, s, args.extra))
    else:
        asyncio.run(run_service(None if cmd == "run" else cmd))


if __name__ == "__main__":
    main()
