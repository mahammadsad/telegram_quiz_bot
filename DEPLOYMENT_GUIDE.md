# স্থাপনার গাইড (Deployment Guide) — WB Exam Quiz Bot

This walks you through everything from zero to a live, self-running bot.
Total cost: ₹0 / $0. Nothing to keep running on your own machine.

---

## 0. How the pieces fit together (read this first)

```
GitHub Actions (free cron)
   │
   ├── Sunday 8:00 PM IST ──> bot.py --mode announce
   │                              │
   │                              ├─ 0. Asks Gemini to write next week's
   │                              │      chapters (syllabus_state.json holds
   │                              │      history so it never repeats itself)
   │                              ├─ 1. Posts syllabus text to Telegram
   │                              └─ 2. Commits syllabus_state.json back to
   │                                     the repo automatically (last step
   │                                     in quiz_scheduler.yml) — nobody
   │                                     touches this file, ever
   │
   └── Mon–Sat 6:30 PM IST ─> bot.py --mode quiz
                                  │
                                  ├─ 1. Looks up today's chapter from
                                  │      syllabus_state.json (self-heals /
                                  │      generates it via Gemini if the
                                  │      Sunday job hasn't run yet)
                                  ├─ 2. Asks Gemini for 10 Bengali MCQs (strict JSON)
                                  ├─ 3. Compresses + Base64-encodes that JSON
                                  ├─ 4. Posts to Telegram group: message + button
                                  │       button URL = your-github-pages-url?data=<encoded>
                                  │
                                  └─ Student taps the button
                                          │
                                          ▼
                              GitHub Pages: index.html
                              (decodes ?data=, renders quiz,
                               grades it — 100% in the browser,
                               no server involved at all)
```

There is no recurring manual step anywhere in this loop. The only things
you ever touch by hand are the one-time setup steps below (get keys, add
secrets) — never anything that repeats week to week.

**Two things worth knowing before you deploy**, because they shaped a couple
of decisions in the code:

- **The quiz button is a plain link button, not a Telegram "Web App" button.**
  Telegram only allows `web_app`-type buttons in private chats with a bot —
  never in groups. A normal `url` button pointing straight at your GitHub
  Pages link works everywhere (groups, channels, private chats), so that's
  what `bot.py` sends. It opens inside Telegram's built-in browser, which
  looks and feels like a Mini App for this purpose.
- **The quiz data is gzip-compressed before it's Base64-encoded.** Telegram's
  official "Direct Link Mini App" mechanism caps custom data at 512
  characters — nowhere near enough for 10 MCQs. Raw Base64 JSON would also
  work but makes for a needlessly long URL (~6–7k characters for 10
  questions with explanations). Compressing first brings that down to
  roughly 1,500–2,000 characters, which is comfortably safe everywhere.

---

## 1. Prerequisites

- A GitHub account (free)
- A Telegram account, and a group you admin (or can add a bot to)
- A Google account (for the free Gemini API key)

---

## 2. Create your Telegram bot

1. Open Telegram, search for **@BotFather**, start a chat.
2. Send `/newbot`, follow the prompts (choose a name and a `...bot` username).
3. BotFather replies with a **token** — looks like `123456789:AAH...`. Save it,
   this is your `TELEGRAM_BOT_TOKEN`.
4. Add your new bot to the Telegram **group** where you want quizzes posted.
   A bot can send messages to a group as soon as it's a member — it does
   **not** need to be an admin, unless your group is set so that only admins
   can post (in which case, promote it to admin).

---

## 3. Get your group's chat ID

`TELEGRAM_CHAT_ID` is a negative number for groups (e.g. `-1001234567890`).

Easiest way:
1. Send any message in the group.
2. Visit this URL in your browser (replace `<TOKEN>` with your bot token):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Look for `"chat":{"id":-100...` in the JSON response — that number is
   your chat ID.

(If you see an empty result, send a fresh message in the group first, then
reload the URL — Telegram only shows recent updates.)

---

## 4. Get a Gemini API key

