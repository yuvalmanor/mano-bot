# CLAUDE.md — Mano Bot

Read this file at the start of every session. It is the source of truth for how to work in this repo.

---

## Project Overview

Mano is a personal WhatsApp AI assistant for Yuval (and his partner Eden),
powered by Claude. It receives WhatsApp messages via Meta Cloud API, processes
them through Claude with tool-use for integrations, and replies via WhatsApp.

**Stack:**
- Python 3.11+
- FastAPI (webhook server)
- Anthropic SDK — model: `claude-sonnet-4-6`
- Notion API via `notion-client`
- Google APIs via `google-api-python-client` (Gmail, Calendar, Drive)
- Hosted on Railway
- WhatsApp via Meta Cloud API

---

## ⚠️ Corporate Environment — SentinelOne EDR

This project is developed on a corporate Windows machine running **SentinelOne** endpoint security.
SentinelOne monitors behavioral patterns, not just file signatures. It previously quarantined all
project files and force-closed Claude Desktop mid-session.

**Known triggers (from incident):**
- `ngrok` — outbound tunnel to expose a local port. SentinelOne may classify this as C2 (command-and-control) behavior
- Python process opening a listening network port (FastAPI/uvicorn)
- Python process making repeated outbound HTTPS calls to multiple external endpoints simultaneously
- A new process writing multiple new files rapidly (can look like ransomware to behavioral analysis)
- Combination of port binding + outbound calls + file writes in the same session = highest risk

**These are risks to manage — not reasons to avoid the tools.** Use the best tool for each job.
Apply the protocol below before any risky operation.

---

## SentinelOne Protocol

### Rule 1 — Classify before acting
Before every step, determine its risk level:

| Risk | Examples | Action |
|---|---|---|
| 🟢 Safe | Writing/editing .py files, reading files, git add/commit | Proceed normally |
| 🟡 Caution | pip install, running Python scripts, git push | Warn Yuval briefly, then proceed |
| 🔴 High risk | Starting uvicorn, ngrok, outbound API calls, OAuth flows, installing socket-opening packages | Full protocol below |

### Rule 2 — Full protocol for 🔴 steps
Before executing any 🔴 step:
1. Tell Yuval exactly what you are about to do
2. Explain why it may trigger SentinelOne
3. **Claude commits and pushes all current work** (`git add` → `git commit` → `git push`). Do not ask Yuval to do this — Claude runs all git operations directly. Report the resulting commit SHA.
4. Wait for Yuval's explicit go-ahead on the risky action itself
5. Only then execute the step

This ensures that if SentinelOne quarantines files mid-task, all work is safe on GitHub and recovery is a single `git clone`.

**General rule:** Claude owns all git operations in this repo (commits, pushes, branch work). Yuval is the decision-maker on *whether* to proceed; Claude is the operator.

### Rule 3 — Offer web as a fallback
For any 🔴 step, also offer running it via **Claude Code on claude.ai (web)** as an alternative.
The web interface does not interact with the local filesystem the same way, avoiding quarantine risk.
Yuval decides — never decide unilaterally.

### Rule 4 — Bypass strategies
Apply these to reduce behavioral footprint without compromising quality or security:
- **File creation:** Create files one at a time, not in rapid bulk
- **pip installs:** Install one package at a time during first setup, not `pip install -r requirements.txt` all at once
- **Outbound calls:** Make API calls sequentially during development, not concurrently
- **Local testing without webhook:** Use unit tests with mocked HTTP instead of running a live server, where possible
- **ngrok + uvicorn together:** This combination is the highest-risk pattern. If it triggers SentinelOne, fall back to Railway for webhook testing (push → Railway auto-deploys → use Railway URL in Meta webhook settings)

---

## How to Work in This Repo

### When Yuval says "proceed with the next task":
1. Read `TASKS.md`
2. Find the first task with status `🔲 Not started`
3. Check the task's risk level — if 🔴, apply the full protocol before starting
4. Execute the task completely
5. Update the task status to `✅ Done` in TASKS.md
6. Add a one-line entry to `CHANGELOG.md`

