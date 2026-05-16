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
machine — read `docs/CLAUDE.md` first). The fallback path is to push to
Railway and use the Railway URL in Meta webhook settings.

```powershell
uvicorn main:app --reload
ngrok http 8000
```

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
