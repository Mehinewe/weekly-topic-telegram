"""
Weekly Awards — Monday poster
=============================

Reads the activity log built up by `log_activity.py`, finds last week's top
contributor in each award category, and posts a celebratory GIF + message with
a "Get Your Badge Avatar" button to the Telegram group.

Run manually for testing:
    python send_weekly_awards.py --dry-run        # show who would win, send nothing
    python send_weekly_awards.py 2026-06-22 --dry-run   # pretend "today" is that date
    python send_weekly_awards.py                  # real post for last week

Award winners are computed from `activity_log.csv`:
    🦈 Video Shark      — most videos + video bubbles
    🎙️ Voice Legend     — most voice messages
    🦋 Social Butterfly — most replies to other people (falls back to most
                          messages if nobody replied)

Required environment variables (real send only):
    TELEGRAM_BOT_TOKEN   the token from @BotFather
    TELEGRAM_CHAT_ID     the group's chat id (negative number)
    BADGE_APP_URL        (optional) base URL of the badge avatar mini app;
                         defaults to the GitHub Pages URL below.
"""

import csv
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# --- Configuration --------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "activity_log.csv"
AWARDS_FILE = BASE_DIR / "awards.csv"
BADGES_DIR = BASE_DIR / "badges"

# Where the badge-avatar mini app is hosted (GitHub Pages). The award button
# links here with ?type=<badge_type>. Override with the BADGE_APP_URL env var.
DEFAULT_BADGE_APP_URL = "https://mehinewe.github.io/weekly-topic-telegram/"

CAPTION_LIMIT = 1024
API_TIMEOUT = 30

# Which message types count toward each metric.
VIDEO_TYPES = {"video"}
VOICE_TYPES = {"voice"}


# --- Helpers --------------------------------------------------------------

def load_dotenv():
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
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def monday_of(d):
    return d - timedelta(days=d.weekday())


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")


def _parse_date(date_str):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


ANIMATED_EXTS = (".gif", ".mp4", ".webp")
IMAGE_EXTS = (".png", ".jpg", ".jpeg")


def resolve_media(name):
    """Find the badge file for `name` in badges/, tolerating the extension.

    Accepts both animations (.gif/.mp4/.webp) and plain images (.png/.jpg), so
    a static badge picture works just as well as an animated one. A CSV that
    says shark.gif still matches shark.png on disk.
    """
    exact = BADGES_DIR / name
    if exact.exists():
        return exact
    stem = Path(name).stem
    for candidate in sorted(BADGES_DIR.glob(stem + ".*")):
        if candidate.suffix.lower() in ANIMATED_EXTS + IMAGE_EXTS:
            return candidate
    return None


def load_awards():
    """Read awards.csv into a list of template dicts."""
    if not AWARDS_FILE.exists():
        _fail(f"awards file not found: {AWARDS_FILE}")
    awards = []
    with AWARDS_FILE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"key", "metric", "gif", "message", "badge_type"}
        if not required.issubset(set(reader.fieldnames or [])):
            _fail(
                "awards.csv must have columns: key, metric, gif, message, "
                f"badge_type (found: {reader.fieldnames})"
            )
        for raw in reader:
            key = (raw.get("key") or "").strip()
            if not key:
                continue
            awards.append({
                "key": key,
                "metric": (raw.get("metric") or "").strip().lower(),
                "gif": (raw.get("gif") or "").strip(),
                "message": (raw.get("message") or "").strip(),
                "badge_type": (raw.get("badge_type") or "").strip(),
            })
    if not awards:
        _fail("awards.csv has no usable rows")
    return awards


def load_week_rows(week_monday):
    """Return the logged rows for the given week (Monday date)."""
    if not LOG_FILE.exists():
        _fail(
            f"activity log not found: {LOG_FILE}. The logger "
            "(log_activity.py) must run for a week before awards can post."
        )
    wanted = week_monday.isoformat()
    rows = []
    with LOG_FILE.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("week_monday") == wanted:
                rows.append(row)
    return rows


def resolve_name(token, chat_id, user_id, _cache={}):
    """Look up a member's current display name live via getChatMember.

    The activity log stores only anonymous numeric ids, so names are fetched
    here, only for the handful of winners, right before posting. Falls back to
    "User <id>" if the lookup fails (e.g. the member left the group).
    """
    if user_id in _cache:
        return _cache[user_id]
    name = f"User {user_id}"
    try:
        url = f"https://api.telegram.org/bot{token}/getChatMember"
        resp = requests.get(
            url, params={"chat_id": chat_id, "user_id": user_id}, timeout=API_TIMEOUT
        )
        body = resp.json()
        if body.get("ok"):
            user = body["result"].get("user", {})
            first = (user.get("first_name") or "").strip()
            last = (user.get("last_name") or "").strip()
            full = (first + " " + last).strip()
            name = full or user.get("username") or name
    except (ValueError, requests.RequestException, KeyError):
        pass
    _cache[user_id] = name
    return name


