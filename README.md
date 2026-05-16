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
Do this after Task 2 code lands, before Task 3.

**Step 1 — Railway project setup (one-time, you do this in the dashboard)**

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo → select `mano-bot`
2. Railway detects the `Procfile` automatically — no extra config needed

**Step 2 — Set env vars in Railway dashboard**

For the echo test only these are needed (leave Google/Notion vars blank or dummy):

| Variable | Value |
|---|---|
| `WHATSAPP_VERIFY_TOKEN` | same value you'll register in Meta |
| `WHATSAPP_ACCESS_TOKEN` | from Meta → App → WhatsApp → API Setup |
| `WHATSAPP_PHONE_NUMBER_ID` | from Meta → App → WhatsApp → API Setup |
| `WHATSAPP_APP_SECRET` | from Meta → App → Settings → Basic → App Secret |
| `ANTHROPIC_API_KEY` | any non-empty string (not called during echo) |
| `NOTION_TOKEN` | `placeholder` |
| `NOTION_TASK_DB_ID` | `placeholder` |
| `NOTION_IDEAS_DB_ID` | `placeholder` |
| `GOOGLE_CREDENTIALS_JSON` | `{}` |
| `GOOGLE_TOKEN_PERSONAL` | `e30=` (base64 of `{}`) |
| `GOOGLE_TOKEN_CGM` | `e30=` |
| `GOOGLE_TOKEN_DEALS` | `e30=` |
| `ADMIN_TOKEN` | any non-empty string |
| `BOT_ENABLED` | `true` |

**Step 3 — Get the Railway URL**

In the Railway dashboard → your service → Settings → Domains → Generate Domain.
It will look like `https://mano-bot-production-xxxx.up.railway.app`.

**Step 4 — Register the webhook in Meta**

1. Meta for Developers → your app → WhatsApp → Configuration
2. Webhook URL: `https://<your-railway-domain>/webhook`
3. Verify token: same as `WHATSAPP_VERIFY_TOKEN` in Railway
4. Click Verify and Save — Railway must be deployed and running at this point
5. Subscribe to the `messages` field

**Step 5 — Send a test message**

Send any text from your WhatsApp to the Meta test number.
The bot should echo the same text back within a few seconds.

**If it doesn't work, check:**
- Railway deploy logs (look for startup errors — usually a missing env var)
- Meta webhook logs (Webhook → Recent Deliveries) for delivery failures or 403s

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
