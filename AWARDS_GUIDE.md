# Weekly Awards — setup & how it works

Every Monday this posts award GIFs to the group celebrating last week's top
contributors (🦈 Video Shark, 🎙️ Voice Legend, 🦋 Social Butterfly), each with a
button that opens a page where the winner makes a profile picture with their
badge.

Winners are **computed automatically** from what people actually posted. That
needs the bot to watch the group all week, so there are two moving parts:

- **Logger** (`log_activity.py`) — runs every hour, records who posted what.
- **Poster** (`send_weekly_awards.py`) — runs Monday, tallies last week, posts.

---

## One-time setup

### 1. Let the bot see every message
By default a Telegram bot only sees messages that mention it, so it can't count
activity. Fix this once:

- In Telegram, message **@BotFather** → `/setprivacy` → pick your bot → **Disable**.
- (Alternatively, make the bot a group **admin** — admins see all messages.)

Without this the counts will be empty or wrong.

### 2. Make the repo private
The activity log stores members' names and what they posted. In GitHub:
**Settings → General → Danger Zone → Change visibility → Private.**

### 3. Turn on the badge avatar page (GitHub Pages)
- **Settings → Pages → Build and deployment → Source: Deploy from a branch.**
- Branch: `main`, folder: **`/docs`** → Save.
- After a minute your page is live at
  `https://<you>.github.io/<repo>/` (for this repo:
  `https://mehinewe.github.io/weekly-topic-telegram/`).
- If your URL differs, set it so the buttons point to the right place:
  **Settings → Secrets and variables → Actions → Variables → New variable**
  named `BADGE_APP_URL` with your Pages URL.

### 4. Add the award GIFs
Drop one animated file per award into **`badges/`**, named to match `awards.csv`:
`video_shark.gif`, `voice_legend.gif`, `social_butterfly.gif` (`.mp4`/`.webp`
also fine). Until they're there, the Monday run skips that award with a warning.

### 5. (Optional) Real badge artwork
The avatar page works out of the box by drawing a coloured ring + emoji. To use
custom art, add transparent square PNGs to **`docs/frames/`**: `shark.png`,
`microphone.png`, `butterfly.png` (see that folder's README).

The same `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` repo secrets used by the
weekly topic poster are reused here — nothing new to add.

---

## How winners are decided
Computed from `activity_log.csv` for the **previous** week (Mon–Sun):

| Award | Metric |
|---|---|
| 🦈 Video Shark | most `video` + video-bubble messages |
| 🎙️ Voice Legend | most `voice` messages |
| 🦋 Social Butterfly | most **replies to other people** (falls back to most messages if nobody replied) |

Ties break deterministically; an award with no activity is silently skipped.
Counting only starts once the logger is live — **the first week may be thin**,
since Telegram gives the bot no history.

---

## Editing the award text
Edit **`awards.csv`** (columns `key, metric, gif, message, badge_type`). Use
`{name}` where the winner's name should go; wrap the message in `"double quotes"`;
multiple lines and emoji are fine. `badge_type` must match a key in the avatar
page (`shark`, `microphone`, `butterfly`).

## Preview before it posts
GitHub → **Actions** → **Weekly awards** → **Run workflow** → leave **Dry run**
ticked. It prints who *would* win without posting. Locally:

```
python send_weekly_awards.py --dry-run            # last week
python send_weekly_awards.py 2026-06-22 --dry-run # pretend today is that Monday
```

## Troubleshooting
- **Everyone has 0 activity** → bot privacy mode is still on (step 1), or the
  logger hasn't been running. Check the **Log group activity** workflow runs.
- **An award didn't post** → its GIF is missing from `badges/`, or nobody did
  that activity last week. The Monday run log says which.
- **Button opens the wrong page** → set the `BADGE_APP_URL` Actions variable
  (step 3).
