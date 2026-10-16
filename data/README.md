# data/

Your personal files and local state. **Everything in this folder is excluded from
git** except this README and the `*.example.*` files — see `.gitignore`.

| File | What it is | How to get it |
|---|---|---|
| `cv.txt` | your CV as plain text | `pdftotext -layout cv.pdf data/cv.txt` — then delete address, phone and personal email |
| `Shares.csv` / `Rich_Media.csv` | your LinkedIn post export | LinkedIn → Settings & Privacy → Data privacy → Get a copy of your data |
| `posts.txt` | your posts, ready for agent 0 | `python main.py convert-linkedin data/Shares.csv` |
| `persona_card.json` | your editorial profile | `python main.py persona --cv data/cv.txt --posts data/posts.txt`, or copy and edit `persona_card.example.json` |
| `trends.db` | SQLite database (scored posts, drafts, feedback) | created automatically |

## Examples

- `persona_card.example.json` — the exact structure of a persona card, filled
  with a fictional profile. Copy it to `persona_card.json` and edit it if you
  want to write your profile by hand.
- `cv.example.txt` — the kind of plain-text CV agent 0 reads well.
- `posts.example.txt` — the format of `posts.txt`: posts separated by a line
  containing `---`, optional metrics on the first line.

## Backups

`trends.db` holds all your feedback. Copy it somewhere safe now and then:

```bash
cp data/trends.db data/trends.db.bak
```

Deleting it resets history and feedback; the persona card and the `.env` are
untouched.