### When Yuval says "where are we" or "what's the current task":
- Report the next not-started or currently in-progress task from TASKS.md

### Never:
- Skip a task
- Work on two tasks simultaneously
- Commit `.env`, credentials, or token files
- Log credential values
- Hardcode phone numbers or API keys outside of `users.py` (the registry there is the single allowed exception)
- Skip the confirmation step before any write operation
- Execute a 🔴 step without the full protocol

---

## Repo Structure

```
mano-bot/
├── docs/
│   ├── CLAUDE.md          ← this file — read first
│   ├── TASKS.md           ← build roadmap — Claude Code's instructions
│   ├── SECURITY.md        ← threat model and security controls
│   ├── DECISIONS.md       ← architecture decisions with rationale
│   ├── CHANGELOG.md       ← updated after each completed task
│   └── TESTING.md         ← test checklist and results
├── README.md              ← setup instructions (created in Task 1)
├── requirements.txt       ← pinned dependencies
├── .env.example           ← all required env vars (empty values)
├── .gitignore
├── Procfile
├── main.py                ← FastAPI entry point
├── config.py              ← env var loading and validation
├── router.py              ← message routing
├── users.py               ← user registry
├── security/
│   ├── auth.py            ← signature verification + allowlist
│   ├── rate_limiter.py    ← per-phone rate limiting
│   └── audit.py           ← audit logging
├── whatsapp/
│   ├── webhook.py         ← parse incoming Meta payloads
│   └── client.py          ← send messages via Meta Cloud API
├── claude_agent/
│   ├── agent.py           ← Claude interaction loop + pending actions
│   ├── tools.py           ← Anthropic tool definitions
│   └── system_prompt.py   ← bot system prompt constant
└── integrations/
    ├── notion.py
    ├── gmail.py
    ├── gcalendar.py
    └── drive.py
```

---

## Environment Variables

All in `.env` (never committed). See `.env.example` for the full list.

```
WHATSAPP_VERIFY_TOKEN      # chosen webhook verify string
WHATSAPP_ACCESS_TOKEN      # Meta system user token
WHATSAPP_PHONE_NUMBER_ID   # Meta phone number ID
WHATSAPP_APP_SECRET        # Meta app secret (for signature verification)
ANTHROPIC_API_KEY
NOTION_TOKEN
NOTION_TASK_DB_ID
NOTION_IDEAS_DB_ID
GOOGLE_CREDENTIALS_JSON    # OAuth client credentials JSON from Google Cloud Console (static, never changes)
GOOGLE_TOKEN_PERSONAL      # base64-encoded token JSON for yuvalmanor@gmail.com (set after OAuth flow)
GOOGLE_TOKEN_CGM           # base64-encoded token JSON for yuval.cgm@gmail.com
GOOGLE_TOKEN_DEALS         # base64-encoded token JSON for deals@cgm-ventures.com
ADMIN_TOKEN                # for GET /audit endpoint
BOT_ENABLED                # true/false kill switch
# Phone numbers are NOT env vars — they live in users.py (the registry)
```

---

## Security Rules

Read `SECURITY.md` for the full model. Short version:

1. Verify Meta webhook signature on every POST — reject 403 if invalid
2. Allowlist check on every message — unknown phones get silent 200
3. Permission check before every integration call
4. Rate limit: 20 msg / 10 min per phone
5. Pending action TTL: 5 minutes
6. Minimal OAuth scopes only
7. Never log credentials or raw exceptions to users

---

## Code Style

- Type hints on all functions
- Docstrings on all public functions
- `logging` module only — no print statements
- Async functions where possible
- Errors caught and returned as Hebrew user-facing messages
- No god files — keep each module focused

---

## Testing

- Local webhook testing: ngrok (🔴 — full protocol applies before running)
- Local unit testing: mock the HTTP layer, run without uvicorn where possible
- Fallback if ngrok triggers SentinelOne: push to Railway, use Railway URL in Meta webhook settings
- Railway auto-deploys on push to `main`
- Full test checklist in `TESTING.md`
