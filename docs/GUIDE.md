# Full guide

Reference documentation. For installation and first setup, start with the
[README](../README.md).

The whole project — code, comments, log messages, Telegram messages and the prompts
sent to the AI models — is in English. The language of the *drafts* is a separate
setting: it comes from `tone_of_voice.language` in your persona card.

## Contents

1. [The agents](#the-agents)
2. [Scheduling: scan and digest](#scheduling-scan-and-digest)
3. [Full configuration](#full-configuration)
4. [AI providers](#ai-providers)
5. [Adding a new AI provider](#adding-a-new-ai-provider)
6. [Sources](#sources)
7. [Adding a new source](#adding-a-new-source)
8. [The persona card](#the-persona-card)
9. [Feedback and economic/political topics](#feedback-and-economicpolitical-topics)
10. [Data model](#data-model)
11. [Cost, limits and safety](#cost-limits-and-safety)

---

## The agents

| Agent | File | When | What it does |
|---|---|---|---|
| 0 · Profiler | `agents/persona.py` | on demand | Turns CV + past posts into `persona_card.json`: core themes, adjacent themes (economy, finance, policy), geographic priorities, tone of voice, best examples, language. |
| 1 · Scanner | `agents/scanner.py` | every `SCAN_INTERVAL_MINUTES` | Collects posts, drops duplicates, scores them **semantically** with every active AI in parallel, stores them. |
| 2 · Evaluator | `agents/editorial.py` | at `DRAFT_HOURS` | Decides whether any of the recent top trends actually deserves a post. |
| 3 · Copywriter | `agents/editorial.py` | right after agent 2 | Writes the draft in your voice and sends it with Approve / Discard buttons. |

**When a draft slot fails.** Two outcomes are deliberate decisions and are never retried:
no trend above threshold, and agent 2 judging that nothing deserves a post. Two are
failures and are retried once, `DRAFT_RETRY_MINUTES` later: the models erroring out, and
a draft that was written but could not be delivered. In the second case the retry resends
the same draft rather than generating another, and the source posts stay unmarked until
delivery actually succeeds. A new scheduled slot cancels any retry still pending.

```
sources ─► Agent 1 (AI ensemble) ─► SQLite ─► Telegram digest
                                      │
                   draft hours ─► Agent 2 ─► Agent 3 ─► draft + buttons
                                      ▲                      │
                                      └─── approve/discard ◄─┘
```

---

## Scheduling: scan and digest

Searching and messaging are deliberately separate:

- **scan** every `SCAN_INTERVAL_MINUTES` (default 30): scores and stores, sends nothing;
- **digest** every `DIGEST_INTERVAL_MINUTES` (default 60): one message with the
  period's summary (number of scans, posts read per source, new posts scored,
  unreachable sources) plus the above-threshold trends not yet sent.

Times are aligned to the clock in `TIMEZONE`: with the defaults the scan runs at
:00 and :30 and the digest at :00 plus 30 seconds. If a scan is still running the
digest waits for it, so it always includes the freshest results. The first scan
starts 15 seconds after launch.

Allowed values for both intervals: divisors of 60 (5, 10, 15, 20, 30) or
multiples of 60 that divide 24 hours (60, 120, 180, 240, 360, 480, 720). The
digest can never be more frequent than the scan.

The digest is only sent when there is at least one trend above threshold. With
`SEND_EMPTY_HEARTBEAT=true` it arrives anyway, carrying just the scan summary.
`/digest` sends it immediately; `/scan` runs a search and then sends the digest.

---

## Full configuration

`.env` lives in the project root, next to `main.py`. The complete template is
`.env.example`.

| Variable | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | – | required |
| `PRIMARY_LLM` | `openai` | the AI that writes the persona card and the drafts |
| `LLM_PROVIDERS` | empty | which providers to use, and in what order; empty = all active ones |
| `<PREFIX>_API_KEY`, `_MODEL`, `_WRITER_MODEL`, `_BASE_URL` | see below | one set per AI |
| `SCAN_INTERVAL_MINUTES` | `30` | how often it searches |
| `DIGEST_INTERVAL_MINUTES` | `60` | how often it writes to Telegram |
| `DRAFT_HOURS` | `11,16,21` | draft times |
| `DRAFT_LOOKBACK_HOURS` | `8` | candidate window for drafts |
| `DRAFT_RETRY_MINUTES` | `5` | one retry after a failed draft; `0` disables it |
| `VOTE_LOOKBACK_HOURS` | `48` | how long a 👍 keeps an item eligible |
| `SEND_EMPTY_HEARTBEAT` | `false` | digest even with nothing above threshold |
| `TIMEZONE` | `Europe/Rome` | IANA name |
| `MIN_SCORE` | `7` | affinity threshold for digest and drafts |
| `MAX_NOTIFY` | `10` | max trends listed per digest (others stay available for drafts) |
| `SCAN_BATCH_SIZE` | `15` | posts per AI scoring call |
| `MAX_NEW_POSTS_PER_SCAN` | `120` | cap on new posts scored per scan |
| `MAX_POST_AGE_HOURS` | `24` | ignore anything older |
| `GOOGLE_TRENDS_GEO` | `US` | country code for Google Trends and Google News |
| `NEWS_LANGUAGE` | `en` | language of the Google News results (two-letter code) |
| `NEWS_QUERIES` | generic tech topics | Google News queries, comma-separated |
| `HN_ENABLED` | `true` | Hacker News |
| `RSS_FEEDS` | empty | extra RSS/Atom feeds |
| `SUBSTACK_FEEDS` | empty | Substack feeds (publication URL + `/feed`), merged into `RSS_FEEDS` |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `SUBREDDITS` | empty | Reddit activates when the keys are present |
| `X_BEARER_TOKEN`, `X_QUERY` | empty | paid X API plan |
| `DB_PATH`, `PERSONA_PATH` | `data/trends.db`, `data/persona_card.json` | relative to the project root |
| `RETENTION_DAYS` | `90` | days of scored posts to keep; `0` disables pruning |

**Careful with `NEWS_QUERIES`, `SUBREDDITS`, `RSS_FEEDS`:** if the line is present
in `.env` it *replaces* the default, it does not extend it. These only decide
where to fish; relevance is still judged by the AI.

**Variable names are matched exactly.** A typo such as `SUBSSTACK_FEEDS` is not
an error — the variable is simply ignored and the feature stays off. After
editing `.env`, confirm with `python main.py providers` and with the "Sources"
line of the next digest.

---

## AI providers

A provider is **active** when it has both `_API_KEY` and `_MODEL`. Check with
`python main.py providers`.

| Provider (`PRIMARY_LLM`) | Prefix | Default model | Notes |
|---|---|---|---|
| `openai` | `OPENAI` | `gpt-4o-mini` | ChatGPT via API. `OPENAI_BASE_URL` accepts compatible endpoints (Azure, Ollama…) |
| `gemini` | `GEMINI` | `gemini-2.5-flash` | on 404/400 update the model name |
| `anthropic` | `ANTHROPIC` | `claude-haiku-5-5` | for drafts you can set `ANTHROPIC_WRITER_MODEL=claude-sonnet-5-5` |
| `xai` | `XAI` | must be set | Grok, OpenAI-compatible API |
| `mistral` | `MISTRAL` | must be set | European provider |
| `deepseek` | `DEEPSEEK` | must be set | |
| `groq` | `GROQ` | must be set | very fast, cheap open models |
| `openrouter` | `OPENROUTER` | must be set | one key, many models |
| `perplexity` | `PERPLEXITY` | must be set | more useful as a web-search source than as a scorer |
| `inception` | `INCEPTION` | `mercury-2` | diffusion LLM, OpenAI-compatible |

Providers without a default need the model name written in `.env`, copied from
the provider's console: names change often and a stale default would only
produce errors.

**How they work together**

- **Scoring:** every active AI scores each batch in parallel; the final score is
  the average. The digest shows the breakdown, e.g. `[openai:8/anthropic:7]`.
  If one AI fails, the others carry on.
- **Persona card and drafts:** written by `PRIMARY_LLM` (using `_WRITER_MODEL` if
  set). On failure it falls through to the next provider in order.
- **Cost:** each extra AI multiplies the scoring cost. `LLM_PROVIDERS=openai,anthropic`
  limits the ensemble even if more keys exist in `.env`.

---

## Adding a new AI provider

**If it has an OpenAI-compatible API** (most do): add one line to
`postwright/llm/registry.py`:

```python
ProviderSpec("newai", "New AI", "NEWAI", "openai_compat", "https://api.newai.com/v1"),
```

then put `NEWAI_API_KEY` and `NEWAI_MODEL` in `.env`. If the provider does not
support `response_format: json_object`, add `json_mode=False`.

**If it has a different API:** create `postwright/llm/newai.py` with a class
extending `BaseLLM` that implements only `_raw(system, user, temperature) -> str`
(see `anthropic.py`, roughly 20 lines), register it in `KINDS` in
`llm/__init__.py`, then add the `registry.py` line with the new `kind`. Retries,
JSON extraction and validation are already handled by `BaseLLM`.

---

## Sources

| Source | File | Setup |
|---|---|---|
| Google Trends, Google News | `sources/google.py` | none |
| Hacker News | `sources/hackernews.py` | none (`HN_ENABLED`) |
| Reddit | `sources/reddit.py` | "script" app at reddit.com/prefs/apps |
| X | `sources/x.py` | `X_BEARER_TOKEN` (paid plan) |
| Custom RSS / Substack | `sources/rss.py` | `RSS_FEEDS=url1,url2` and/or `SUBSTACK_FEEDS` |

**Substack** has no useful API, but every publication exposes a standard RSS feed
at `/feed`. `SUBSTACK_FEEDS` entries are merged into `RSS_FEEDS` (duplicates
removed, order preserved) and read by the same RSS source.

**Feeds that answer 403.** Some publications sit behind a bot filter that inspects the
client's TLS fingerprint rather than its User-Agent. Python's SSL stack does not look
like a browser's, so those feeds refuse this program even when `curl` on the same
machine is served normally. The User-Agent, the request headers, the HTTP version and
the request rate have no bearing on it, and the only workaround is a library that
imitates a browser's TLS handshake — a heavy native dependency that breaks whenever the
filter changes, which this project deliberately avoids.

A publication that serves the same content from its own domain is usually reachable, so
try that URL first; otherwise drop the feed. Feeds that fail are listed in the digest's
"Unreachable" line.

**LinkedIn, Instagram and Facebook are not connected:** they offer no API for
reading feeds or trends and scraping violates their terms. Legitimate
alternatives: the RSS feed or newsletter of pages you follow (via `RSS_FEEDS`),
or a third-party service whose terms you accept.

---

## Adding a new source

Copy `sources/_template.py`, implement `fetch()` and `enabled()`, then add the
class to `SOURCES` in `sources/__init__.py`. The template contains ideas that fit
the project — for example using Grok's X search as an alternative to the paid X
API.

Every source returns `RawPost` objects; `fetch_all()` runs them concurrently,
de-duplicates by id, and drops anything older than `MAX_POST_AGE_HOURS`. A source
that raises is logged and reported in the digest as unreachable, without stopping
the scan. A source that handles failures item by item — one dead feed out of ten —
appends a label to `self.failures`, which `fetch_all()` merges into the same list,
so a single broken RSS or Google News query still shows up in the digest instead of
disappearing into the log.

Feed XML is parsed with `defusedxml`, so a hostile or compromised feed cannot use
entity expansion to exhaust the machine's memory, and bodies above 5 MB are refused.

---

## The persona card

`data/persona_card.json` drives **everything**: filtering, scoring and the tone of
the drafts. The three ways to create it are in
[README section 6](../README.md#6-build-your-persona-card).

### Schema

```jsonc
{
  "name": "string",
  "headline": "string",
  "audience": "string",
  "core_themes": [
    { "name": "string", "description": "string", "weight": 1-10 }
  ],
  "adjacent_interests": [
    { "name": "string", "description": "string",
      "bridge_to_core": "string", "weight": 1-10 }
  ],
  "geo_priorities": [
    { "place": "string", "weight": 1-10, "note": "string" }
  ],
  "tone_of_voice": {
    "descriptors": ["string"],
    "do": ["string"],
    "dont": ["string"],
    "signature_moves": ["string"],
    "language": "it"
  },
  "top_performing_examples": [
    { "excerpt": "string", "why_it_worked": "string", "metrics": "string" }
  ],
  "editorial_notes": "string"
}
```

`load_persona()` in `config.py` validates the file against the `PersonaCard`
model from `agents/persona.py` on every start: a `weight` outside 1-10, a missing
field or a wrong type aborts with a message naming the field. Every key is
required; lists may be empty.

### What matters most

- `core_themes[].weight` — what gets through the filter.
- `adjacent_interests[].bridge_to_core` — the concrete connection the AI reasons
  with when judging an economic or political story. A vague bridge produces noise.
- `tone_of_voice.language` — the ISO code of the language the drafts are written
  in (`"en"`, `"it"`, …). Agent 0 writes the card itself in English and infers this
  field from your posts, so the card can be in English while your drafts are not.
- `top_performing_examples` — the strongest signal for voice. Real excerpts work
  far better than descriptions.

### LinkedIn export details

The export comes in two shapes:

- `Shares.csv` — full export, column `ShareCommentary`, every post.
- `Rich_Media.csv` — "Basic" export, column `Media Description`, only posts with
  a photo, video or document.

`linkedin_export.py` detects which one it is from the columns, de-duplicates,
drops posts shorter than `--min-chars`, sorts newest first, and writes them to
`posts.txt` separated by `---`. It also repairs the `?` characters the export
leaves in place of emoji and apostrophes (`It?s` → `It's`).

Metrics are not in the export. Add them by hand as a first line on your best
posts: `[reactions: 240, comments: 31]`.

### After editing the card

Posts already scored are **not** re-scored. To start over, delete
`data/trends.db` — you lose history and feedback.

---

## Feedback and economic/political topics

**Digest votes.** Each news item in the digest has `👍 n` and `👎 n` buttons. One
tap saves the vote (the button becomes `✅`), a second tap on the same button
cancels it, and not voting is a valid choice.

- **👍** — the item becomes a priority candidate for the next draft, even if it
  is not the freshest (within `VOTE_LOOKBACK_HOURS`, 48h by default) and even if
  its affinity score is lower than others. Agent 2 reads it as a strong signal
  but stays selective: a weak item can still be skipped.
- **👎** — never used for a draft.
- **No vote** — agent 2 decides on its own, with the usual criteria.
- The last 10 votes of each kind also enter the prompts of agents 1, 2 and 3
  (they are part of the same `feedback_summary()` block), so over time they shift
  the affinity scores of new items too.

**Drafts.** Every Approve or Discard stores the topic and angle of the draft. The
last 8 of each kind enter the prompts of agents 1, 2 and 3 as an implicit
preference. This is not training, it is calibration through context — the effect
is immediate.

Economic, financial and political trends are scored on the **bridge** to your
themes (research funding, startups, employment, energy, regulation, territory):
with a concrete bridge they can reach 7-9, otherwise they stay below 5. The
reason shown in the digest names the bridge. Drafts on these topics keep an
analytical tone, with no partisan positions and no investment advice.

---

## Data model

`data/trends.db` is a SQLite database created automatically. It stores scored
posts (with id, source, score, reason and timestamps), the drafts produced, and
your feedback (votes and approve/discard decisions). Post ids are used for
de-duplication, which is why an item is never scored twice.

Inspect it with any SQLite browser, or:

```bash
sqlite3 data/trends.db ".tables"
sqlite3 data/trends.db "select count(*) from posts;"
```

Deleting the file resets everything and costs you the accumulated feedback.
Backing it up is a plain file copy.

**Retention.** Every Sunday at 04:10 the database deletes posts and scan records older
than `RETENTION_DAYS`, then runs `VACUUM` so the space is actually returned to the disk.
Two things are never deleted: posts you voted on or that produced a draft — that is the
feedback every prompt is calibrated on — and the drafts themselves.

Pruning cannot cause anything to be scored twice. Sources only return items published
within `MAX_POST_AGE_HOURS`, so a post old enough to be pruned has already disappeared
from them. Budget about 1 KB per scored post when choosing the window.

---

## Cost, limits and safety

- Posts already seen are never re-scored. Scoring happens in groups of
  `SCAN_BATCH_SIZE`, with at most `MAX_NEW_POSTS_PER_SCAN` new posts per round.
  On HTTP 429, lower both.
- A provider answering 429 or 503 is retried after a long pause (5s, then 15s),
  or after exactly the delay it asks for in a `Retry-After` header. Other errors
  are retried after 1s and 2s. A provider that is still refusing after three
  attempts is dropped for that batch only, and the remaining models carry on.
- If every AI fails on a batch, those posts are retried on the next round.
- Drafts do not invent data and leave `[...]` placeholders where one of your own
  examples belongs. Check facts and sources before publishing.
- Google's RSS endpoints are not guaranteed over time: if the format changes the
  source is skipped and appears among the unreachable ones in the digest.
- **Secrets:** `.env` holds the bot token and the API keys. Do not share it, and
  never compress the project folder to send it to someone — `.gitignore` does not
  apply to a ZIP. Use `git archive --format=zip -o /tmp/postwright.zip HEAD`, which
  contains only the tracked files. HTTP request logs are silenced because
  the bot token appears in the URL; check any log before sharing it. If a token
  is exposed, revoke it (`/revoke` on @BotFather, or from the provider's console).
- Only one instance may run against a given Telegram bot at a time.
