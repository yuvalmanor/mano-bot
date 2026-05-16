# TASKS.md — Mano Bot Build Tasks

This file is Claude Code's build roadmap.

---

## How to Use

When Yuval says **"proceed with the next task"**:
1. Read this file
2. Find the first task with status `🔲 Not started`
3. Check the task's risk level — if 🔴, apply the full protocol before doing anything
4. Execute the task completely
5. Update status to `✅ Done` and add a one-line note to CHANGELOG.md

When Yuval says **"what's the current task"** or **"where are we"**:
- Report the current in-progress or next not-started task

Never skip tasks. Never work on two tasks simultaneously.
Always read CLAUDE.md before starting any task if you haven't in this session —
especially the SentinelOne section.

---

## ⚠️ SentinelOne Protocol (read before every task)

This machine runs SentinelOne EDR which previously quarantined all project files mid-session.
The goal is to work in the best way possible while managing the risk.

**Risk levels:**
- 🟢 Safe — writing/editing files, git add/commit, reading files — proceed normally
- 🟡 Caution — pip install, running Python scripts, git push — warn Yuval briefly, then proceed
- 🔴 High risk — uvicorn, ngrok, outbound API calls, OAuth flows — full protocol below

**Full protocol for any 🔴 step:**
1. Tell Yuval exactly what you're about to do
2. Explain why it may trigger SentinelOne
3. **Claude commits and pushes all current work** (`git add` → `git commit` → `git push`) and reports the SHA. Do not ask Yuval to run git — Claude runs all git operations directly.
4. Also offer: "This step can alternatively be run via Claude Code on claude.ai (web) to avoid local risk."
5. Wait for Yuval's go-ahead on the risky action itself before executing it

**Bypass strategies (apply always, without compromising quality or security):**
- Create files one at a time — not in rapid bulk
- Install pip packages one at a time during first setup
- Make API calls sequentially during development, not concurrently
- Use unit tests with mocked HTTP for logic that doesn't need a live server
- If ngrok + uvicorn together triggers SentinelOne: fall back to Railway for webhook testing (push → Railway auto-deploys → use Railway URL in Meta webhook settings)

---

## Task Table

| # | Task | Status | Risk | Notes |
|---|---|---|---|---|
| 1 | Project scaffold | ✅ Done | 🟢 | |
| 2 | Echo bot | 🟨 Code done, live test deferred | 🔴 | Code + 22 mocked tests passing; live webhook test will run via Railway in Task 2b |
| 2b | Live echo test via Railway | ⚠️ Blocked | 🟡 | Railway deployed ✓, webhook registered ✓, POST→200 via Test button ✓. Blocked: need dedicated SIM for bot's WhatsApp number (personal number can't be used — already a WA account). Resume when SIM available. |
| 3 | Claude integration | ✅ Done | 🔴 | Code + 10 mocked tests passing; live verification deferred until Task 2b's SIM available |
| 4 | Security layer | ✅ Done | 🟢 | auth allowlist, rate limiter, audit log, dedup, kill switch, pending-action store; 15 new tests (47 total) passing |
| 5 | Notion integration | ✅ Done | 🔴 | Adapter aligned with real schema (Task/Idea titles + Bucket relation to My Life Buckets); 18 Notion tests (65 total) passing; Mano Bot connected to Headquarters + Idea Lab parent pages; 4 NOTION_* env vars set in Railway; live WhatsApp verification deferred until Task 2b SIM available |
| 6a | Gmail integration — code + mocked tests | ✅ Done | 🟡 | `integrations/gmail.py` + Claude tool + 12 tests (77 total) passing; OAuth helper script at `scripts/oauth_setup_google.py`; README "Google Auth Setup" expanded |
| 6b | Gmail integration — live OAuth + verification | 🔲 Not started | 🔴 | run `oauth_setup_google.py` 3× (personal/cgm/deals), paste tokens into Railway, live WhatsApp send test (deferred — gated by Task 2b SIM and OAuth flow risk; consider running on claude.ai web) |
| 7 | Google Calendar integration | 🔲 Not started | 🔴 | outbound API calls |
| 8 | Google Drive integration | 🔲 Not started | 🔴 | outbound API calls |
| 9 | Audit logging | 🔲 Not started | 🟢 | code only |
| 10 | End-to-end testing | 🔲 Not started | 🔴 | full network activity |
| 11 | Railway production deploy | 🔲 Not started | 🟡 | git push only |