1. Go to <https://aistudio.google.com/app/apikey>.
2. Create an API key (no credit card needed for the free tier).
3. Save it — this is your `GEMINI_API_KEY`.
4. Free tier as of mid-2026 is roughly 10–15 requests/minute and ~1,000+
   requests/day on `gemini-3.5-flash` — this bot uses **one** request per day,
   so you'll never come close to the limit. If Google ever renames/retires
   this model, check <https://ai.google.dev/gemini-api/docs/models> and
   update the `GEMINI_MODEL` constant near the top of `bot.py`.

---

## 5. Create the GitHub repository

1. Create a new **public** repository (Pages' free tier requires public,
   unless you have GitHub Pro/Team/Enterprise for private Pages).
2. Upload these files, keeping the folder structure exactly as given:
   ```
   your-repo/
   ├── bot.py
   ├── requirements.txt
   ├── index.html
   └── .github/
       └── workflows/
           └── quiz_scheduler.yml
   ```

---

## 6. Enable GitHub Pages

1. In your repo: **Settings → Pages**.
2. Under "Build and deployment" → Source, choose **Deploy from a branch**.
3. Branch: `main` (or whichever branch you pushed to), folder: `/ (root)`.
4. Save. GitHub gives you a URL like:
   `https://your-username.github.io/your-repo/`
5. Your quiz page will be at:
   `https://your-username.github.io/your-repo/index.html`
   This is your `QUIZ_PAGE_URL`. It can take a minute or two to go live the
   first time.

---

## 7. Let the workflow commit its own syllabus updates (one-time, 30 seconds)

This is what lets Gemini's weekly syllabus save itself back into the repo
with zero manual editing, ever. You only do this once, right now:

1. In your repo: **Settings → Actions → General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Click **Save**.

(Without this, the last step of `quiz_scheduler.yml` — the one that commits
`syllabus_state.json` — will fail with a permission error every run.)

---

## 8. Add your Secrets and Variables

In your repo: **Settings → Secrets and variables → Actions**.

Under the **Secrets** tab, add these (click "New repository secret" for each):

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | from Step 4 |
| `TELEGRAM_BOT_TOKEN` | from Step 2 |
| `TELEGRAM_CHAT_ID` | from Step 3 |

Under the **Variables** tab (same page, next to Secrets), add:

| Name | Value |
|---|---|
| `QUIZ_PAGE_URL` | your Pages URL from Step 6, e.g. `https://your-username.github.io/your-repo/index.html` |

(`QUIZ_PAGE_URL` isn't sensitive, so it's a Variable rather than a Secret —
either would technically work, but Variables are the right place for
non-secret config.)

---

## 9. Test it before trusting the schedule

1. Go to the **Actions** tab in your repo.
2. Click **WB Exam Quiz Bot Scheduler** in the left sidebar.
3. Click **Run workflow** (this exists because of `workflow_dispatch` in the
   YAML) → **Run workflow** again to confirm.
4. Watch the run. If it succeeds, check your Telegram group for the quiz
   message, tap the button, and confirm the quiz opens and works end to end.
5. If it fails, click into the run to read the error — the most common
   first-time issues are a missing/misnamed secret, or the bot not yet
   being a member of the group.

---

## 10. Adjust the schedule / timezone (optional)

The two `cron:` lines in `.github/workflows/quiz_scheduler.yml` are in UTC.
IST is UTC+5:30. Use <https://crontab.guru> to build/check any expression.
If you change the cron lines, update the matching `if: github.event.schedule
== '...'` line in the same file so it still matches — they have to stay in
sync (this is a GitHub Actions quirk: the schedule step needs to know which
cron fired).

---

## 11. The weekly syllabus — fully automatic, nothing to maintain

There is no `WEEKLY_SYLLABUS` dictionary to edit anymore, and no recurring
step here at all. Here's what runs the show instead:

- **Monday–Friday subjects are a fixed timetable** (History, Geography,
  General Science, Math, Polity — set once in `SUBJECTS_MON_TO_FRI` in
  `bot.py`, like a school routine). Saturday is always Current Affairs.
