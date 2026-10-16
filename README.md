# Postwright

**Your newsroom, your voice, your approval.** Postwright reads the news for you,
pings you on Telegram only about what matches your professional profile, and
drafts LinkedIn posts the way you would have written them.

Nothing is ever published automatically. You always get a draft and a button.

> *A wheelwright makes wheels, a playwright makes plays. A postwright makes posts —
> yours, from what actually happened today.*

```
 every 30-60 min        every 1-3 h             11:00 · 16:00 · 21:00
┌─────────────────┐   ┌─────────────────┐     ┌──────────────────────┐
│ Collect + score │──►│ Telegram digest │     │   LinkedIn draft     │
│  sources + AI   │   │   👍 / 👎       │     │  Approve / Discard   │
└─────────────────┘   └─────────────────┘     └──────────────────────┘
```

1. **Scan** — pulls items from Google News, Google Trends, Hacker News and,
   optionally, Reddit, X and any RSS feed. Every active AI model scores each
   item 1-10 for affinity with your profile.
2. **Digest** — one single Telegram message per period with the items scoring
   ≥ `MIN_SCORE`. Each item has 👍 / 👎 buttons that teach the system.
3. **Draft** — at fixed hours the AI picks the best trend and writes a post in
   your voice. You approve or discard with one tap.

Your profile lives in `data/persona_card.json`, built from your CV and your past
LinkedIn posts.

---

## Table of contents

