# স্থাপনার গাইড (Deployment Guide) — WB Exam Quiz Bot

This walks you through everything from zero to a live, self-running bot —
now with a proper Telegram **Mini App** (button opens instantly, no "open
link?" step) and a live **Top 20 leaderboard**.

Total cost: ₹0 / $0, no credit card anywhere. Nothing to keep running on
your own machine.

> **Upgrading an existing install?** Jump to [Section 14](#14-upgrading-from-the-old-url-button-version).
> It's three things: register a Mini App, add Firebase, update your repo's
> Variables. Everything else (Gemini key, bot token, chat id) stays the same.

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
                                  ├─ 3. Writes quizzes/<id>.json — a small
                                  │      plain file, committed to the repo
                                  ├─ 4. Posts to Telegram group: message + button
                                  │       button URL = https://t.me/<bot>/<app>?startapp=<id>
                                  │
                                  └─ Student taps the button
                                          │
                                          ▼
                              Telegram opens the Mini App DIRECTLY
                              (no external-link warning — this is a
                              t.me/ link, so Telegram recognizes it as
                              its own Mini App launcher)
                                          │
                                          ▼
                              GitHub Pages: index.html
                              (reads the id from start_param, fetches
                              quizzes/<id>.json, renders/grades the quiz
                              in the browser, then writes the score
                              straight to Firestore for the leaderboard)
                                          │
                                          ▼
                              dashboard.html — Top 20, live, for everyone
```

There is no recurring manual step anywhere in this loop. The only things
you ever touch by hand are the one-time setup steps below (get keys, add
secrets, register the Mini App, create the Firebase project) — never
anything that repeats week to week.

**A few things worth knowing before you deploy:**

- **The quiz button is a Telegram Mini App direct link, not a plain URL
  button.** Regular `url`-type inline buttons pointing at an external site
  make Telegram show an "open this link?" confirmation and then open it in
  a generic in-app browser — that's the old behavior. A link in the form
  `https://t.me/<bot>/<shortname>?startapp=<id>` is different: Telegram
  recognizes `t.me/` as its own domain and opens the Mini App natively,
  full-screen, with no external-link step. Getting this requires a
  one-time `/newapp` registration with @BotFather (Section 6).
- **The quiz data lives in a small file, not the URL.** Telegram caps the
  Mini App `startapp` parameter at 512 characters, and a 10-question quiz
  with explanations is comfortably longer than that even compressed. So
  `bot.py` now writes `quizzes/<id>.json` (a plain, uncompressed file) and
  the button just carries that short id.
- **The leaderboard is genuinely optional.** If you skip the Firebase
  section, the quiz still works perfectly end-to-end — score-saving just
  quietly does nothing, and `dashboard.html` shows a friendly "not set up
  yet" message instead of a list.
- **There's no server verifying who's who.** Scores are written straight
  from the student's browser to Firestore, trusting whatever Telegram's
  own Mini App SDK reports as the logged-in user. There's no login, no
  password, nothing to phish — but a technically-inclined student could in
  theory open devtools and fake a better score. For a friendly study-group
  leaderboard that's a reasonable trade-off; see `firestore.rules` if you
  want to reason about it further.

---

## 1. Prerequisites

- A GitHub account (free)
- A Telegram account, and a group you admin (or can add a bot to)
- A Google account (used for both the free Gemini API key and the free
  Firebase project — one login covers both)

---

## 2. Create your Telegram bot

1. Open Telegram, search for **@BotFather**, start a chat.
2. Send `/newbot`, follow the prompts (choose a name and a `...bot` username).
3. BotFather replies with a **token** — looks like `123456789:AAH...`. Save it,
   this is your `TELEGRAM_BOT_TOKEN`.
4. Also note the bot's **username** (the `...bot` part, without the `@`) —
   this is your `TELEGRAM_BOT_USERNAME`, used in Section 6.
5. Add your new bot to the Telegram **group** where you want quizzes posted.
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
   ├── dashboard.html
   ├── firestore.rules          (reference copy — the real rules live in
   │                              the Firebase console, Section 7)
   └── .github/
       └── workflows/
           └── quiz_scheduler.yml
   ```
   (`quizzes/` doesn't need to exist yet — `bot.py` creates it automatically
   the first time it runs.)

---

## 6. Register your Mini App with BotFather

This is the step that fixes the "shows a link, then I have to click it
again" problem — it turns your page into a real Telegram Mini App instead
of a plain external webpage.

1. Message **@BotFather**, send `/newapp`.
2. Pick your bot from the list.
3. Give it a title (e.g. "দৈনিক মক টেস্ট") and a short description.
4. Upload a simple square photo when asked (any icon works — BotFather
   requires one).
5. **Web App URL**: your GitHub Pages URL for `index.html`, e.g.
   `https://your-username.github.io/your-repo/index.html` (Section 8 shows
   you exactly where to find this).
6. **Short name**: pick something short, lowercase, e.g. `quiz`. This is
   your `MINIAPP_SHORT_NAME`.
7. BotFather confirms and shows you the direct link format — it will look
   like `https://t.me/your_bot/quiz`. You don't need to save this link
   itself; `bot.py` builds it automatically from `TELEGRAM_BOT_USERNAME` +
   `MINIAPP_SHORT_NAME` (Section 9).

If you ever change your GitHub Pages URL later, come back to @BotFather →
`/myapps` → your app → edit the Web App URL to match.

---

## 7. Set up Firebase (for the Top 20 leaderboard)

1. Go to <https://console.firebase.google.com>, sign in with the same
   Google account as Section 4, click **Add project**. Name it anything
   (e.g. `wb-quiz-bot`). Google Analytics is not needed — you can leave it off.
2. Once the project is created: left sidebar → **Build → Firestore
   Database** → **Create database** → start in **production mode** → pick
   any nearby region → **Enable**.
3. Go to the **Rules** tab of Firestore, delete the default contents, and
   paste in everything from `firestore.rules` (included in this repo) →
   **Publish**.
4. Register a **Web app**: on the project's main page (⚙️ → Project
   settings, or the `</>` icon on the overview page) → **Add app → Web**.
   Give it any nickname (e.g. "quiz page") → **Register app**. Firebase
   Hosting is not needed — skip that checkbox if offered.
