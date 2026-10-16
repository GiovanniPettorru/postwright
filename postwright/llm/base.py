"""Base class shared by every provider: API call, JSON extraction, pydantic validation, retries."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, TypeVar

import httpx
from pydantic import BaseModel

if TYPE_CHECKING:
    from ..config import ProviderConfig

log = logging.getLogger("llm")
T = TypeVar("T", bound=BaseModel)

# A rate limit is not a transient glitch: the provider is asking us to slow down, and
# retrying a second later just burns another request. These are the waits used when a
# provider answers 429 or 503, unless it sends a Retry-After header saying otherwise.
RATE_LIMIT_BACKOFF = (5.0, 15.0, 30.0)
MAX_BACKOFF = 120.0


def retry_delay(e: Exception, attempt: int) -> float:
    """Seconds to wait before the next attempt, given the error that just happened."""
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (429, 503):
        after = e.response.headers.get("retry-after", "").strip()
        if after:
            try:  # the header is either a number of seconds...
                return max(0.0, min(float(after), MAX_BACKOFF))
            except ValueError:
                try:  # ...or an HTTP date
                    when = parsedate_to_datetime(after)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    return max(0.0, min((when - datetime.now(timezone.utc)).total_seconds(), MAX_BACKOFF))
                except (TypeError, ValueError):
                    pass
        return RATE_LIMIT_BACKOFF[min(attempt, len(RATE_LIMIT_BACKOFF) - 1)]
    return float(2**attempt)


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    """Accepts raw JSON, JSON inside backticks, or JSON surrounded by prose."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


class BaseLLM:
    """Each provider only has to implement _raw(system, user, temperature) -> text."""

    def __init__(self, cfg: "ProviderConfig", model: str, timeout: float = 90, retries: int = 3):
        self.cfg = cfg
        self.model = model
        self.name = f"{cfg.spec.name}:{model}"
        self.retries = retries
        self._client = httpx.AsyncClient(timeout=timeout)

    async def _raw(self, system: str, user: str, temperature: float) -> str:
        raise NotImplementedError

    async def generate_json(self, system: str, user: str, schema: type[T], temperature: float = 0.2) -> T:
        schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        system_full = (
            f"{system}\n\nReply with a valid JSON object conforming to this JSON Schema and NOTHING else - "
            f"no extra prose, no backticks:\n{schema_hint}"
        )
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                raw = await self._raw(system_full, user, temperature)
                return schema.model_validate(extract_json(raw))
            # Broad on purpose: a provider changing its response shape raises TypeError or
            # AttributeError, and those must still be retried and fall through to the next model.
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt + 1 >= self.retries:
                    break  # no point sleeping after the final attempt
                delay = retry_delay(e, attempt)
                log.warning("[%s] attempt %d/%d failed (%s), retrying in %.0fs",
                            self.name, attempt + 1, self.retries, str(e)[:160], delay)
                await asyncio.sleep(delay)
        raise LLMError(f"{self.name}: {last}")

    async def aclose(self) -> None:
        await self._client.aclose()


async def generate_with_fallback(llms: list[BaseLLM], system: str, user: str, schema: type[T],
                                 temperature: float = 0.2) -> T:
    """Try the models in order (the first one is the primary) and return the first valid response."""
    errors = []
    for llm in llms:
        try:
            return await llm.generate_json(system, user, schema, temperature)
        except Exception as e:  # noqa: BLE001 - never let one provider abort the whole cycle
            errors.append(f"{llm.name}: {e}")
            log.warning("Fallback: %s unavailable (%s), trying the next one", llm.name, str(e)[:160])
    raise LLMError("Every model failed: " + " | ".join(errors))
