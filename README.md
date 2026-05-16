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

## Google Auth Setup

Per-account OAuth tokens are obtained by a one-off local helper script, then
stored as base64-encoded JSON in the Railway env vars `GOOGLE_TOKEN_PERSONAL`,
`GOOGLE_TOKEN_CGM`, and `GOOGLE_TOKEN_DEALS`. Detailed steps are documented in
Task 6 (`docs/TASKS.md`) and will be expanded here once that task lands.

## Documentation

- `docs/CLAUDE.md` — operating contract for Claude Code in this repo
- `docs/TASKS.md` — build roadmap
- `docs/SECURITY.md` — threat model and security controls
- `docs/DECISIONS.md` — architecture decisions with rationale
- `docs/CHANGELOG.md` — completed-task log
- `docs/TESTING.md` — test checklist
