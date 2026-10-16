"""Google Gemini (REST generateContent)."""
from __future__ import annotations

from .base import BaseLLM


class GeminiLLM(BaseLLM):
    async def _raw(self, system: str, user: str, temperature: float) -> str:
        r = await self._client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.cfg.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
            },
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