def tally(rows, metric):
    """Count contributions per user for a metric. Returns a Counter."""
    counts = Counter()
    if metric == "video":
        for row in rows:
            if row.get("type") in VIDEO_TYPES:
                counts[row["user_id"]] += 1
    elif metric == "voice":
        for row in rows:
            if row.get("type") in VOICE_TYPES:
                counts[row["user_id"]] += 1
    elif metric == "social":
        for row in rows:
            if row.get("is_reply") == "1":
                counts[row["user_id"]] += 1
        if not counts:  # nobody replied — fall back to most messages overall
            for row in rows:
                counts[row["user_id"]] += 1
    else:
        _fail(f"unknown metric '{metric}' in awards.csv")
    return counts


def pick_winner(counts):
    """Return (user_id, count) for the top contributor, or None.

    Ties are broken by user_id so the result is deterministic.
    """
    if not counts:
        return None
    best = max(counts.values())
    if best <= 0:
        return None
    winners = sorted(uid for uid, c in counts.items() if c == best)
    return winners[0], best


# --- Telegram -------------------------------------------------------------

def send_badge(token, chat_id, media_path, caption, button_url):
    """Send the badge (animation or static image) with caption + inline button.

    Uses sendAnimation for .gif/.mp4/.webp and sendPhoto for .png/.jpg, so the
    award works whether you supply an animated GIF or a plain picture.
    """
    animated = media_path.suffix.lower() in ANIMATED_EXTS
    method, field = ("sendAnimation", "animation") if animated else ("sendPhoto", "photo")
    url = f"https://api.telegram.org/bot{token}/{method}"
    reply_markup = (
        '{"inline_keyboard":[[{"text":"🌟 Get Your Badge Avatar 🌟",'
        f'"url":"{button_url}"}}]]}}'
    )
    with media_path.open("rb") as media:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption, "reply_markup": reply_markup},
            files={field: media},
            timeout=API_TIMEOUT,
        )
    _check(resp, method)


def send_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url, data={"chat_id": chat_id, "text": text}, timeout=API_TIMEOUT
    )
    _check(resp, "sendMessage")


def _check(resp, what):
    try:
        body = resp.json()
    except ValueError:
        _fail(f"{what}: non-JSON response (HTTP {resp.status_code}): {resp.text[:300]}")
    if not body.get("ok"):
        _fail(f"{what} failed: {body.get('description', resp.text[:300])}")
    print(f"{what} OK")


# --- Main -----------------------------------------------------------------

def main():
    load_dotenv()

    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    date_args = [a for a in args if not a.startswith("--")]

    if date_args:
        today = _parse_date(date_args[0])
        if today is None:
            _fail(f"bad date argument '{date_args[0]}'; use YYYY-MM-DD or M/D/YYYY")
    else:
        today = date.today()

    # Awards posted this Monday celebrate the PREVIOUS week.
    last_week_monday = monday_of(today) - timedelta(days=7)

    awards = load_awards()
    rows = load_week_rows(last_week_monday)
    app_url = (os.environ.get("BADGE_APP_URL") or DEFAULT_BADGE_APP_URL).rstrip("/")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    print(f"Computing awards for week of Monday {last_week_monday} "
          f"({len(rows)} logged messages).")
    if not rows:
        print("No activity logged for that week — nothing to post.")
        return

    # Decide every winner first, so a dry run shows the full picture.
    planned = []
    for award in awards:
        result = pick_winner(tally(rows, award["metric"]))
        if result is None:
            print(f"  {award['key']}: no qualifying activity — skipping.")
            continue
        uid, count = result
        planned.append((award, uid, count))

    if not planned:
        print("No awards have a winner this week — nothing to post.")
        return

    if dry_run:
        # Names come from a live lookup, which needs a token; without one we
        # just show the anonymous id so dry runs still work offline.
        print("--- DRY RUN (nothing sent) ---")
        for award, uid, count in planned:
            name = resolve_name(token, chat_id, uid) if (token and chat_id) else f"User {uid}"
            print(f"  {award['key']}: {name} (id {uid}) — {count} — gif={award['gif']}")
            print(f"    button -> {app_url}/?type={award['badge_type']}")
        print("--- end dry run ---")
        return

    if not token:
        _fail("TELEGRAM_BOT_TOKEN is not set")
    if not chat_id:
        _fail("TELEGRAM_CHAT_ID is not set")

    for award, uid, count in planned:
        media_path = resolve_media(award["gif"])
        if media_path is None:
            print(f"  WARNING: badge file not found for {award['key']} "
                  f"({award['gif']}) — skipping this award.", file=sys.stderr)
            continue
        name = resolve_name(token, chat_id, uid)
        caption = award["message"].format(name=name)
        button_url = f"{app_url}/?type={award['badge_type']}"
        print(f"Posting {award['key']} for {name} ({count}).")
        if len(caption) <= CAPTION_LIMIT:
            send_badge(token, chat_id, media_path, caption, button_url)
        else:
            send_badge(token, chat_id, media_path, caption[:CAPTION_LIMIT], button_url)
            send_message(token, chat_id, caption[CAPTION_LIMIT:])

    print("Done.")


if __name__ == "__main__":
    main()