1. [Before you start](#1-before-you-start)
2. [Install](#2-install)
3. [Create the Telegram bot](#3-create-the-telegram-bot)
4. [Get an AI API key](#4-get-an-ai-api-key)
5. [Fill in the .env file](#5-fill-in-the-env-file)
6. [Build your persona card](#6-build-your-persona-card) — CV · LinkedIn import · by hand
7. [First run](#7-first-run)
8. [Daily use](#8-daily-use)
9. [Run it 24/7](#9-run-it-247) — Raspberry Pi · Linux server · macOS · Windows · Docker
10. [Costs](#10-costs)
11. [Privacy and security](#11-privacy-and-security)
12. [Troubleshooting](#12-troubleshooting)
13. [Project layout](#13-project-layout)

---

## 1. Before you start

You need:

| Thing | Why | Cost |
|---|---|---|
| **Python 3.11 or newer** | runs the program | free |
| **A Telegram account** | that is where the bot talks to you | free |
| **An API key from at least one AI provider** | scoring and writing | pay-per-use, a few cents to a few euros per month |
| *(optional)* **Your LinkedIn data export** | teaches the AI your writing voice | free |
| *(optional)* **A Raspberry Pi or an always-on computer** | keeps it running 24/7 | — |

Check your Python version:

```bash
python3 --version
```

If it prints `3.11.x` or higher you are fine. If the command is not found or the
version is older:

- **Windows** — install from [python.org/downloads](https://www.python.org/downloads/)
  and tick **"Add python.exe to PATH"** on the first screen.
- **macOS** — `brew install python@3.12` ([Homebrew](https://brew.sh)), or use the
  python.org installer.
- **Linux / Raspberry Pi OS** — `sudo apt update && sudo apt install python3 python3-venv python3-pip`.
  On Raspberry Pi OS *Bookworm* this gives 3.11; on the older *Bullseye* it gives 3.9, so upgrade the OS or install a newer Python.

> Throughout this README, commands are written for macOS/Linux. On Windows use
> PowerShell and read the notes marked **Windows**.

---

## 2. Install

### 2.1 Get the code

```bash
git clone https://github.com/GiovanniPettorru/postwright.git
cd postwright
```

No git? Download the ZIP from the GitHub page (**Code → Download ZIP**), unzip it,
and `cd` into the folder.

### 2.2 Create a virtual environment

A virtual environment keeps this project's packages separate from the rest of your
system. Do not skip it.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell refuses with an execution-policy error, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Your prompt should now start with `(.venv)`. **Every time you open a new terminal
to work on this project you must run the `activate` command again.**

### 2.3 Install the dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

That installs `httpx`, `pydantic`, `python-dotenv`, `python-telegram-bot`,
`APScheduler` and `praw` (the last one only matters if you enable Reddit).

### 2.4 Create your configuration file

```bash
cp .env.example .env
```

**Windows:** `copy .env.example .env`

Leave it for now — sections 3 to 5 tell you what to put in it.

---

## 3. Create the Telegram bot

You need two values: a **bot token** and your **chat ID**.

### 3.1 The bot token

1. Open Telegram and search for **@BotFather** (the one with the blue checkmark).
2. Press **Start**, then send `/newbot`.
3. It asks for a **display name** — anything you like, e.g. `My Postwright`.
4. It asks for a **username** — it must be unique and end in `bot`,
   e.g. `alex_postwright_bot`. If it is taken, try another.
5. BotFather replies with a line like:

   ```
   Use this token to access the HTTP API:
   8123456789:AAH4k2n-EXAMPLE-do-not-use-this-one
   ```

6. Copy that whole string. That is your `TELEGRAM_BOT_TOKEN`.

> **Treat the token like a password.** Anyone holding it can control your bot.
> If it leaks, send `/revoke` to BotFather and generate a new one.

### 3.2 Your chat ID

The bot must know where to write. Telegram identifies you with a number.

**Easiest way:**

1. Search for **@userinfobot** on Telegram.
2. Press **Start**.
3. It replies with `Id: 123456789`. That number is your `TELEGRAM_CHAT_ID`.

**Alternative, if that bot is unavailable:**

1. Open a chat with **your own bot** (the username you chose in 3.1) and send it
   any message, e.g. `hello`. This step is mandatory — a bot cannot write first.
2. In a browser open, with your real token in place of `<TOKEN>`:

   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

   Keep the word `bot` glued to the token: `.../bot8123456789:AAH.../getUpdates`.

3. In the JSON that appears, find `"chat":{"id":123456789,` — that number is your
   chat ID.

   If you get `{"ok":true,"result":[]}`: you did not message the bot, or the
   program is already running and consumed the updates. Stop the program and
   send a new message.

### 3.3 Put both in .env

Open `.env` in any text editor and fill in:

```ini
TELEGRAM_BOT_TOKEN=8123456789:AAH4k2n-your-real-token
TELEGRAM_CHAT_ID=123456789
```

No quotes, no spaces around `=`.

---

## 4. Get an AI API key

You need **at least one**. More than one is optional: all active models vote on
every news item and the score is their average, which makes filtering steadier
but multiplies the cost.

> **Important:** an API key is *not* the same as a ChatGPT Plus / Gemini Advanced /
> Claude Pro / X Premium subscription. API access is billed separately,
> per token used. Most providers ask for a credit card; some give free starting
> credit.

### 4.1 The generic procedure — works for every provider

1. Go to the provider's **developer console** (table below) and sign in or create
   an account.
2. Find **Billing** and add a payment method or buy credit. Without this, keys
   usually return `429` or `quota exceeded` on the first call.
   Set a **monthly spending limit** while you are there — every console has one.
3. Find the section called **API keys** (or *Keys*, *Credentials*, *Tokens*).
4. Click **Create new secret key**, give it a name like `postwright`, confirm.
5. **Copy the key immediately.** Nearly every provider shows it exactly once.
   If you lose it, delete it and create another — no harm done.
6. Find the **Models** page of that same console and copy the exact name of a
   cheap, fast model (e.g. `gpt-4o-mini`, `gemini-2.5-flash`). Model names change
   often, which is why this project does not hardcode most of them.
7. In `.env`, uncomment and fill the two lines for that provider:

   ```ini
   OPENAI_API_KEY=sk-proj-your-real-key
   OPENAI_MODEL=gpt-4o-mini
   ```

   "Uncomment" means removing the leading `#`.

8. Set `PRIMARY_LLM` to that provider's short name:

   ```ini
   PRIMARY_LLM=openai
   ```

9. Verify:

   ```bash
   python main.py providers
   ```

   The provider must show `ACTIVE`. If it shows `no model`, you set the
   key but not the model name; if it shows `-`, the key is missing or misspelled.

### 4.2 Where each console is

| Provider | `PRIMARY_LLM` value | Console | Env prefix |
|---|---|---|---|
| OpenAI (ChatGPT) | `openai` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `OPENAI` |
| Google Gemini | `gemini` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `GEMINI` |
| Anthropic Claude | `anthropic` | [console.anthropic.com](https://console.anthropic.com/settings/keys) | `ANTHROPIC` |
| xAI Grok | `xai` | [console.x.ai](https://console.x.ai) | `XAI` |
| Mistral AI (EU) | `mistral` | [console.mistral.ai](https://console.mistral.ai/api-keys) | `MISTRAL` |
| DeepSeek | `deepseek` | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | `DEEPSEEK` |
| Groq | `groq` | [console.groq.com/keys](https://console.groq.com/keys) | `GROQ` |
| OpenRouter | `openrouter` | [openrouter.ai/keys](https://openrouter.ai/keys) | `OPENROUTER` |
| Perplexity | `perplexity` | [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api) | `PERPLEXITY` |
| Inception Mercury | `inception` | [platform.inceptionlabs.ai](https://platform.inceptionlabs.ai) | `INCEPTION` |

Every provider uses the same four variables:

```ini
<PREFIX>_API_KEY=       # required
<PREFIX>_MODEL=         # required — exact model name from the console
<PREFIX>_WRITER_MODEL=  # optional — a stronger model, used only for drafts
<PREFIX>_BASE_URL=      # optional — only for self-hosted or proxy endpoints
```

**Not sure which to pick?** Google Gemini has the simplest signup and a free tier
that is enough to try the project. Add others later.

Adding a provider that is not in the list takes one line of code — see
[docs/GUIDE.md](docs/GUIDE.md#adding-a-new-ai-provider).

---

## 5. Fill in the .env file

Open `.env`. The minimum working configuration is five lines:

```ini
TELEGRAM_BOT_TOKEN=8123456789:AAH...
TELEGRAM_CHAT_ID=123456789
PRIMARY_LLM=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash
```

Everything else has a sensible default. The settings you are most likely to touch:

| Variable | Default | What it does |
|---|---|---|
| `TIMEZONE` | `Europe/Rome` | all schedules follow this |
| `SCAN_INTERVAL_MINUTES` | `30` | how often it searches |
| `DIGEST_INTERVAL_MINUTES` | `60` | how often it writes to you |
| `DRAFT_HOURS` | `11,16,21` | when drafts are written |
| `DRAFT_RETRY_MINUTES` | `5` | after a failed draft, retry once after this many minutes; `0` disables |
| `MIN_SCORE` | `7` | affinity threshold, 1-10 |
| `MAX_NOTIFY` | `10` | max items per digest |
| `NEWS_QUERIES` | generic tech topics | **change this to your own topics** |
| `GOOGLE_TRENDS_GEO` | `US` | country code for Google Trends and News |
| `RETENTION_DAYS` | `90` | how long scored posts are kept; `0` keeps everything |
| `NEWS_LANGUAGE` | `en` | language of the Google News results |
| `SEND_EMPTY_HEARTBEAT` | `false` | `true` = digest even when nothing matched |

> **Language.** The program, its Telegram messages and its AI prompts are in English.
> `NEWS_LANGUAGE` only controls which language the Google News results come back in.
> The language of your LinkedIn drafts is separate: it comes from
> `tone_of_voice.language` in your persona card, so you can run an English tool and
> still get Italian drafts.

Rules that trip people up:

- **No spaces around `=`** — `MIN_SCORE=7`, not `MIN_SCORE = 7`.
- **No quotes.**
- **A line starting with `#` is disabled.**
- `SCAN_INTERVAL_MINUTES` and `DIGEST_INTERVAL_MINUTES` must be a divisor of 60
  (any of 1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30) or a multiple of 60 that divides
  a day (60, 120, 180, 240, 360, 480, 720), and the digest cannot be more
  frequent than the scan.
- `DRAFT_HOURS` is a comma-separated list of hours, no spaces: `11,16,21`.
- Lists such as `NEWS_QUERIES` **replace** the built-in default when present —
  they do not add to it.

The full table of every variable is in [docs/GUIDE.md](docs/GUIDE.md#full-configuration).

---

## 6. Build your persona card

`data/persona_card.json` is the brain of the system. It decides what counts as
relevant and how the drafts sound. There are three ways to create it.

> Whichever route you take, **open the file afterwards and correct it by hand.**
> It is plain JSON. The weights and the "bridges" decide what reaches your phone.

### Route A — from your CV (recommended, 2 minutes)

1. Turn your CV into plain text at `data/cv.txt`:

   ```bash
   pdftotext -layout cv.pdf data/cv.txt
   ```

   `pdftotext` comes with *poppler*: `brew install poppler` on macOS,
   `sudo apt install poppler-utils` on Linux. No poppler? Open the PDF, select
   all, paste into a text editor, save as `data/cv.txt`. Plain text, not .docx.

2. **Delete your home address, phone number and personal email from `cv.txt`.**
   This file is sent to the AI provider you configured.

3. Create a minimal `data/posts.txt` (one or two things you have written, or even
   a couple of paragraphs describing how you write), then run:

   ```bash
   python main.py persona --cv data/cv.txt --posts data/posts.txt
   ```

4. Add extra interests the CV does not show:

   ```bash
   python main.py persona --cv data/cv.txt --posts data/posts.txt \
     --extra "EU research funding, startup ecosystems, industrial policy"
   ```

The result is written to `data/persona_card.json`.

### Route B — import your real LinkedIn posts (best writing voice)

This teaches the AI how *you* actually write.

1. **Request your data from LinkedIn.**
   On the LinkedIn website: click your photo → **Settings & Privacy** →
   **Data privacy** → **Get a copy of your data**.
   - Choose **"Download larger data archive"** (everything) if you want all your
     posts, or pick only **Posts / Shares** if offered.
   - Click **Request archive**, confirm with your password.
   - LinkedIn emails you a download link. The small archive usually arrives in
     ~10 minutes, the full one can take up to 24 hours.

2. **Unzip it and find the one file you need:**
   - `Shares.csv` — the complete export: every post you wrote.
   - `Rich_Media.csv` — the "Basic" export: only posts with a photo, video or
     document attached.

   Either works. Copy it into the `data/` folder of this project.

3. **Delete the rest of the archive.** It contains your contacts, email
   addresses, messages and ad-targeting data. None of it is used here.

4. **Convert it:**

   ```bash
   python main.py convert-linkedin data/Shares.csv
   ```

   Options:

   ```bash
   python main.py convert-linkedin data/Rich_Media.csv --limit 40 --min-chars 200
   ```

   | Option | Default | Meaning |
   |---|---|---|
   | `--limit` | `0` (all) | keep only the N most recent posts |
   | `--min-chars` | `120` | skip posts shorter than this |
   | `--out` | `data/posts.txt` | where to write |

   The converter also cleans up the `?` characters LinkedIn's export leaves in
   place of emoji and apostrophes.

5. **Add your metrics by hand (strongly recommended).** The export does not
   include reactions or comments, and the AI uses them to find out which of your
   posts worked. Open `data/posts.txt` — posts are separated by a line with
   `---` — and on your 5-10 best posts add the metrics as a line ABOVE the
   `[date: ...]` line the converter wrote:

   ```
   [reactions: 240, comments: 31]
   [date: 2026-03-14]
   The post text...
   ```

6. **Generate the card:**

   ```bash
   python main.py persona --cv data/cv.txt --posts data/posts.txt
   ```

### Route C — write it by hand (no CV, no export, full control)

Copy the example and edit it:

```bash
cp data/persona_card.example.json data/persona_card.json
```

Then open `data/persona_card.json` and replace the content. The file is checked
against the schema every time the program starts: a missing field, a wrong type or
a weight outside 1-10 stops it with a message naming the offending field, rather
than silently degrading your results. Keep every key below:

| Field | Type | What to write |
|---|---|---|
| `name` | text | your name |
| `headline` | text | your one-line professional description |
| `audience` | text | who reads you: peers, students, clients, recruiters… |
| `core_themes` | list of 4-7 | your main topics. Each needs `name`, `description` (which sub-topics genuinely interest you) and `weight` **1-10** |
| `adjacent_interests` | list of 4-8 | economic / financial / policy topics that *affect* your core themes. Each needs `name`, `description`, `bridge_to_core` (the concrete connection — this is what the AI reasons with) and `weight` 1-10 |
| `geo_priorities` | list | places you care about, each with `place`, `weight` 1-10, `note`. E.g. your city, your region, your country, your continent, world |
| `tone_of_voice` | object | `descriptors` (list of adjectives), `do` (list), `dont` (list), `signature_moves` (list: how you open, structure, close), `language` (**ISO code of the language your drafts must be written in**, e.g. `"en"`, `"it"`) |
| `top_performing_examples` | list of 3-5 | real excerpts of your best posts: `excerpt` (max ~400 chars), `why_it_worked`, `metrics` (free text, may be empty) |
| `editorial_notes` | text | 3-6 lines of editorial rules in your own words |

Every key is required, but the lists may be empty. Minimum viable card if you are
in a hurry: fill `name`, `headline`, `audience`, three or four `core_themes`, and
`tone_of_voice` (all five of its keys), then set `adjacent_interests`,
`geo_priorities` and `top_performing_examples` to `[]` and `editorial_notes` to a
sentence. Quality improves a lot with detail.

**Check it before running:**

```bash
python main.py providers   # loads nothing persona-related, just proves .env parses
python main.py scan        # loads the card: tells you exactly what is wrong, if anything
```

A missing comma or a trailing comma is the usual cause of a JSON error on startup;
a missing field is reported by name.

### Changing the card later

Edit the JSON and save — the next scan picks it up. Items already scored are
**not** re-scored. To start from a clean slate, delete `data/trends.db`
(you lose history and feedback).

---

## 7. First run

With `.venv` active and `.env` filled in:

```bash
python main.py providers   # 1. check your AI keys are recognised
python main.py scan        # 2. one real search + digest sent to Telegram
python main.py draft       # 3. one LinkedIn draft sent to Telegram
```

If steps 2 and 3 land in your Telegram chat, you are done.

Note that step 3 may answer *"No trend above threshold"* or *"No draft in this slot"*.
That is a normal outcome, not a failure: on a fresh database the editor is deliberately
selective and would rather skip a slot than publish something weak. As long as the
message arrives, the chain works.

Start the service:

```bash
python main.py
```

It now runs until you press `Ctrl+C`. Closing the terminal or letting the laptop
sleep stops it — see [section 9](#9-run-it-247) for a permanent setup.

---

## 8. Daily use

### Terminal commands

| Command | What it does |
|---|---|
| `python main.py` | run the service continuously |
| `python main.py scan` | one search + digest, then exit |
| `python main.py draft` | one LinkedIn draft, then exit |
| `python main.py providers` | show which AI providers are active |
| `python main.py persona --cv … --posts …` | rebuild the persona card |
| `python main.py convert-linkedin <file.csv>` | LinkedIn export → `posts.txt` |

### Telegram commands

| Command | What it does |
|---|---|
| `/start` | reply with your chat id (useful if you ever need to correct `TELEGRAM_CHAT_ID`) |
| `/scan` | search now |
| `/digest` | send the digest now |
| `/draft` | write a draft now |
| `/status` | statistics |

### The buttons

- **👍 on a news item** — it becomes a priority candidate for the next draft,
  for `VOTE_LOOKBACK_HOURS` (48h by default), even if its score was lower than
  others. Tap again to undo.
- **👎** — never used for a draft.
- **No vote** — the AI decides on its own.
- **Approve / Discard on a draft** — stores the topic and angle. The last 8 of
  each kind are fed back into the prompts, so your taste is applied immediately.

Drafts leave `[...]` placeholders where a personal example belongs, and they do
not invent figures. **Check facts and sources before you publish.**

Two messages look like problems but are not: *"No trend above threshold"* and
*"No draft in this slot"* mean the editor looked and decided nothing was worth a
post. Those slots are skipped and not retried — the answer would be the same five
minutes later. A real failure (the models erroring out, or Telegram refusing the
message) says so explicitly and is retried once after `DRAFT_RETRY_MINUTES`.

---

## 9. Run it 24/7

The program must stay running to work. A laptop that sleeps is not enough. Pick
the option that matches your hardware.

### 9.1 Raspberry Pi or any Linux machine — systemd (recommended)

Works on Raspberry Pi 3 / 4 / 5 with Raspberry Pi OS, and on any Debian/Ubuntu
server. A Pi Zero 2 W is enough: the program is almost entirely idle.

**Step 1 — install the project on the Pi**

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
cd ~
git clone https://github.com/GiovanniPettorru/postwright.git
cd postwright
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Step 2 — copy your configuration over**

From your laptop:

```bash
scp .env pi@raspberrypi.local:~/postwright/.env
scp data/persona_card.json pi@raspberrypi.local:~/postwright/data/
```

Replace `pi@raspberrypi.local` with your username and the Pi's hostname or IP.
Test it once before making it a service:

```bash
python main.py scan
```

**Step 3 — create the service file**

```bash
sudo nano /etc/systemd/system/postwright.service
```

Paste this, replacing `pi` with your username if different:

```ini
[Unit]
Description=Postwright
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/postwright
ExecStart=/home/pi/postwright/.venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=append:/home/pi/postwright/service.log
StandardError=append:/home/pi/postwright/service.log

[Install]
WantedBy=multi-user.target
```

Save with `Ctrl+O`, `Enter`, then exit with `Ctrl+X`.

> Paths must be **absolute**. `~` does not work inside a service file.

**Step 4 — enable and start**

```bash
sudo systemctl daemon-reload
sudo systemctl enable postwright     # start automatically at every boot
sudo systemctl start postwright
sudo systemctl status postwright     # should say "active (running)"
```

**Everyday commands**

```bash
sudo systemctl restart postwright            # after editing .env
sudo systemctl stop postwright               # stop it
journalctl -u postwright -f                  # live logs (Ctrl+C to leave)
tail -f ~/postwright/service.log    # the log file
```

**Step 5 — keep the Pi awake and online**

```bash
sudo raspi-config     # System Options → set it to boot to console, disable screen blanking
```

If the Pi is on Wi-Fi, disable power saving so it does not drop off the network:

```bash
sudo nano /etc/rc.local
# add before "exit 0":
/sbin/iw dev wlan0 set power_save off
```

Also: set the Pi's timezone (`sudo raspi-config` → Localisation Options) and make
sure `TIMEZONE` in `.env` matches what you expect.

### 9.2 macOS — launchd

Create `~/Library/LaunchAgents/com.user.postwright.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.user.postwright</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOURNAME/postwright/.venv/bin/python</string>
    <string>main.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/YOURNAME/postwright</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key>
  <string>/Users/YOURNAME/postwright/service.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOURNAME/postwright/service.log</string>
</dict>
</plist>
```

Replace `YOURNAME`, then:

```bash
launchctl load ~/Library/LaunchAgents/com.user.postwright.plist
launchctl list | grep postwright         # check
launchctl unload ~/Library/LaunchAgents/com.user.postwright.plist   # stop
```

A Mac still stops the process when it sleeps. For true 24/7 use a Mac mini set to
never sleep (System Settings → Energy), or `caffeinate -s`.

### 9.3 Windows — Task Scheduler

1. Create `run.bat` in the project folder:

   ```bat
   @echo off
   cd /d "C:\path\to\postwright"
   call .venv\Scripts\activate.bat
   python main.py
   ```

2. Open **Task Scheduler** → **Create Task** (not "Basic Task").
3. **General:** tick *Run whether user is logged on or not* and *Run with highest privileges*.
4. **Triggers** → New → *At startup*. Tick *Repeat task every 5 minutes* →
   *for a duration of: Indefinitely* (this restarts it if it ever dies).
5. **Actions** → New → *Start a program* → browse to your `run.bat`.
6. **Conditions:** untick *Start the task only if the computer is on AC power*.
7. **Settings:** tick *If the task fails, restart every 1 minute*, and set
   *If the task is already running: Do not start a new instance*.

Also disable sleep: **Settings → System → Power → Screen and sleep → Never**.

### 9.4 Docker (any platform)

The repository ships a `.dockerignore` that keeps `.env` and `data/` out of the
image. Keep it: without it, `COPY . .` bakes your keys into a layer, where they
survive even though the volume mount later shadows the folder.

Create `Dockerfile` in the project folder:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

Build and run:

```bash
docker build -t postwright .
docker run -d --name postwright --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  postwright
```

Logs: `docker logs -f postwright`. Update: `docker restart postwright`.

The `-v` mount keeps the database and persona card on the host, so they survive
rebuilds, and `--env-file` passes the secrets in at launch. They stay out of the
image only because of `.dockerignore` — check it is there before you build, and
never push an image you built without it.

### 9.5 Quick and dirty — tmux

For an always-on machine you already use over SSH:

```bash
sudo apt install tmux
tmux new -s agents
source .venv/bin/activate && python main.py
# detach with Ctrl+B then D ; come back with: tmux attach -t agents
```

This does **not** survive a reboot. Use systemd for anything you rely on.

### 9.6 Common to every setup

- **Only one instance at a time.** Two copies polling the same Telegram bot
  fight over the updates and messages go missing. Stop the local one before
  starting the Pi.
- After editing `.env`, **restart** the service — the file is read at startup.
- `data/trends.db` is the memory of the system. Back it up occasionally:
  `cp data/trends.db data/trends.db.bak`.
- The database prunes itself once a week, keeping `RETENTION_DAYS` of history (90 by
  default) plus, forever, every post you voted on or that produced a draft. Expect
  roughly 1 KB per scored post: at 500 posts a day that is about 40 MB at the default
  setting. Set `RETENTION_DAYS=0` to keep everything.

---

## 10. Costs

Only the AI providers charge anything. Telegram, Google News, Google Trends,
Hacker News and RSS are free.

What drives the bill:

| Factor | Effect |
|---|---|
| Number of active providers | each one scores every item — 3 providers ≈ 3× the cost |
| `SCAN_INTERVAL_MINUTES` | 30 min = 48 scans/day, 60 min = 24 |
| `MAX_NEW_POSTS_PER_SCAN` | hard cap on items scored per scan |
| `SCAN_BATCH_SIZE` | items per AI call — bigger batches cost less overall |
| Model choice | a "mini"/"flash"/"haiku" tier model costs a fraction of a flagship |

To keep it cheap: one provider, a small model, `SCAN_INTERVAL_MINUTES=60`, and
set a hard monthly limit in the provider's console. Already-scored items are
never re-scored, so the cost does not grow with the size of the database.

---

## 11. Privacy and security

- **`.env` holds your bot token and your API keys.** It is in `.gitignore`.
  Never commit it, never paste it in a chat, never include it in a ZIP you send.
  If a key leaks: revoke it in the provider's console (and `/revoke` on
  @BotFather for the bot token), then issue a new one.
- **`data/` holds your personal files** — CV, posts, persona card, database.
  The whole folder is excluded from git except the examples.
- **Your CV and your posts are sent to the AI providers you configure.** Strip
  your address, phone number and personal email from `cv.txt` first.
- **HTTP request logging is silenced** because the bot token appears in the URL.
  If you ever share a log file, read it first anyway.
- **Nothing is published to LinkedIn.** The project has no LinkedIn write access
  at all; it gives you text to copy.
- **LinkedIn, Instagram and Facebook are not read either** — they offer no API
  for feeds or trends, and scraping breaks their terms. Use `RSS_FEEDS` with
  newsletters or publications instead.
- **Never share a ZIP of the project folder.** Compressing the folder from your file
  manager includes `.env` and all of `data/` — `.gitignore` does not apply to it. To
  send someone a copy, export exactly what git tracks:

  ```bash
  git archive --format=zip -o /tmp/postwright.zip HEAD
  ```

- Before pushing to GitHub, sanity-check what is tracked:

  ```bash
  git status --short          # .env must NOT appear here
  git ls-files                # nothing personal must appear here
  ```

  `git ls-files` should list only source code, documentation and the `*.example.*`
  files — never `.env`, `cv.txt`, `posts.txt`, `persona_card.json` or `trends.db`.

---

## 12. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Invalid configuration: ...` | `.env` missing, in the wrong folder, or incomplete. The message lists exactly what is missing. The file must sit next to `main.py`. |
| `command not found: python3` | Python is not installed or not on PATH. See [section 1](#1-before-you-start). |
| `ModuleNotFoundError: No module named 'httpx'` | The virtual environment is not active, or `pip install -r requirements.txt` was never run. Run `source .venv/bin/activate` first. |
| `No active LLM provider` | You set a key but no `<PREFIX>_MODEL`, or vice versa. Run `python main.py providers`. |
| `xAI Grok: API key present but XAI_MODEL is empty, provider ignored` | Exactly that: add the model name. It is a warning, not a fatal error — the run continues without that provider. |
| HTTP `404` / `400` from an AI | The model name is wrong or retired. Copy the current name from the provider's console. |
| HTTP `401` / `invalid api key` | Key mistyped, or you copied a truncated version. Create a new one. |
| HTTP `429` | Rate limit or no billing set up. The provider is retried after a long pause and usually goes through; if it fails all three attempts the other models still score the batch. To stop it happening, lower `MAX_NEW_POSTS_PER_SCAN` and `SCAN_BATCH_SIZE`, add billing, or drop that provider from `LLM_PROVIDERS`. |
| `getUpdates` returns `"result":[]` | Message your bot first; stop any other running instance; open `https://api.telegram.org/bot<TOKEN>/deleteWebhook`. |
| Telegram messages never arrive | Wrong `TELEGRAM_CHAT_ID`, or you never pressed Start in the chat with your bot. |
| Two copies of each message | Two instances are running. Stop one. |
| No digest at all | Possibly nothing above `MIN_SCORE`. Use `/status`, `/digest`, or set `SEND_EMPTY_HEARTBEAT=true`. |
| Digest full of irrelevant topics | Fix the weights and `bridge_to_core` entries in the persona card; discard the drafts you dislike. |
| `… is not valid JSON` on startup | `data/persona_card.json` has a syntax error — usually a trailing comma. |
| `… does not match the persona card schema` | The card is valid JSON but a field is missing, mistyped or out of range. The message names the field; see [section 6](#route-c--write-it-by-hand-no-cv-no-export-full-control). |
| Few sources active | Check the "Sources" line in the digest and the `WARNING` lines in the log. Google's RSS endpoints change occasionally. |
| Works locally, not on the Pi | Absolute paths in the service file; `.env` and `data/persona_card.json` actually copied over; `systemctl status postwright` for the real error. |

More detail in [docs/GUIDE.md](docs/GUIDE.md).

---

## 13. Project layout

```
main.py                  single entry point
.env.example             configuration template — copy to .env
.gitignore               keeps secrets and personal data out of git
.dockerignore            keeps them out of Docker images too
requirements.txt         dependencies
data/                    your personal files (excluded from git)
├── README.md            what goes in here
├── cv.example.txt       format example
├── posts.example.txt    format example
└── persona_card.example.json   format example
docs/GUIDE.md            full reference: every option, sources, internals
postwright/
├── config.py            reads .env, validates it
├── llm/                 one file per API type + registry.py (provider catalogue)
├── sources/             one file per source + _template.py to add your own
├── agents/              persona (profile), scanner (scoring), editorial (drafts)
├── scheduler.py         scan / digest / draft timing
├── telegram_bot.py      messages and buttons
├── db.py                SQLite storage
└── linkedin_export.py   LinkedIn CSV → posts.txt
```

Code, comments, log messages, Telegram messages and AI prompts are all in English.

---

## License

MIT — see [LICENSE](LICENSE).