Status legend: 🔲 Not started | 🔄 In progress | ✅ Done | ⚠️ Blocked

---

## Task Specs

---

### Task 1 — Project Scaffold
**Risk: 🟢 Safe — file creation only**

**Goal:** Create the full repo structure with all placeholder files.

Create files one at a time (SentinelOne caution — avoid rapid bulk file creation).

**Files to create:**
```
main.py                    ← empty FastAPI app, health check GET / only
config.py                  ← loads all env vars, fails loud if missing
users.py                   ← user registry (Yuval + Eden)
router.py                  ← stub only
requirements.txt           ← all dependencies, pinned versions
.env.example               ← all required env vars with empty values
.gitignore                 ← .env, *.pyc, __pycache__, credentials*.json, SECRETS.md, audit.log, token_*.json
Procfile                   ← web: uvicorn main:app --host 0.0.0.0 --port $PORT
README.md                  ← project overview + local setup instructions
whatsapp/__init__.py
whatsapp/webhook.py        ← stub
whatsapp/client.py         ← stub
claude_agent/__init__.py
claude_agent/agent.py      ← stub
claude_agent/tools.py      ← empty list
claude_agent/system_prompt.py  ← full system prompt as constant (spec below)
integrations/__init__.py
integrations/notion.py     ← stub
integrations/gmail.py      ← stub
integrations/gcalendar.py   ← stub
integrations/drive.py      ← stub
security/__init__.py
security/auth.py           ← stub
security/rate_limiter.py   ← stub
security/audit.py          ← stub
```

**config.py must:**
- Load from `.env` via python-dotenv
- Validate all required vars on startup, raise a clear error if any are missing
- Never log credential values

**users.py must:**
```python
USERS = {
    "+972542159121": {
        "name": "Yuval",
        "language": "he",
        "permissions": ["notion", "gmail", "calendar", "drive", "idea_lab"]
    },
    "+972546900908": {
        "name": "Eden",
        "language": "he",
        "permissions": []
    }
}

def get_user(phone: str) -> dict | None:
    return USERS.get(phone)

def is_authorized(phone: str) -> bool:
    return phone in USERS

def has_permission(phone: str, integration: str) -> bool:
    user = get_user(phone)
    return user is not None and integration in user.get("permissions", [])
```

**system_prompt.py must contain:**
```python
SYSTEM_PROMPT = """
You are a personal AI assistant for Yuval, operating via WhatsApp.

## Identity & Language
- You are Yuval's personal assistant, sharp, efficient, and direct
- Default language: Hebrew
- Switch to English only if Yuval explicitly asks
- Use informal Hebrew (אתה)

## Users
- Yuval (+972542159121): full access to all integrations
- Eden (+972546900908): Hebrew, no Notion access, Gmail/Calendar/Drive TBD

## Behavior Rules
- Always confirm before executing any action (Notion, Gmail, Calendar, Drive)
- Summarize what you're about to do and ask "לאשר?" before writing
- Be concise — this is WhatsApp, not email
- No unnecessary filler or pleasantries

## Service Routing
- Specific date/time + event/appointment → Google Calendar
- Task/todo language → Notion
- Email/Drive language → Gmail / Google Drive
- "יש לי רעיון" → Idea Lab
- Gray area (unclear if task or event) → ask: "זה משימה ב-Notion או אירוע ביומן?"

## Notion — Structure
Buckets: Business, Career, Self Improvement, Personal, Productive Ideas, Job,
Health, Fitness, Family & Friends, Journal, Relationship, Admin, Marketing,
Economics, Study

When adding a task:
- Infer the bucket from context
- Confirm with user before saving: "אוסיף משימה '[name]' תחת [bucket]. לאשר?"

Task listing format: per bucket → per day → per priority

## Gmail
- #personal → yuvalmanor@gmail.com
- #cgm → yuval.cgm@gmail.com
- #deals → deals@cgm-ventures.com
- Always confirm before sending
- Write emails in casual, human, everyday language — not bot language
- Never use "—" or other LLM-style punctuation

## Google Drive
- #personal → yuvalmanor@gmail.com (personal drive)
- #cgm → yuval.cgm@gmail.com (CGM general, rarely used)
- #deals → deals@cgm-ventures.com (LLC docs, property management)

## Google Calendar
- Single calendar: yuvalmanor@gmail.com
- Always confirm before creating/editing events

## SMS & Messaging
- Write in casual, human, everyday language — not bot language
- Never use "—" or other LLM-style punctuation

## Idea Lab
- Activated on demand only
- Example: "תעבור על רעיון X ותצור משימות ב-HQ"
"""
```

