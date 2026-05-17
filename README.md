# Mano Bot

Personal WhatsApp AI assistant for Yuval (and Eden), powered by Claude.

Receives WhatsApp messages via Meta Cloud API, processes them through Claude
with tool-use for integrations (Notion, Gmail, Google Calendar, Google Drive),
and replies via WhatsApp. Hosted on Railway.

See `docs/CLAUDE.md` for the operating contract Claude Code follows in this
repo, and `docs/TASKS.md` for the build roadmap.

## Stack

- Python 3.11+
- FastAPI (webhook server)
- Anthropic SDK — model: `claude-sonnet-4-6`
- Notion API via `notion-client`
- Google APIs via `google-api-python-client` (Gmail, Calendar, Drive)
- WhatsApp via Meta Cloud API
- Hosted on Railway

## Local setup

1. Clone the repo and create a virtualenv:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
2. Install dependencies (one at a time during first setup — SentinelOne caution):
   ```powershell
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in the values.
4. Sanity-check the scaffold:
   ```powershell
   pytest --collect-only
   ```

## Running locally

Local webhook testing requires `uvicorn` + `ngrok` (🔴 high-risk on this
machine — read `docs/CLAUDE.md` first). Preferred path: deploy to Railway
and use the Railway URL in Meta webhook settings instead of ngrok.

```powershell
uvicorn main:app --reload
ngrok http 8000
```

## Railway deploy + live WhatsApp echo test

This is the preferred way to test the live webhook on this machine (avoids ngrok).
Do this after Task 2 code lands, before Task 3. Estimated time: ~10 minutes.

---

### Part A — Railway setup

**Step 1 — Create the Railway project**

1. Go to **[https://railway.app/new](https://railway.app/new)**
2. Click **"Deploy from GitHub repo"**
3. If prompted, click **"Configure GitHub App"** and grant access to the `mano-bot` repo
4. Select **`mano-bot`** from the list
5. Railway will start deploying immediately — it detects the `Procfile` automatically

**Step 2 — Generate a public domain**

1. In the Railway dashboard, click on the **`mano-bot` service** (the card that appeared after deploy)
2. Click the **"Settings"** tab
3. Scroll to **"Networking"** → click **"Generate Domain"**
4. Copy the generated URL — it will look like `https://mano-bot-production-xxxx.up.railway.app`
   — keep this open, you'll need it in Part B

**Step 3 — Find your Meta credentials (before entering Railway vars)**

Before setting env vars you need three values from Meta. Open a new tab:

