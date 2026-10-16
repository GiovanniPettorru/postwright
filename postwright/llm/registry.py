"""Catalogue of the supported LLM providers.

Adding an AI takes a single line in PROVIDERS:
  - if it exposes an OpenAI-compatible API (most do: Grok, Mistral, DeepSeek, Groq, OpenRouter, Ollama...)
    use kind="openai_compat" and give the base URL;
  - otherwise write a class in llm/<name>.py extending BaseLLM and register it in llm/__init__.py (KINDS).

Every provider is configured in .env through its prefix:
  <PREFIX>_API_KEY, <PREFIX>_MODEL, <PREFIX>_WRITER_MODEL (optional), <PREFIX>_BASE_URL (optional)
A provider is active once it has both API_KEY and MODEL.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str              # identifier used in PRIMARY_LLM / LLM_PROVIDERS
    label: str             # human-readable name
    env_prefix: str        # prefix of the environment variables
    kind: str              # "openai_compat" | "gemini" | "anthropic"
    default_base_url: str = ""
    default_model: str = ""   # empty = must be set in .env (model names change often)
    json_mode: bool = True    # supports response_format={"type": "json_object"}


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec("openai", "OpenAI (ChatGPT)", "OPENAI", "openai_compat", "https://api.openai.com/v1", "gpt-4o-mini"),
    ProviderSpec("gemini", "Google Gemini", "GEMINI", "gemini", default_model="gemini-2.5-flash"),
    ProviderSpec("anthropic", "Anthropic Claude", "ANTHROPIC", "anthropic", "https://api.anthropic.com/v1",
                 "claude-haiku-5-5"),
    ProviderSpec("xai", "xAI Grok", "XAI", "openai_compat", "https://api.x.ai/v1"),
    ProviderSpec("mistral", "Mistral AI", "MISTRAL", "openai_compat", "https://api.mistral.ai/v1"),
    ProviderSpec("deepseek", "DeepSeek", "DEEPSEEK", "openai_compat", "https://api.deepseek.com/v1"),
    ProviderSpec("groq", "Groq", "GROQ", "openai_compat", "https://api.groq.com/openai/v1"),
    ProviderSpec("openrouter", "OpenRouter", "OPENROUTER", "openai_compat", "https://openrouter.ai/api/v1",
                 json_mode=False),
    ProviderSpec("perplexity", "Perplexity", "PERPLEXITY", "openai_compat", "https://api.perplexity.ai",
                 json_mode=False),
    ProviderSpec("inception", "Inception Mercury", "INCEPTION", "openai_compat",
                 "https://api.inceptionlabs.ai/v1", "mercury-2", json_mode=False),
    # ---- Room for new providers ----------------------------------------------------------------
    # ProviderSpec("ollama", "Ollama (local)", "OLLAMA", "openai_compat", "http://localhost:11434/v1"),
)