**pip install (🟢 safe — install pytest now so tests work from Task 2 onward):**
```
pip install pytest
pip install pytest-asyncio
```

**Done when:** All files exist and `pytest --collect-only` runs without error. No server started.

---

### Task 2 — Echo Bot
**Risk: 🔴 High risk — uvicorn + ngrok**

⚠️ **Before starting, tell Yuval:**
"I'm about to install packages, start a local server (uvicorn), and run ngrok to expose it. The combination of port binding and an outbound tunnel is what previously triggered SentinelOne. Please commit and push all current work before I proceed. Alternatively, this step can be run via Claude Code on claude.ai (web)."

Wait for Yuval's go-ahead.

**pip installs — one at a time:**
```
pip install fastapi
pip install "uvicorn[standard]"
pip install python-dotenv
pip install httpx
```

**Implement `whatsapp/webhook.py`:**
- `parse_incoming(payload: dict) -> dict | None`
  - Extracts: `from_phone`, `message_type`, `text`, `message_id`
  - Returns `None` for status updates (delivered/read receipts) — silently ignored
  - Handles missing/malformed payloads gracefully

**Implement `whatsapp/client.py`:**
- `send_message(to_phone: str, text: str) -> bool`
  - POSTs to `https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages`
  - Uses `WHATSAPP_ACCESS_TOKEN` from config
  - 10-second `httpx` timeout — returns False on timeout or HTTP error
  - Never logs the token itself
  - Returns True on success, False on failure

**Implement `main.py`:**
- `GET /webhook` — Meta verification: check `hub.verify_token`, return `hub.challenge`
- `POST /webhook`:
  1. Verify signature → 403 if invalid
  2. Parse payload → if not a text message, return 200 immediately
  3. **Return 200 immediately**, then process in a FastAPI `BackgroundTask` (Meta requires 200 within ~20 seconds; Claude + integration calls can exceed this)
  4. Background task: echo text back
- Always return 200 to Meta even on errors

**Local testing:**
- Write `tests/test_webhook.py` that mocks HTTP and tests parse_incoming + echo logic without a live server
- For real WhatsApp webhook testing: run `uvicorn main:app --reload` + `ngrok http 8000`, update Meta webhook URL to the ngrok HTTPS URL
- **If ngrok triggers SentinelOne:** fall back to Railway — push to main, Railway auto-deploys, use Railway URL in Meta webhook settings

**Done when:** Echo works end-to-end — WhatsApp message in → identical message back.

---