1. Go to **[https://developers.facebook.com/apps](https://developers.facebook.com/apps)**
2. Click your app
3. In the left sidebar, click **"WhatsApp"** → **"API Setup"**
4. Copy:
   - **Phone Number ID** (shown under "From" — a long number)
   - **Access Token** (click "Generate" if needed — the temporary token is fine for testing)
5. Now go to **"App Settings"** → **"Basic"** (left sidebar, under your app name)
6. Copy:
   - **App Secret** (click "Show" to reveal it)

**Step 4 — Set environment variables in Railway**

Back in Railway:

1. Click on the **`mano-bot` service** → click the **"Variables"** tab
2. Click **"New Variable"** for each row below — add them one at a time:

| Variable | Value |
|---|---|
| `WHATSAPP_VERIFY_TOKEN` | Pick any string you'll remember, e.g. `mano-verify-2024` |
| `WHATSAPP_ACCESS_TOKEN` | The Access Token you copied from Meta Step 3 |
| `WHATSAPP_PHONE_NUMBER_ID` | The Phone Number ID you copied from Meta Step 3 |
| `WHATSAPP_APP_SECRET` | The App Secret you copied from Meta Step 3 |
| `ANTHROPIC_API_KEY` | `placeholder` (not called during echo) |
| `NOTION_TOKEN` | `placeholder` |
| `NOTION_TASK_DB_ID` | `placeholder` |
| `NOTION_IDEAS_DB_ID` | `placeholder` |
| `GOOGLE_CREDENTIALS_JSON` | `{}` |
| `GOOGLE_TOKEN_PERSONAL` | `e30=` |
| `GOOGLE_TOKEN_CGM` | `e30=` |
| `GOOGLE_TOKEN_DEALS` | `e30=` |
| `ADMIN_TOKEN` | `placeholder` |
| `BOT_ENABLED` | `true` |

3. After adding all variables, Railway will automatically redeploy
4. Wait for the deploy to show **"Success"** (green) in the **"Deployments"** tab before continuing

**Railway gotcha:** edits to existing variables sometimes land in a "staged changes" state with a yellow **"Apply Changes"** banner at the top of the Variables tab. Until you click that, redeploys silently use the previous values — which presents as a deploy that briefly goes Active then crash-loops on the old config. If you see this, click **Apply Changes** (or **Save**) and Railway will redeploy with the real values.

---

### Part B — Meta webhook registration

**Step 5 — Register the webhook URL**

1. Go to **[https://developers.facebook.com/apps](https://developers.facebook.com/apps)**
2. Click your app
3. In the left sidebar, click **"WhatsApp"** → **"Configuration"**
4. Under **"Webhook"**, click **"Edit"**
5. Fill in:
   - **Callback URL:** `https://<your-railway-domain>/webhook` (replace with the domain from Step 2)
   - **Verify Token:** the exact string you set as `WHATSAPP_VERIFY_TOKEN` in Railway (e.g. `mano-verify-2024`)
6. Click **"Verify and Save"** — Meta will call Railway to verify; Railway must be deployed and showing "Success" at this point
7. If verification succeeds you'll see a green checkmark

**Step 6 — Subscribe to messages**

1. Still on the **WhatsApp → Configuration** page
2. Under **"Webhook Fields"**, find **`messages`** and click **"Subscribe"**

---

### Part C — Test

**Step 7 — Send a test message**

1. Go to **WhatsApp → API Setup** → **[https://developers.facebook.com/apps](https://developers.facebook.com/apps)** → your app → WhatsApp → API Setup
2. Under **"Send and receive messages"**, note the **test phone number** (format: +1 555 xxx-xxxx)
3. From your personal WhatsApp, send a message **to that test number**
4. The bot should echo the exact same text back within a few seconds

**If it doesn't work:**

- Railway deploy failed → check **Railway → Deployments tab** → click the failed deploy → view logs (usually a missing env var)
- Verification failed → check that `BOT_ENABLED=true` and all four WhatsApp vars are set correctly
- Message not echoed → check **Meta → WhatsApp → Configuration → Webhook → Recent Deliveries** for the HTTP status code Railway returned

## Notion setup

The Notion integration (Task 5) talks to three databases that already exist in
Yuval's workspace, under the **Headquarters** and **Idea Lab** parent pages.

### Env vars

```
NOTION_TOKEN            # internal integration token (ntn_... or secret_...)
NOTION_TASK_DB_ID       # 2dd484a7ece581eba273d55f54119119   (My Task List, under Headquarters)
NOTION_IDEAS_DB_ID      # 110d878b5f3e4f828448aaaa6b19c05c   (My Ideas, under Idea Lab)
NOTION_BUCKETS_DB_ID    # 2dd484a7ece581edadf5000b8ab9f6a4   (My Life Buckets, under Headquarters)
```

These IDs are stable — they're already wired into Mano's adapter.

### 1. Create the internal integration

1. Open **<https://www.notion.so/profile/integrations>** → **"New integration"**
2. Name: `Mano Bot` → Associated workspace: your personal workspace → **Create**
3. Under **Capabilities** keep the defaults: Read content, Update content, Insert content. No user info.
4. Copy the **Internal Integration Secret** (`ntn_...` or `secret_...`) — this is `NOTION_TOKEN`.

### 2. Connect Mano Bot to your two parent pages

Mano reads/writes three child databases. Connecting at the parent-page level
gives the integration access to all of them in one click.

For each of these pages, do:

- **Headquarters** — <https://www.notion.so/Headquarters-2dd484a7ece581dd9790c9df701202c9>
- **Idea Lab** — <https://www.notion.so/Idea-Lab-35c484a7ece5815cad29c59497023df0>

1. Open the page in Notion → click **`…`** top-right → **Connections** → **Connect to** → pick `Mano Bot`
2. Confirm the access prompt

Without this step, Notion returns 404 on every API call from the bot.

### 3. Schema (already in place — do not change)

This is what Mano expects. Your DBs already match. **Don't rename these props.**

**My Task List** (database):

| Property | Type | Notes |
|---|---|---|
| `Task` | Title | task name |
| `Bucket` | Relation → My Life Buckets | Mano resolves bucket name → page by querying My Life Buckets |
| `Date` | Date | optional due date |
| `Priority` | Select (`1` / `2` / `3`) | used only for list ordering |

**My Ideas** (database, under Idea Lab):

| Property | Type |
|---|---|
| `Idea` | Title |
| `Description` | Text (rich_text) — optional |

(The richer fields you have on My Ideas — `Category`, `Status`, `Source`, `Tags`, `Effort`, `Potential`, `Activation Date`, `Date Captured` — aren't set by Mano yet. Will add as needed.)

**My Life Buckets** (database) — title prop `Name`. One page per bucket. Make sure the 15 buckets from `SYSTEM_PROMPT` all exist as pages here:

```
Business, Career, Self Improvement, Personal, Productive Ideas, Job, Health,
Fitness, Family & Friends, Journal, Relationship, Admin, Marketing, Economics, Study
```

If you request a bucket name that isn't in My Life Buckets, Mano creates the task without a bucket relation (audit log `status=ok_no_bucket`) and you can re-bucket manually.

### 4. Set the env vars

- Locally: add the four `NOTION_*` keys to `.env` (DB IDs are listed at the top of this section).
- Railway: **Variables tab** → add the four keys.

### 5. Verify

Send WhatsApp message: `תוסיף משימה לקנות חלב תחת Personal` → Mano confirms (`לאשר?`) → reply `כן` → task appears in My Task List with Bucket relation set to the Personal page.

## Google Auth Setup

Per-account OAuth tokens are obtained by a one-off local helper script
(`scripts/oauth_setup_google.py`) and stored as base64-encoded JSON in the
Railway env vars `GOOGLE_TOKEN_PERSONAL`, `GOOGLE_TOKEN_CGM`, and
`GOOGLE_TOKEN_DEALS`. We don't write token files to disk because Railway's
filesystem is ephemeral (see D-015).

### Prereqs (one-time, in Google Cloud Console)

1. Open the [Google Cloud Console — APIs & Services](https://console.cloud.google.com/apis/dashboard) and select the project that owns the OAuth client (the same one that produced `GOOGLE_CREDENTIALS_JSON`)
2. Go to **APIs & Services → Library** and enable: **Gmail API**, **Google Calendar API**, **Google Drive API**, **People API**
3. Go to **APIs & Services → OAuth consent screen → Audience**:
   - User type: **External**
   - Publishing status: **Testing**
   - Under **Test users**, add: `yuvalmanor@gmail.com`, `yuval.cgm@gmail.com`, `deals@cgm-ventures.com`, `edeng.cgm@gmail.com`
   - `edeng.cgm@gmail.com` (Eden) is enrolled as a test user so future Eden-side Google access can be turned on without re-touching the consent screen. The bot does **not** currently use it — Eden has no Google permissions in `users.py` and there is no `GOOGLE_TOKEN_EDEN` env var. Enable later by adding the permission(s) to `USERS["+972546900908"]` and adding a token env var.
4. Confirm `GOOGLE_CREDENTIALS_JSON` is set in your **local `.env`** (it must be the full client-secret JSON on a single line — minify if needed)

### Run the helper (once per account)

The helper has two modes:

* **default (loopback)** — `python scripts/oauth_setup_google.py <account>`. Opens a browser AND binds a temporary localhost port for the OAuth redirect. 🔴 SentinelOne risk: port binding + outbound HTTPS together. Use only if you're certain SentinelOne is calm.

* **`--manual`** — `python scripts/oauth_setup_google.py <account> --manual`. Prints the Google auth URL, you sign in in your browser, copy the (failed-redirect) URL from the address bar, paste it back. No port binding. 🟡 risk only (outbound HTTPS POST). **This is the recommended mode on the corporate machine.**

For each account, in manual mode:
```
python scripts/oauth_setup_google.py personal --manual
python scripts/oauth_setup_google.py cgm --manual
python scripts/oauth_setup_google.py deals --manual
```

Manual flow walkthrough:
1. Script prints "STEP 1 — Open this URL in your browser" followed by a long `https://accounts.google.com/o/oauth2/auth?...` URL — copy that whole URL
2. Open it in any browser → sign in with the **exact** account name the script printed (Google will reject any other account, since only the four test users are enrolled)
3. Approve the requested scopes (gmail.send, gmail.readonly, contacts.readonly, contacts.other.readonly, calendar.events, drive.readonly). **Task 6c expanded this set — re-run OAuth for all three accounts so existing tokens get the new scopes.**
4. Google redirects to `http://localhost:8765/?code=...` — the browser shows **"This site can't be reached" / `ERR_CONNECTION_REFUSED`**. THAT IS EXPECTED. Nothing is listening on port 8765. The piece you need is in the URL bar.
5. Copy the **entire URL** from the browser address bar (it starts with `http://localhost:8765/?state=...&code=...&scope=...`) and paste it into the script at the `>` prompt → Enter
6. Script does one outbound HTTPS POST to `oauth2.googleapis.com/token`, exchanges the code for a token, and prints a single long base64 line — that's your token

### Paste the token into Railway

For each account, in the [Railway dashboard](https://railway.com/) → **mano-bot service → Variables tab**:

| account_key | Railway env var | Gmail address |
|---|---|---|
| `personal` | `GOOGLE_TOKEN_PERSONAL` | yuvalmanor@gmail.com |
| `cgm`      | `GOOGLE_TOKEN_CGM`      | yuval.cgm@gmail.com |
| `deals`    | `GOOGLE_TOKEN_DEALS`    | deals@cgm-ventures.com |

Steps per variable:
1. Click **+ New Variable**
2. Name: the env var from the table above
3. Value: the base64 line printed by the helper (no quotes, no newlines, no leading/trailing spaces)
4. Save → Railway auto-redeploys

### Verify

After all three tokens are set, the next deploy should boot cleanly (config.py validates that all three env vars are present). End-to-end send test runs in Task 6b — send a WhatsApp message like `תשלח מייל ל-foo@bar.com מהאישי "Subject" "Body"`, Mano confirms (`לאשר?`), reply `כן` → email appears in the Sent folder of the matching account.

## Documentation

- `docs/CLAUDE.md` — operating contract for Claude Code in this repo
- `docs/TASKS.md` — build roadmap
- `docs/SECURITY.md` — threat model and security controls
- `docs/DECISIONS.md` — architecture decisions with rationale
- `docs/CHANGELOG.md` — completed-task log
- `docs/TESTING.md` — test checklist