5. Firebase now shows you a `firebaseConfig` object like:
   ```js
   const firebaseConfig = {
     apiKey: "AIza...",
     authDomain: "wb-quiz-bot-xxxxx.firebaseapp.com",
     projectId: "wb-quiz-bot-xxxxx",
     storageBucket: "wb-quiz-bot-xxxxx.appspot.com",
     messagingSenderId: "...",
     appId: "1:...:web:..."
   };
   ```
   This is **not secret** — it's meant to be public in client-side code
   (Firestore's actual protection is the Rules from step 3, not this
   object). Copy these six values.
6. Open **both** `index.html` and `dashboard.html` in your repo, find the
   `firebaseConfig` object near the top of the `<script>` block (search for
   `PASTE_YOUR`), and paste your six real values in, replacing the
   placeholders — in both files, since they're separate static pages.

That's it — no Cloud Functions, no service account, no billing setup. The
free "Spark" plan comfortably covers a study-group-sized quiz bot (50,000
Firestore reads/day, 20,000 writes/day, no card required).

---

## 8. Enable GitHub Pages

1. In your repo: **Settings → Pages**.
2. Under "Build and deployment" → Source, choose **Deploy from a branch**.
3. Branch: `main` (or whichever branch you pushed to), folder: `/ (root)`.
4. Save. GitHub gives you a URL like:
   `https://your-username.github.io/your-repo/`
5. Your quiz page will be at:
   `https://your-username.github.io/your-repo/index.html`
   This is the URL you pasted into BotFather in Section 6. It can take a
   minute or two to go live the first time.

---

## 9. Let the workflow commit its own generated files (one-time, 30 seconds)

This is what lets Gemini's weekly syllabus *and* each day's quiz file save
themselves back into the repo with zero manual editing, ever.

1. In your repo: **Settings → Actions → General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**.
4. Click **Save**.

(Without this, the last step of `quiz_scheduler.yml` — the one that commits
`syllabus_state.json` and `quizzes/*.json` — will fail with a permission
error every run.)

---

## 10. Add your Secrets and Variables

In your repo: **Settings → Secrets and variables → Actions**.

Under the **Secrets** tab, add these (click "New repository secret" for each):

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | from Section 4 |
| `TELEGRAM_BOT_TOKEN` | from Section 2 |
| `TELEGRAM_CHAT_ID` | from Section 3 |

