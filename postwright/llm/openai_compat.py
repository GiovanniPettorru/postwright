"""Any OpenAI-compatible Chat Completions endpoint: OpenAI, Grok, Mistral, DeepSeek, Groq, OpenRouter..."""
from __future__ import annotations

from .base import BaseLLM


class OpenAICompatLLM(BaseLLM):
    async def _raw(self, system: str, user: str, temperature: float) -> str:
        body = {
            "model": self.model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.cfg.spec.json_mode:
            body["response_format"] = {"type": "json_object"}
        r = await self._client.post(
            f"{self.cfg.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.cfg.api_key}"},
            json=body,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
