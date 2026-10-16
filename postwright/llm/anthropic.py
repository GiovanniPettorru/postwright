"""Anthropic Claude (Messages API)."""
from __future__ import annotations

from .base import BaseLLM, LLMError


class AnthropicLLM(BaseLLM):
    async def _raw(self, system: str, user: str, temperature: float) -> str:
        r = await self._client.post(
            f"{self.cfg.base_url}/messages",
            headers={"x-api-key": self.cfg.api_key, "anthropic-version": "2023-06-01"},
            json={
                "model": self.model,
                # Large enough for a full SCAN_BATCH_SIZE of scores with their reasons.
                "max_tokens": 8192,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        data = r.json()
        if data.get("stop_reason") == "max_tokens":
            # Otherwise the truncated JSON fails to parse and the real cause is invisible.
            raise LLMError("response truncated at max_tokens - lower SCAN_BATCH_SIZE")
        texts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        if not texts:
            raise LLMError("response contained no text")
        return "".join(texts)