- **The actual chapter under each subject is chosen by Gemini**, every
  week, inside `generate_weekly_chapters()`. It's told what's already been
  covered (from `syllabus_state.json`) so it progresses through the real
  WBCS/WBPSC syllabus instead of repeating a topic.
- **`syllabus_state.json` is the bot's memory.** It holds the current
  week's chapters plus a rolling ~20-week history per subject. The Sunday
  job generates it, and the last step of `quiz_scheduler.yml` commits it
  back to the repo automatically (that's why Step 7 exists). If that job
  ever fails to run, the Mon–Sat quiz job self-heals: it generates the
  week itself the moment it notices one is missing.
- **You never open this file.** If you ever do want to nudge things —
  say, switch the exam focus from WBCS to a different upcoming exam — you
  can edit the `exam_focus` value inside `syllabus_state.json` once, but
  that's an optional creative choice, not required maintenance.

---

## 12. Alternative scheduler: always-on `schedule` library (Method B)

If you'd rather run this on a machine that's on 24/7 (a VPS, Raspberry Pi,
old laptop, Oracle Cloud free-tier VM, etc.) instead of GitHub Actions:

```bash
export GEMINI_API_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export QUIZ_PAGE_URL=...
export TZ=Asia/Kolkata
python bot.py --mode daemon
```

This runs the classic `schedule.every()...do(...)` loop from `bot.py`
forever, checking every 30 seconds whether it's time to post. Use a process
manager (`systemd`, `pm2`, `screen`/`tmux`, or Docker with `restart:
always`) so it survives reboots/crashes. This mode is **not** compatible
with GitHub Actions — Actions kills the runner the moment the script would
otherwise loop forever, so Method A (Section 9) is what actually runs on
GitHub's infrastructure. In this mode `syllabus_state.json` just persists
on the machine's local disk — there's no git commit step, and none is
needed since the process never restarts from a clean checkout.

---

## 13. Troubleshooting

**"Telegram API error on sendMessage: ... can't parse entities"**
Some dynamic text (a chapter name with `&`, `<`, etc.) broke HTML parsing.
`bot.py` already escapes all dynamic text with `esc()` before inserting it
into `parse_mode="HTML"` messages — if you add new dynamic fields, wrap them
in `esc()` too.

**Gemini returns a 429 / rate-limit error**
`bot.py` retries automatically with exponential backoff (`retry_with_backoff`).
This bot makes one Gemini call per day, so hitting the free tier's actual
daily/per-minute limits would be very unusual — a 429 here is more likely a
transient hiccup that the retry logic already handles.

**The quiz button doesn't do anything / opens a blank page**
Check that `QUIZ_PAGE_URL` (the repo Variable) exactly matches your live
GitHub Pages URL, including `/index.html` at the end, and that Pages has
finished deploying (Settings → Pages will show "Your site is live at...").

**"চ্যাপ্টার" / Bengali text shows as boxes or "?"**
This would be a font-loading issue in the visiting browser, not the bot —
`index.html` already loads Hind Siliguri/Tiro Bangla from Google Fonts, which
covers this. Make sure the deployed `index.html` still has the
`fonts.googleapis.com` `<link>` tags intact.

**Scheduled runs seem a bit late**
GitHub's free scheduled workflows are best-effort and can fire up to
roughly 30 minutes late under load — this is normal GitHub behavior, not a
bug in this project.

**"Commit updated syllabus state" step fails with a permission/403 error**
Step 7 (Settings → Actions → General → Workflow permissions → "Read and
write permissions") hasn't been set, or was reset after a repo setting
changed. Re-check that setting — this is the only thing that step needs.

**Sunday's post looks fine but the syllabus repeats a chapter from a
few weeks ago**
Not a bug — after ~20 weeks, `syllabus_state.json` intentionally lets a
subject's history "age out" so chapters can resurface for spaced revision,
rather than the bot eventually running out of never-used topics.
