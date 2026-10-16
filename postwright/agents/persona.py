"""Agent 0 - Persona & Editorial Profiler.

Usage:  python main.py persona --cv data/cv.txt --posts data/posts.txt [--extra "..."]

posts.txt: your LinkedIn posts, separated by a line containing `---`.
If you know the engagement metrics, put them on the first line of each post, e.g.:
    [reactions: 240, comments: 31]
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import Settings
from ..llm import build_llms, generate_with_fallback

log = logging.getLogger("agent0")


class Theme(BaseModel):
    name: str
    description: str
    weight: int = Field(ge=1, le=10)


class AdjacentTheme(BaseModel):
    name: str
    description: str
    bridge_to_core: str = Field(description="How this theme connects to the core themes, even indirectly")
    weight: int = Field(ge=1, le=10)


class GeoPriority(BaseModel):
    place: str
    weight: int = Field(ge=1, le=10)
    note: str


class ToneOfVoice(BaseModel):
    descriptors: list[str]
    do: list[str]
    dont: list[str]
    signature_moves: list[str]
    language: str = "en"


class Example(BaseModel):
    excerpt: str
    why_it_worked: str
    metrics: str = ""


class PersonaCard(BaseModel):
    name: str
    headline: str
    audience: str
    core_themes: list[Theme]
    adjacent_interests: list[AdjacentTheme]
    geo_priorities: list[GeoPriority]
    tone_of_voice: ToneOfVoice
    top_performing_examples: list[Example]
    editorial_notes: str


SYSTEM = """You are Agent 0: an editorial strategist building a "persona card" for a professional.
Analyse the CV and the history of LinkedIn posts, and produce a card that other AI agents will use to:
(1) semantically judge whether a news item or trend is relevant to this profile;
(2) write new posts in this person's voice.

Rules:
- Do not invent anything: infer only from what you read. If something is missing, stay generic.
- core_themes: 4-7 core themes (e.g. the person's technical field, its socio-economic impact, industry dynamics,
  work and wellbeing), each with a concrete description (which sub-topics genuinely interest them) and a weight 1-10.
- adjacent_interests: 4-8 ECONOMIC, FINANCIAL and POLITICAL/POLICY topics the user wants to follow because they
  can affect their core themes, even indirectly (e.g. interest rates and venture capital -> startups; public research
  funding -> their lab; regulation -> their sector; energy and inflation -> industry and local economy).
  For each one write "bridge_to_core" (the concrete connection) and a weight 1-10. ALWAYS include at least one
  economic, one financial and one political/policy theme, framed in terms of impact rather than partisanship.
- geo_priorities: infer where the person is based from the CV. List their city, their region, their country, their
  continent and "World", each with a weight 1-10 and a note on how the geographic level changes their interest
  (e.g. "local news about innovation and jobs is high priority"). Use the real place names from the CV.
- tone_of_voice: descriptors, what they always do / never do, recurring moves (openings, closings, structure,
  use of data, questions).
- top_performing_examples: 3-5 real excerpts (max 400 characters) from the posts with the most traction (use the
  metrics when present, otherwise the most representative ones) and why they worked.
- tone_of_voice.language: ISO code of the language the user actually writes their posts in (e.g. "en", "it"),
  inferred from the posts. This is the language future drafts will be written in.
- editorial_notes: 3-6 lines of concise editorial guidelines.
Write the card in English, but keep the example excerpts in their original language."""


async def build_persona(cv_text: str, posts_text: str, settings: Settings, extra: str = "") -> PersonaCard:
    llms = build_llms(settings, role="writer")
    extra_block = f"\n\n=== ADDITIONAL INTERESTS STATED BY THE USER (integrate them) ===\n{extra}" if extra else ""
    user = f"=== CV ===\n{cv_text[:30000]}\n\n=== LINKEDIN POST HISTORY ===\n{posts_text[:60000]}{extra_block}"
    try:
        return await generate_with_fallback(llms, SYSTEM, user, PersonaCard, temperature=0.3)
    finally:  # one-shot command: close the connection pools before the loop ends
        await asyncio.gather(*(m.aclose() for m in llms), return_exceptions=True)


async def build_and_save(cv: Path, posts: Path, out: Path, settings: Settings, extra: str = "") -> Path:
    card = await build_persona(cv.read_text(encoding="utf-8"), posts.read_text(encoding="utf-8"), settings, extra)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(card.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Persona card saved to %s - review it by hand: everything else depends on it.", out)
    return out