### Task 2b — Live Echo Test via Railway
**Risk: 🟡 Caution — git push only (Claude's part); dashboard steps for Yuval**

**Goal:** Validate the webhook plumbing end-to-end before building Claude integration on top of it.

**Why before Task 3:** If signature verification, payload parsing, or the Meta→Railway→WhatsApp path is broken, better to know now than after layering Claude on top.

**Claude's part (🟡):**
- Confirm the code is pushed to `main` (already done at end of Task 2)
- No code changes needed — the echo is already implemented

**Yuval's part (dashboard steps, ~5 min):**
1. Railway: create project → connect `mano-bot` GitHub repo → Railway auto-deploys on push
2. Railway: set the env vars listed in README.md "Railway deploy + live WhatsApp echo test" section (echo-only set — Google/Notion can be placeholders)
3. Railway: generate a domain (Settings → Domains)
4. Meta: register webhook URL (`https://<railway-domain>/webhook`) with verify token; subscribe to `messages` field
5. Send a WhatsApp message to the Meta test number → confirm echo arrives

**Done when:** WhatsApp text in → same text echoed back, confirmed on a real device.

---

### Task 3 — Claude Integration
**Risk: 🔴 High risk — outbound HTTPS to Anthropic API**

⚠️ **Before starting, tell Yuval:**
"I'm about to install the Anthropic SDK and make outbound HTTPS calls to api.anthropic.com. This may trigger SentinelOne. Please commit and push all current work before I proceed. Alternatively, this step can be run via Claude Code on claude.ai (web)."

Wait for Yuval's go-ahead.

**pip install:**
```
pip install anthropic
```

**Implement `claude_agent/agent.py`:**

```python
CONVERSATION_HISTORY: dict[str, list[dict]] = {}  # phone → list of {role, content} dicts
MAX_HISTORY_TURNS = 5  # user+assistant pairs; trimmed oldest-first when full
```

- `async def run(user_phone: str, message: str) -> str`
  - Load history for `user_phone` (empty list if first message)
  - Build messages list: history + new user message
  - Call `claude-sonnet-4-6` with:
    - System prompt: `SYSTEM_PROMPT` with `cache_control: {"type": "ephemeral"}` (prompt caching — reduces cost on repeated calls)
    - Messages: history + current message
    - Tools: empty list for now
    - Max tokens: 1024
  - Append user message + assistant reply to history; trim to last `MAX_HISTORY_TURNS` pairs
  - Return text reply
  - On API error: log error (no message content), return Hebrew error ("משהו השתבש, נסה שוב")

**Implement `router.py`:**
- `async def handle_message(from_phone: str, text: str) -> None`
  - Wraps the entire body in `try/except Exception` — **a user must always get a reply**
  - On any unhandled exception: log the error (no message content), send Hebrew fallback ("משהו השתבש, נסה שוב") via `whatsapp.client.send_message`
  - Normal path: calls `agent.run` → sends reply via `whatsapp.client.send_message`

Update `main.py` POST /webhook `BackgroundTask` to call `router.handle_message`.

**Done when:** Hebrew conversation with Claude works end-to-end via WhatsApp.

---

### Task 4 — Security Layer
**Risk: 🟢 Safe — code only, no network activity**

**Goal:** Harden the bot before connecting any real integrations.
**Must complete before Tasks 5–8.**

**Implement `security/auth.py`:**
- `verify_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool`
  - HMAC-SHA256 of payload using `WHATSAPP_APP_SECRET`
  - `hmac.compare_digest` — constant-time comparison
  - Return False if header missing or invalid
- `authorize_sender(phone: str) -> bool`
  - True only if phone in USERS
  - Log unauthorized attempts (phone + timestamp only, no message content)

**Implement `security/rate_limiter.py`:**
- In-memory: dict of phone → deque of timestamps
- `check_rate_limit(phone: str) -> bool` — max 20 msg / 10 min
- `get_rate_limit_message() -> str` — Hebrew warning string

**Implement `security/audit.py`:**
- `log_action(phone: str, action_type: str, details: str, status: str) -> None`
  - Appends to `audit.log`
  - Format: `[ISO timestamp] | phone=MASKED | action=X | details=X | status=X`
  - Phone masked to last 4 digits
  - Never log message content

**Add to `main.py` — message deduplication store:**
```python
from collections import deque
SEEN_MESSAGE_IDS: set[str] = set()
SEEN_MESSAGE_IDS_QUEUE: deque[str] = deque(maxlen=1000)  # FIFO eviction

def is_duplicate(message_id: str) -> bool:
    if message_id in SEEN_MESSAGE_IDS:
        return True
    if len(SEEN_MESSAGE_IDS_QUEUE) == 1000:
        SEEN_MESSAGE_IDS.discard(SEEN_MESSAGE_IDS_QUEUE[0])
    SEEN_MESSAGE_IDS.add(message_id)
    SEEN_MESSAGE_IDS_QUEUE.append(message_id)
    return False
```

**Pending action store in `claude_agent/agent.py`:**
```python
PENDING_ACTIONS: dict[str, dict] = {}
TTL_MINUTES = 5
CONFIRM_WORDS = {"כן", "yes", "אשר", "ok", "confirm", "כן."}
CANCEL_WORDS  = {"לא", "no", "ביטול", "cancel", "בטל", "לא."}
```
Overwrite behavior: if a new non-confirmation/non-cancellation message arrives while a pending action exists for that phone, discard the pending action silently and process the new message normally.

**Update `main.py` POST /webhook pipeline:**
```
1. Verify webhook signature → 403 if invalid
2. Check BOT_ENABLED → if false, return 200 immediately
3. Parse payload → 200 if not a text message
4. Deduplicate message_id → if seen, return 200 immediately (no processing)
5. Authorize sender → if unknown → audit log + silent 200
6. Check rate limit → if over → Hebrew warning + 200
7. Return 200 immediately, enqueue BackgroundTask → route to handler
```

**Done when:** All security controls active. Verified via unit tests (no network needed).

---

### Task 5 — Notion Integration
**Risk: 🔴 High risk — outbound HTTPS to Notion API**

⚠️ **Before starting, tell Yuval:**
"I'm about to install notion-client and make outbound calls to the Notion API. This may trigger SentinelOne. Please commit and push all current work before I proceed. Alternatively, this step can be run via Claude Code on claude.ai (web)."

Wait for Yuval's go-ahead.

**pip install:**
```
pip install notion-client
```

**Implement `integrations/notion.py`:**
```python
async def add_task(title: str, bucket: str, due_date: str | None = None) -> bool
async def list_tasks(filter_bucket: str | None = None) -> str
async def add_idea(title: str, description: str | None = None) -> bool
```
- Use `NOTION_TOKEN`, `NOTION_TASK_DB_ID`, `NOTION_IDEAS_DB_ID`
- `list_tasks` returns Hebrew-friendly string: bucket → due date → priority
- All external calls: 10-second `httpx` timeout — on timeout return `False`/empty string, log to audit
- Check `has_permission(phone, "notion")` before every call

**Add to `claude_agent/tools.py`:**
```python
{
    "name": "notion_add_task",
    "description": "Add a task to Notion My Task List",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "bucket": {
                "type": "string",
                "enum": ["Business","Career","Self Improvement","Personal",
                         "Productive Ideas","Job","Health","Fitness",
                         "Family & Friends","Journal","Relationship",
                         "Admin","Marketing","Economics","Study"]
            },
            "due_date": {"type": "string", "description": "ISO date string, optional"}
        },
        "required": ["title", "bucket"]
    }
},
{
    "name": "notion_list_tasks",
    "description": "List tasks from Notion My Task List",
    "input_schema": {
        "type": "object",
        "properties": {
            "filter_bucket": {"type": "string"}
        }
    }
},
{
    "name": "notion_add_idea",
    "description": "Add an idea to the Idea Lab",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"}
        },
        "required": ["title"]
    }
}
```

Update `claude_agent/agent.py` to handle `tool_use` blocks.

**Done when:** Add task → confirm → "כן" → task in Notion. Eden denied. List works.

---

### Task 6 — Gmail Integration
**Risk: 🔴 High risk — outbound HTTPS + OAuth browser flow**

⚠️ **Before starting, tell Yuval:**
"I'm about to set up Google OAuth (which opens a browser flow) and make outbound Gmail API calls. This is among the highest-risk steps — outbound HTTPS, token file writes, and a browser OAuth flow all at once. Please commit and push all current work before I proceed. Strongly recommend running this via Claude Code on claude.ai (web) to avoid local risk."

Wait for Yuval's go-ahead.

**pip installs — one at a time:**
```
pip install google-auth
pip install google-auth-oauthlib
pip install google-api-python-client
```

**OAuth scope:** `https://www.googleapis.com/auth/gmail.send` only

**Two distinct credential types — do not confuse:**
- `GOOGLE_CREDENTIALS_JSON` — static OAuth client credentials (client_id, client_secret) downloaded once from Google Cloud Console. Never changes. Already in `.env`.
- `GOOGLE_TOKEN_PERSONAL`, `GOOGLE_TOKEN_CGM`, `GOOGLE_TOKEN_DEALS` — per-account user tokens obtained via the OAuth browser flow. **Stored as Railway env vars (base64-encoded JSON), not as files on disk** (Railway's filesystem is ephemeral — files are lost on redeploy). See D-015.

**OAuth setup flow (run once per account, locally):**
1. Run a one-off helper script that loads `GOOGLE_CREDENTIALS_JSON`, opens the browser flow, and prints the resulting token as base64
2. Paste the base64 string into the Railway env var for that account
3. Document exact steps in README under "Google Auth Setup"

**Implement `integrations/gmail.py`:**
```python
async def send_email(to: str, subject: str, body: str, account_key: str) -> bool
```
- `account_key`: "personal" | "cgm" | "deals"
- Load token from env var (`GOOGLE_TOKEN_PERSONAL` etc.), decode base64, construct `google.oauth2.credentials.Credentials`
- All external calls: 10-second `httpx` timeout — on timeout return `False`, log to audit
- Check `has_permission(phone, "gmail")`

**Claude tool:** `gmail_send_email` with fields: `to`, `subject`, `body`, `account_key`

**Done when:** Email sent from correct account, visible in Sent folder.

---

### Task 7 — Google Calendar Integration
**Risk: 🔴 High risk — outbound HTTPS to Google Calendar API**

⚠️ **Before starting, tell Yuval:**
"I'm about to make outbound calls to the Google Calendar API. Please commit and push all current work before I proceed. This step can also be run via Claude Code on claude.ai (web)."

Wait for Yuval's go-ahead.

**OAuth scope:** `https://www.googleapis.com/auth/calendar.events` only

**Implement `integrations/gcalendar.py`:** (named `gcalendar` to avoid shadowing stdlib `calendar`)
```python
async def create_event(title: str, start_datetime: str, end_datetime: str, description: str | None = None) -> bool
async def list_upcoming_events(days: int = 7) -> str
```
- Load token from `GOOGLE_TOKEN_PERSONAL` env var (same pattern as Gmail — base64-decoded JSON)
- All external calls: 10-second `httpx` timeout — on timeout return `False`/empty string, log to audit
- Check `has_permission(phone, "calendar")`

**Claude tools:** `calendar_create_event`, `calendar_list_events`

**Done when:** Event created in Calendar. Upcoming events listed correctly.

---

### Task 8 — Google Drive Integration
**Risk: 🔴 High risk — outbound HTTPS to Google Drive API**

⚠️ **Before starting, tell Yuval:**
"I'm about to make outbound calls to the Google Drive API. Please commit and push all current work before I proceed. This step can also be run via Claude Code on claude.ai (web)."

Wait for Yuval's go-ahead.

**OAuth scope:** `https://www.googleapis.com/auth/drive.readonly` only

**Implement `integrations/drive.py`:**
```python
async def search_files(query: str, account_key: str) -> str
```
- Returns file names + view links as clean list
- Load token from the appropriate env var for `account_key` (same base64 pattern)
- All external calls: 10-second `httpx` timeout — on timeout return empty string, log to audit
- Check `has_permission(phone, "drive")`
- Read-only — no write operations

**Claude tool:** `drive_search_files`

**Done when:** File search returns name + link.

---

### Task 9 — Audit Logging
**Risk: 🟢 Safe — code only, file writes only**

**Goal:** Extend the audit trail (started in Task 4) to cover all integration actions.

Extend `security/audit.py` to additionally cover:
- Every Claude tool call attempted
- Every confirmation and cancellation
- Every write executed (success/failure)
- Every unauthorized access attempt

Add `GET /audit` endpoint:
- Protected by `ADMIN_TOKEN` header
- Returns last 50 lines of `audit.log`

**Done when:** Full test session produces clean audit.log with no credential leakage.

---

### Task 10 — End-to-End Testing
**Risk: 🔴 High risk — full network activity across all integrations**

⚠️ **Before starting, tell Yuval:**
"End-to-end testing involves running all integrations simultaneously — this is the highest network activity the bot produces. Please commit and push everything before I proceed. Strongly recommend running this phase via Claude Code on claude.ai (web)."

Wait for Yuval's go-ahead.

Run through every item in `TESTING.md`. Document results. Fix all failures before Task 11.

**Done when:** All TESTING.md items marked ✅.

---

### Task 11 — Railway Production Deploy
**Risk: 🟡 Caution — git push only**

**Note — no staging environment:** There is only one Railway environment. Use `BOT_ENABLED=false` as a manual gate: deploy with it false, verify the deploy succeeded, then flip it true only when ready. If something breaks in production, flip back to false instantly — no redeployment needed.

Tell Yuval you are about to push to production. Wait for a brief confirmation, then proceed.

Steps:
1. Verify all code is committed and pushed to `main`
2. Confirm Railway auto-deployment succeeded (check deploy logs)
3. Set all production env vars in Railway dashboard (including all `GOOGLE_TOKEN_*` values)
4. Set `BOT_ENABLED=false` initially
5. Update Meta webhook URL to Railway production domain
6. Verify HTTPS enforced (Railway provides this)
7. Flip `BOT_ENABLED=true`
8. Test with real WhatsApp number (Rami Levy prepaid SIM — Yuval's dedicated test number, separate from his personal number)
9. Monitor logs for first 10 real messages
8. Update CHANGELOG.md with v1.0.0 release entry

**Done when:** Real WhatsApp message from Yuval's phone gets a correct Claude reply in production.
