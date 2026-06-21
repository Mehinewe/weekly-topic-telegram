# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telegram group automation, run on GitHub Actions cron — no app server, no test suite.
Two features share the same bot token / chat id (repo secrets `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`):

1. **Weekly topic poster** — posts a prepared image + caption every Monday. Stateless,
   CSV-driven. (`send_weekly_topic.py`, `schedule.csv`, `weekly.yml`)
2. **Weekly awards** — auto-computes last week's top contributors and posts award GIFs
   with a "Get Your Badge Avatar" button. Stateful: an hourly logger records group
   activity all week, a Monday poster tallies it. (`log_activity.py` + `send_weekly_awards.py`,
   `activity_log.csv`, `awards.csv`, `log.yml` + `awards.yml`, `docs/` mini app)

## Commands

```bash
pip install -r requirements.txt          # only dep is `requests`

# Preview without sending (no token needed — exits before the credential check):
python send_weekly_topic.py --dry-run
python send_weekly_topic.py 2026-06-22 --dry-run   # force a specific week

# Real send (needs env vars set):
python send_weekly_topic.py              # picks the current week's row
python send_weekly_topic.py 2026-06-22   # force a specific Monday

python get_chat_id.py                     # one-time helper to find the group chat id
```

Required env vars for a real send: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
Locally these are read from a gitignored `.env` (see `load_dotenv` in the script);
on GitHub Actions they come from repo secrets of the same names.

## Architecture

The whole flow lives in [send_weekly_topic.py](send_weekly_topic.py):

1. **Week resolution** — `monday_of()` snaps any date to the Monday of its week. The
   target is today (or the CLI date arg), so the same script run any day that week
   resolves to the same row.
2. **Row selection** (`pick_row`) — matches a `schedule.csv` row by the *Monday of its
   date*, so CSV dates don't have to be exact Mondays. If no row matches the target
   week, it falls back to the **most recent past row** rather than failing — a missed
   week re-sends the latest topic.
3. **Image resolution** (`resolve_image`) — looks up the CSV's `image` value in
   `images/`, and if the exact filename is missing, retries by stem with a
   `.png/.jpg/.jpeg` swap (so `0.png` in the CSV still matches `0.jpg` on disk).
4. **Send** — `sendPhoto` with the message as caption. Telegram caps captions at 1024
   chars (`CAPTION_LIMIT`); longer messages send the first chunk as the caption and the
   remainder as a follow-up `sendMessage`.

`--dry-run` short-circuits before the credential check, so previews work without secrets.
Any error calls `_fail()` which exits non-zero so the scheduler flags the run.

## Data contract: schedule.csv

The CSV *is* the content database. Columns: `date,image,message`.
- `date` — the Monday to post (`YYYY-MM-DD` preferred; `M/D/YYYY` also parsed).
- `image` — filename under `images/`, must match (extension swap is tolerated).
- `message` — wrap in `"double quotes"`; multi-line and emoji are supported.

Emojis matter: editing the CSV in Excel strips them, so the documented workflow
(see [WEEKLY_GUIDE.md](WEEKLY_GUIDE.md)) is to edit it directly on the GitHub website.

## Scheduling

[.github/workflows/weekly.yml](.github/workflows/weekly.yml) runs the script every
Monday at 10:00 UTC (`cron: "0 10 * * 1"`). GitHub cron is always UTC.

`workflow_dispatch` allows a manual run with a `dry_run` input that **defaults to true**
(safe preview). The scheduled run always posts for real; a manual run posts only if you
untick "Dry run". The dry-run flag is wired in via the workflow's `run:` expression, not
the script.

[run_local.bat](run_local.bat) is the Windows Task Scheduler alternative (only runs while
the PC is on). It just sets the two env vars and calls the script.

## Weekly awards (the stateful feature)

Because Telegram gives a bot **no message history** and drops undelivered updates after
~24h, winner-counting can't be a once-a-week job. It's split in two:

- **`log_activity.py`** (hourly via `log.yml`) — calls `getUpdates`, advances the
  `last_update_id` saved in `activity_state.json`, and appends one row per group message
  to `activity_log.csv` (`iso_time, week_monday, user_id, display_name, type, is_reply,
  reply_to_user_id`). `type` ∈ video/voice/text/other; bot messages and other chats are
  skipped. The workflow **commits the log + state back to the repo** (concurrency-guarded)
  so state persists across stateless runs — this is why `activity_log.csv` and
  `activity_state.json` are intentionally NOT gitignored, and why the repo must be private.
- **`send_weekly_awards.py`** (Monday via `awards.yml`) — reads the rows for the
  *previous* week (`monday_of(today) - 7d`), tallies per `awards.csv` metric
  (video / voice / social), picks the top user per award, and sends `sendAnimation` (GIF
  from `badges/`) + caption + an inline URL button. Social = most replies-to-others,
  falling back to most messages.

`awards.csv` columns: `key, metric, gif, message, badge_type`. `message` uses `{name}`;
`badge_type` must match a key in the mini app and becomes the button's `?type=` param.

The button URL is `BADGE_APP_URL` (Actions *variable*, not secret) + `/?type=<badge_type>`,
defaulting to the GitHub Pages URL in `DEFAULT_BADGE_APP_URL`.

**Badge avatar mini app** (`docs/`, served by GitHub Pages from `/docs`): a static
`index.html` that reads `?type=`, lets the winner upload a photo, composites it under a
badge ring on a `<canvas>`, and offers a download. It draws a coloured ring + emoji by
default; if `docs/frames/<type>.png` exists it's overlaid instead. No server.

**Critical external setup** (see [AWARDS_GUIDE.md](AWARDS_GUIDE.md)): the bot's privacy
mode must be **disabled in @BotFather** (or bot made admin) or it sees no messages and all
counts are empty; repo must be **private**; GitHub Pages must be enabled on `/docs`.

## Conventions

- Console output is reconfigured to UTF-8 at startup so emoji captions don't crash on
  Windows cp1252. Telegram payloads are always UTF-8 regardless.
- Never commit real tokens. `.env` is gitignored; `run_local.bat` ships with
  placeholders; GitHub uses repo secrets.