Under the **Variables** tab (same page, next to Secrets), add:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_USERNAME` | your bot's username from Section 2, **without** the `@`, e.g. `wb_quiz_bot` |
| `MINIAPP_SHORT_NAME` | the short name you gave BotFather in Section 6, e.g. `quiz` |

(Neither of these is sensitive — a bot's username and Mini App short name
are public by nature — so they're Variables, not Secrets. There's no
`QUIZ_PAGE_URL` anymore; the new flow doesn't need your Pages URL at
runtime.)

---

## 11. Test it before trusting the schedule

1. Go to the **Actions** tab in your repo.
2. Click **WB Exam Quiz Bot Scheduler** in the left sidebar.
3. Click **Run workflow** → choose `quiz` from the dropdown → **Run workflow**
   again to confirm.
4. Watch the run. If it succeeds, check your Telegram group: tap the quiz
   button and confirm it opens **directly**, full-screen, with no "open
   link?" step in between.
5. Finish the quiz, then tap **🏆 লিডারবোর্ড দেখো** — you should see yourself
   appear at the top of an otherwise-empty Top 20.
6. If it fails, click into the run to read the error — common first-time
   issues: a missing/misnamed secret or variable, the bot not yet being a
   member of the group, or the Mini App / Firebase steps not finished yet.

---

## 12. Adjust the schedule / timezone (optional)

The two `cron:` lines in `.github/workflows/quiz_scheduler.yml` are in UTC.
IST is UTC+5:30. Use <https://crontab.guru> to build/check any expression.
If you change the cron lines, update the matching `if [ "${{ github.event.schedule }}" = '...' ]`
line in the same file so it still matches — they have to stay in sync
(this is a GitHub Actions quirk: the schedule step needs to know which cron
fired).

---

## 13. The weekly syllabus — fully automatic, nothing to maintain

There is no `WEEKLY_SYLLABUS` dictionary to edit, and no recurring step
here at all. Here's what runs the show instead:

- **Monday–Friday subjects are a fixed timetable** (History, Geography,
  General Science, Math, Polity — set once in `SUBJECTS_MON_TO_FRI` in
  `bot.py`, like a school routine). Saturday is always Current Affairs.
- **The actual chapter under each subject is chosen by Gemini**, every
  week, inside `generate_weekly_chapters()`. It's told what's already been
  covered (from `syllabus_state.json`) so it progresses through the real
  WBCS/WBPSC syllabus instead of repeating a topic.
- **`syllabus_state.json` is the bot's syllabus memory.** `quizzes/*.json`
  is a second, simpler kind of memory — one small file per day's quiz,
  kept forever (a year of them is well under a megabyte total). The Sunday
  job generates the syllabus, the Mon–Sat job generates each day's quiz
  file, and the last step of `quiz_scheduler.yml` commits both back to the
  repo automatically (that's why Section 9 exists). If the Sunday job ever
  fails to run, the Mon–Sat quiz job self-heals: it generates the week
  itself the moment it notices one is missing.
- **You never open these files.** If you ever do want to nudge things —
  say, switch the exam focus from WBCS to a different upcoming exam — you
  can edit the `exam_focus` value inside `syllabus_state.json` once, but
  that's an optional creative choice, not required maintenance.

---

## 14. Upgrading from the old `?data=` URL-button version

If you had the previous version running, here's the complete list of what
changed and what you need to do:

1. **Do Section 6** (register the Mini App with BotFather) — new, required.
2. **Do Section 7** (create the Firebase project, paste the config into
   both HTML files) — new, optional but recommended.
3. **Replace** `bot.py`, `index.html`, `dashboard.html` (new file),
   `firestore.rules` (new file), and `.github/workflows/quiz_scheduler.yml`
   with the versions here.
4. **In repo Variables**, remove `QUIZ_PAGE_URL` (no longer used) and add
   `TELEGRAM_BOT_USERNAME` + `MINIAPP_SHORT_NAME` (Section 10).
5. Old quiz messages already sitting in your Telegram group keep working —
   `index.html` still recognizes the old `?data=` link format as a
   fallback, it just won't have a leaderboard entry (there's no id to key
   it by). Only new quizzes posted after the upgrade use the Mini App +
   Firestore flow.
6. If your existing workflow file had any custom steps beyond what's
   described in Section 0, merge them into the new `quiz_scheduler.yml`
   yourself — it was rebuilt from this guide's own description rather than
   from your actual file, since that wasn't available when this update was
   written.

---

## 15. Alternative scheduler: always-on `schedule` library (Method B)

If you'd rather run this on a machine that's on 24/7 (a VPS, Raspberry Pi,
old laptop, Oracle Cloud free-tier VM, etc.) instead of GitHub Actions:

```bash
export GEMINI_API_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export TELEGRAM_BOT_USERNAME=...
export MINIAPP_SHORT_NAME=...
export TZ=Asia/Kolkata
python bot.py --mode daemon
```

This runs the classic `schedule.every()...do(...)` loop from `bot.py`
forever, checking every 30 seconds whether it's time to post. Use a process
manager (`systemd`, `pm2`, `screen`/`tmux`, or Docker with `restart:
always`) so it survives reboots/crashes. This mode is **not** compatible
with GitHub Actions — Actions kills the runner the moment the script would
otherwise loop forever, so Method A (Section 11) is what actually runs on
GitHub's infrastructure. In this mode `syllabus_state.json` and `quizzes/`
just persist on the machine's local disk — there's no git commit step, and
none is needed since the process never restarts from a clean checkout.
(You'd need to serve `index.html`/`dashboard.html`/`quizzes/` yourself in
this mode too, e.g. with a simple `nginx` or `caddy` in front of the same
folder — GitHub Pages is what serves them in Method A.)

---

## 16. Troubleshooting

**The quiz button still shows an "open link?" step, or opens a blank/plain
browser page instead of the app**
Almost always one of: (a) the Mini App wasn't actually registered — redo
Section 6 and double check `/myapps` in BotFather shows it; (b)
`TELEGRAM_BOT_USERNAME` or `MINIAPP_SHORT_NAME` (repo Variables) don't
exactly match what BotFather has — no `@`, no typos; (c) the Web App URL
saved in BotFather doesn't match your live GitHub Pages URL.

**"App not found" / Telegram says the Mini App doesn't exist**
The bot username or short name in the link doesn't match a registered app —
check `/myapps` in BotFather, and check the two repo Variables in Section 10.

**Leaderboard shows "not set up yet" / permission-denied in the console**
Either the `firebaseConfig` placeholders in `index.html`/`dashboard.html`
still say `PASTE_YOUR...` (Section 7, step 6), or the Firestore Rules
haven't been published yet (Section 7, step 3).

**Leaderboard is empty even after finishing a quiz**
Check the browser/Telegram console for errors. The most common cause is
Firestore Rules not yet published, or a typo in one of the six
`firebaseConfig` values (all six must match exactly, or `initializeApp`
silently fails). If the console specifically shows `permission-denied` and
Section 7's steps all look right, `firestore.rules`' validation of the
`leaderboard` collection checks the *result* of the `increment()` calls —
this is standard, well-supported Firestore behavior, but if it ever gives
you trouble, temporarily loosen that one rule to just
`allow write: if request.resource.data.name is string;`, confirm scores
start appearing, then tighten it back once you've confirmed the shape of
what's actually being written.

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

**"চ্যাপ্টার" / Bengali text shows as boxes or "?"**
This would be a font-loading issue in the visiting browser, not the bot —
`index.html`/`dashboard.html` load Noto Sans Bengali + Tiro Bangla from
Google Fonts, which cover this well. Make sure the deployed files still
have the `fonts.googleapis.com` `<link>` tags intact, and that you didn't
strip the `<script src="https://telegram.org/js/...">` tag (losing that
also breaks the Mini App bridge entirely, not just fonts).

**Scheduled runs seem a bit late**
GitHub's free scheduled workflows are best-effort and can fire up to
roughly 30 minutes late under load — this is normal GitHub behavior, not a
bug in this project.

**"Commit generated quiz + syllabus files" step fails with a
permission/403 error**
Section 9 (Settings → Actions → General → Workflow permissions → "Read and
write permissions") hasn't been set, or was reset after a repo setting
changed. Re-check that setting — this is the only thing that step needs.

**Sunday's post looks fine but the syllabus repeats a chapter from a
few weeks ago**
Not a bug — after ~20 weeks, `syllabus_state.json` intentionally lets a
subject's history "age out" so chapters can resurface for spaced revision,
rather than the bot eventually running out of never-used topics.
