"""Central configuration, read from the .env file in the project root."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import ValidationError

from .llm.registry import PROVIDERS, ProviderSpec

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")
log = logging.getLogger("config")


# ---------------------------------------------------------------------------- helpers
def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).lower() in ("1", "true", "yes")


def _list(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(x.strip() for x in _env(name, default).split(",") if x.strip())


def _path(name: str, default: str) -> Path:
    p = Path(_env(name, default))
    return p if p.is_absolute() else ROOT_DIR / p


# ---------------------------------------------------------------------------- LLM providers
@dataclass(frozen=True)
class ProviderConfig:
    spec: ProviderSpec
    api_key: str
    base_url: str
    model: str
    writer_model: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.model)


def _load_providers() -> tuple[ProviderConfig, ...]:
    out = []
    for spec in PROVIDERS:
        p = spec.env_prefix
        out.append(
            ProviderConfig(
                spec=spec,
                api_key=_env(f"{p}_API_KEY"),
                base_url=_env(f"{p}_BASE_URL", spec.default_base_url).rstrip("/"),
                model=_env(f"{p}_MODEL", spec.default_model),
                writer_model=_env(f"{p}_WRITER_MODEL"),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------- settings
@dataclass(frozen=True)
class Settings:
    # Telegram
    telegram_token: str = _env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id: int = _int("TELEGRAM_CHAT_ID", 0)

    # LLM
    primary_llm: str = _env("PRIMARY_LLM", "openai").lower()
    llm_providers: tuple[str, ...] = tuple(x.lower() for x in _list("LLM_PROVIDERS"))  # empty = every active one
    providers: tuple[ProviderConfig, ...] = field(default_factory=_load_providers)

    # Sources
    reddit_client_id: str = _env("REDDIT_CLIENT_ID")
    reddit_client_secret: str = _env("REDDIT_CLIENT_SECRET")
    reddit_user_agent: str = _env("REDDIT_USER_AGENT", "postwright/1.0")
    subreddits: tuple[str, ...] = _list(
        "SUBREDDITS", "technology,Futurology,MachineLearning,europe,science"
    )
    x_bearer_token: str = _env("X_BEARER_TOKEN")
    x_query: str = _env("X_QUERY", "(AI OR startup OR research) lang:en -is:retweet -is:reply")
    google_trends_geo: str = _env("GOOGLE_TRENDS_GEO", "US")
    news_language: str = _env("NEWS_LANGUAGE", "en")  # Google News interface/content language
    news_queries: tuple[str, ...] = _list(
        "NEWS_QUERIES",
        "artificial intelligence,technology innovation,startup funding,research funding,digital policy",
    )
    # Substack has no useful API, but every publication exposes a standard RSS feed at /feed:
    # SUBSTACK_FEEDS entries are merged into RSS_FEEDS (duplicates removed, order preserved)
    # and read by the same RSS source. substack_feeds is kept separate for reference/logging only.
    substack_feeds: tuple[str, ...] = _list("SUBSTACK_FEEDS")
    rss_feeds: tuple[str, ...] = tuple(dict.fromkeys(_list("RSS_FEEDS") + _list("SUBSTACK_FEEDS")))
    hn_enabled: bool = _bool("HN_ENABLED", True)

    # Data
    db_path: Path = _path("DB_PATH", "data/trends.db")
    persona_path: Path = _path("PERSONA_PATH", "data/persona_card.json")
    retention_days: int = _int("RETENTION_DAYS", 90)  # 0 disables pruning

    # Scheduling
    timezone: str = _env("TIMEZONE", "Europe/Rome")
    scan_interval_minutes: int = _int("SCAN_INTERVAL_MINUTES", 30)      # how often it searches
    digest_interval_minutes: int = _int("DIGEST_INTERVAL_MINUTES", 60)  # how often it writes to you on Telegram
    draft_hours: str = _env("DRAFT_HOURS", "11,16,21")
    draft_lookback_hours: int = _int("DRAFT_LOOKBACK_HOURS", 8)
    draft_retry_minutes: int = _int("DRAFT_RETRY_MINUTES", 5)  # one retry after a failure; 0 disables
    vote_lookback_hours: int = _int("VOTE_LOOKBACK_HOURS", 48)  # how long an upvote keeps an item eligible
    send_empty_heartbeat: bool = _bool("SEND_EMPTY_HEARTBEAT", False)

    # Filtering and cost
    min_score: float = _float("MIN_SCORE", 7)
    max_notify: int = _int("MAX_NOTIFY", 10)
    scan_batch_size: int = _int("SCAN_BATCH_SIZE", 15)
    max_new_posts_per_scan: int = _int("MAX_NEW_POSTS_PER_SCAN", 120)
    max_post_age_hours: int = _int("MAX_POST_AGE_HOURS", 24)

    # ------------------------------------------------------------------ active providers
    def active_providers(self) -> list[ProviderConfig]:
        active = [p for p in self.providers if p.enabled]
        if self.llm_providers:
            order = {n: i for i, n in enumerate(self.llm_providers)}
            active = sorted((p for p in active if p.spec.name in order), key=lambda p: order[p.spec.name])
        active.sort(key=lambda p: p.spec.name != self.primary_llm)  # the primary one goes first
        return active

    # ------------------------------------------------------------------ validation
    def validate(self, need_telegram: bool = True) -> None:
        from .scheduler import interval_trigger_kwargs  # local import to avoid a circular import

        errors = []
        if need_telegram:
            if not self.telegram_token:
                errors.append("TELEGRAM_BOT_TOKEN is missing")
            if not self.telegram_chat_id:
                errors.append("TELEGRAM_CHAT_ID is missing (see the README, Telegram section)")
        for p in self.providers:
            if p.api_key and not p.model:
                log.warning("%s: API key present but %s_MODEL is empty, provider ignored",
                            p.spec.label, p.spec.env_prefix)
        if not self.active_providers():
            errors.append("No active LLM provider: at least one <PROVIDER>_API_KEY + <PROVIDER>_MODEL pair is required")
        known = {s.name for s in PROVIDERS}
        for n in (self.primary_llm, *self.llm_providers):
            if n not in known:
                errors.append(f"Unknown provider '{n}'. Valid values: {', '.join(sorted(known))}")
        for name in ("scan_interval_minutes", "digest_interval_minutes"):
            try:
                interval_trigger_kwargs(getattr(self, name))
            except ValueError as e:
                errors.append(f"{name.upper()}: {e}")
        if self.digest_interval_minutes < self.scan_interval_minutes:
            errors.append("DIGEST_INTERVAL_MINUTES must be >= SCAN_INTERVAL_MINUTES")
        if self.draft_retry_minutes < 0:
            errors.append("DRAFT_RETRY_MINUTES must be 0 (no retry) or a positive number of minutes")
        if 0 < self.retention_days < 2:
            errors.append("RETENTION_DAYS must be 0 (keep everything) or at least 2")
        try:
            ZoneInfo(self.timezone)
        except Exception:  # noqa: BLE001 - any failure means the name is unusable
            errors.append(f"TIMEZONE '{self.timezone}' is not a valid IANA name (e.g. Europe/Rome, UTC)")
        bad_feeds = [u for u in self.rss_feeds if not u.startswith(("http://", "https://"))]
        if bad_feeds:
            errors.append("Invalid URLs in RSS_FEEDS/SUBSTACK_FEEDS: " + ", ".join(bad_feeds))
        if errors:
            raise SystemExit("Invalid configuration:\n - " + "\n - ".join(errors))


def load_persona(path: Path) -> dict:
    """Load the persona card and check it against the PersonaCard schema.

    Returns the raw dict, which is what the prompts embed. A hand-written card with a
    missing field or an out-of-range weight fails here with a readable message instead
    of silently degrading the scoring."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Generate it with: python main.py persona --cv data/cv.txt --posts data/posts.txt"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path} is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object, not {type(data).__name__}")

    from .agents.persona import PersonaCard  # local import to avoid a circular import

    try:
        PersonaCard(**data)
    except ValidationError as e:
        problems = "\n".join(
            f" - {'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:20]
        )
        raise SystemExit(
            f"{path} does not match the persona card schema:\n{problems}\n"
            "See README section 6 for the list of required fields."
        )
    return data
