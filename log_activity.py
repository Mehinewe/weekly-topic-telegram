"""
Weekly Awards — group activity logger
=====================================

Watches the Telegram group and records who posts what, so the Monday award
poster (`send_weekly_awards.py`) can tally last week's top contributors.

Telegram only keeps undelivered updates for ~24 hours and gives a bot NO access
to history, so this must run often (hourly) to catch messages before they age
out. Each run:

  1. Reads the last processed update id from `activity_state.json`.
  2. Calls getUpdates for everything newer.
  3. Appends one row per group message to `activity_log.csv`.
  4. Saves the new update id back to the state file.

The GitHub Actions workflow (`.github/workflows/log.yml`) commits the updated
log + state back to the repo after each run.

IMPORTANT: the bot must be able to SEE every group message. In @BotFather run
`/setprivacy` -> Disable for this bot (or make the bot a group admin). With
privacy mode on (the default) the bot only sees messages that mention it, and
the counts will be wrong.

Required environment variables:
    TELEGRAM_BOT_TOKEN   the token from @BotFather
    TELEGRAM_CHAT_ID     the group's chat id (negative, e.g. -1001234567890)
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# Print UTF-8 so emoji/display names don't crash the Windows console (cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# --- Configuration --------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "activity_log.csv"
STATE_FILE = BASE_DIR / "activity_state.json"

API_TIMEOUT = 60          # HTTP timeout for the whole request
GETUPDATES_LIMIT = 100    # max updates Telegram returns per call

# The log stores ONLY anonymous numeric Telegram ids — no names — so the repo
# can be public without exposing anyone. The winner's name is looked up live at
# post time (see send_weekly_awards.py).
LOG_FIELDS = [
    "iso_time",
    "week_monday",
    "user_id",
    "type",
    "is_reply",
    "reply_to_user_id",
]


# --- Helpers --------------------------------------------------------------

def load_dotenv():
    """Load KEY=VALUE pairs from a local .env into the environment, if present.

    Local convenience only; on GitHub Actions the secrets come from the
    environment. Existing environment variables are never overwritten.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _fail(message):
    """Print an error and exit non-zero so the scheduler flags the run."""
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def monday_of(d):
    """Return the Monday (date) of the week containing date `d`."""
    return d - timedelta(days=d.weekday())


def read_offset():
    """Return the next update offset to request (last id + 1), or None."""
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    last = data.get("last_update_id")
    return (last + 1) if isinstance(last, int) else None


def write_offset(last_update_id):
    """Persist the highest processed update id."""
    STATE_FILE.write_text(
        json.dumps({"last_update_id": last_update_id}, indent=2) + "\n",
        encoding="utf-8",
    )


def classify(message):
    """Return the primary activity type for a message.

    Maps to the award categories: video (incl. video bubbles) and voice get
    their own buckets; everything else is 'text'/'other' and still counts
    toward social engagement.
    """
    if "video" in message or "video_note" in message:
        return "video"
    if "voice" in message:
        return "voice"
    if "text" in message:
        return "text"
    return "other"


def fetch_updates(token, offset):
    """Fetch one batch of updates from getUpdates (short poll)."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"limit": GETUPDATES_LIMIT, "timeout": 0}
    if offset is not None:
        params["offset"] = offset
    # Only ask for the update types we care about; keeps payloads small.
    params["allowed_updates"] = json.dumps(["message"])
    resp = requests.get(url, params=params, timeout=API_TIMEOUT)
    try:
        body = resp.json()
    except ValueError:
        _fail(f"getUpdates: non-JSON response (HTTP {resp.status_code})")
    if not body.get("ok"):
        _fail(f"getUpdates failed: {body.get('description', resp.text[:300])}")
    return body.get("result", [])


# --- Main -----------------------------------------------------------------

def main():
    load_dotenv()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token:
        _fail("TELEGRAM_BOT_TOKEN is not set")
    if not chat_id:
        _fail("TELEGRAM_CHAT_ID is not set")
    try:
        target_chat = int(chat_id)
    except ValueError:
        _fail(f"TELEGRAM_CHAT_ID is not a number: {chat_id!r}")

    offset = read_offset()
    new_rows = []
    highest_id = None

    # Telegram returns at most GETUPDATES_LIMIT updates per call, so loop until
    # a batch comes back empty (or smaller than the limit).
    while True:
        updates = fetch_updates(token, offset)
        if not updates:
            break

        for upd in updates:
            update_id = upd.get("update_id")
            if isinstance(update_id, int):
                highest_id = update_id if highest_id is None else max(highest_id, update_id)
                offset = update_id + 1  # advance so the next call skips this one

            message = upd.get("message")
            if not message:
                continue

            chat = message.get("chat") or {}
            if chat.get("id") != target_chat:
                continue  # only our group

            sender = message.get("from") or {}
            if sender.get("is_bot"):
                continue  # ignore the bot's own posts (and other bots)

            sent = datetime.fromtimestamp(message.get("date", 0), tz=timezone.utc)
            reply = message.get("reply_to_message") or {}
            reply_user = (reply.get("from") or {}).get("id")
            # A reply only counts as "interacting with a classmate" if it
            # replies to someone else's message, not the user's own.
            is_reply = bool(reply) and reply_user not in (None, sender.get("id"))

            new_rows.append({
                "iso_time": sent.isoformat(),
                "week_monday": monday_of(sent.date()).isoformat(),
                "user_id": sender.get("id"),
                "type": classify(message),
                "is_reply": int(is_reply),
                "reply_to_user_id": reply_user if is_reply else "",
            })

        if len(updates) < GETUPDATES_LIMIT:
            break

    if not new_rows:
        print("No new group messages.")
        # Still persist the offset if Telegram advanced it (e.g. non-message
        # updates were drained), so we don't re-request them next time.
        if highest_id is not None and highest_id + 1 != read_offset():
            write_offset(highest_id)
        return

    write_header = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)

    if highest_id is not None:
        write_offset(highest_id)

    print(f"Logged {len(new_rows)} new message(s); offset now {highest_id}.")


if __name__ == "__main__":
    main()
