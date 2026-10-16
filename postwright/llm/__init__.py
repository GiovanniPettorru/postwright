"""LLM client factory. To support a new API type: write the class and add it to KINDS."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .anthropic import AnthropicLLM
from .base import BaseLLM, LLMError, generate_with_fallback
from .gemini import GeminiLLM
from .openai_compat import OpenAICompatLLM

if TYPE_CHECKING:
    from ..config import Settings

KINDS: dict[str, type[BaseLLM]] = {
    "openai_compat": OpenAICompatLLM,
    "gemini": GeminiLLM,
    "anthropic": AnthropicLLM,
}


def build_llms(settings: "Settings", role: str = "fast") -> list[BaseLLM]:
    """role='fast': cheap models used for scoring (every active one, as an ensemble).
    role='writer': same providers, using <PREFIX>_WRITER_MODEL when set. The first is always PRIMARY_LLM."""
    llms: list[BaseLLM] = []
    for cfg in settings.active_providers():
        model = cfg.writer_model if (role == "writer" and cfg.writer_model) else cfg.model
        llms.append(KINDS[cfg.spec.kind](cfg, model))
    if not llms:
        raise SystemExit("No LLM provider configured")
    return llms


__all__ = ["BaseLLM", "LLMError", "build_llms", "generate_with_fallback"]
