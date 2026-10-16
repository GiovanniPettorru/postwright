"""Convert the LinkedIn data export into posts.txt for agent 0.

Both formats are supported:
  - Shares.csv      (full export: ShareCommentary column)
  - Rich_Media.csv  ("Basic" export: text of posts with a photo, video or document, Media Description column)

Usage:
    python main.py convert-linkedin data/Rich_Media.csv --limit 40
    python main.py convert-linkedin data/Shares.csv --min-chars 200

Afterwards, add the engagement metrics by hand as the first line of your best posts:
    [reactions: 240, comments: 31]
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path


def clean(text: str) -> str:
    """The export replaces emoji and non-ASCII characters with '?': clean up the obvious leftovers."""
    text = text.replace("\\n", "\n")
    text = re.sub(r"(\w)\?(s|t|re|ve|ll|d|m)\b", r"\1'\2", text)  # It?s -> It's
    text = re.sub(r"\?{2,}", "", text)                              # lost emoji
    text = re.sub(r"[ \t]+\?(?=\s|$)", "", text)                    # stray '?' after a space
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_row(r: dict) -> tuple[str, str]:
    if "ShareCommentary" in r:                      # Shares.csv
        return (r.get("Date") or "")[:10], r.get("ShareCommentary") or ""
    desc = r.get("Media Description") or ""         # Rich_Media.csv
    m = re.search(r"on (\w+ \d{1,2}, \d{4})", r.get("Date/Time") or "")
    date = ""
    if m:
        try:
            date = datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return date, desc


def convert(csv_file: Path, out: Path, limit: int = 0, min_chars: int = 120) -> int:
    with csv_file.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    seen, posts = set(), []
    for r in rows:
        date, text = parse_row(r)
        text = clean(text)
        if len(text) >= min_chars and text not in seen:
            seen.add(text)
            posts.append((date, text))

    posts.sort(key=lambda x: x[0], reverse=True)  # newest first
    if limit:
        posts = posts[:limit]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n---\n".join(f"[date: {d}]\n{t}" for d, t in posts), encoding="utf-8")
    print(f"{len(posts)} posts out of {len(rows)} rows written to {out}")
    return len(posts)
