# CHANGELOG.md — Mano Bot

Claude Code must add an entry here after completing each task.

Format: `## [YYYY-MM-DD] — [description]` followed by bullet points.

---

## [2026-05-09] — Project Definition
- Defined project scope, users, integrations, behavior rules
- Established two-user model (Yuval + Eden) with phone-based identification
- Defined integration map (Gmail ×3, Calendar, Drive ×3, Notion, Idea Lab)

## [2026-05-10] — Design Complete
- Finalized Notion structure (HQ + Idea Lab)
- Defined service routing logic and confirmation pattern for all writes
- Wrote and locked system prompt
- Selected stack: Python + FastAPI + Railway + Meta Cloud API

## [2026-05-11] — Infrastructure & Repo Setup
- Meta Cloud API: test number active (+1 555 645-4608), token generated, webhook confirmed
- Railway: account created, connected to GitHub
- GitHub: repo `mano-bot` created (private)
- Produced initial repo documentation set: CLAUDE.md, TASKS.md, SECURITY.md, DECISIONS.md, CHANGELOG.md, TESTING.md

## [2026-05-15] — SentinelOne Incident & Hardened Dev Protocol
- SentinelOne EDR quarantined all project files and force-closed Claude Desktop mid-build
- Root cause: ngrok + Python port binding + outbound API calls triggered C2 behavioral detection
- IT lowered SentinelOne sensitivity; files not recoverable but GitHub repo intact
- Decisions D-011, D-012, D-013 added: no ngrok, commit-before-execute protocol, web fallback
- CLAUDE.md: added full SentinelOne section with risk classification table and bypass rules
- TASKS.md: every task now has a risk level (🟢/🟡/🔴) and pre-execution protocol for 🔴 tasks
- DECISIONS.md: three new decisions documenting the hardened dev approach

## [2026-05-15] — Design Revision: Remaining Gaps Closed
- `whatsapp/client.py`: 10-second timeout specified (was missing while all integration clients had one)
- `router.py`: top-level try/except guarantees user always receives a Hebrew reply, even on unhandled exceptions
- Task 11: `BOT_ENABLED=false` gate formalised as the no-staging-env mitigation; deploy steps updated
- SECURITY.md Known Gaps: token refresh failure mode clarified (manual revocation, not normal expiry)

## [2026-05-15] — Design Revision: Production Gaps Addressed

- D-004 updated: rolling 5-message conversation history (in-memory, resets on restart)
- D-014 added: message deduplication via in-memory seen-ID set (prevents duplicate writes on Meta retry)
- D-015 added: OAuth tokens stored as Railway env vars (not filesystem — Railway filesystem is ephemeral)
- D-016 added: async webhook processing — return 200 immediately, process in BackgroundTask
- D-017 added: pending action overwrite behavior defined (new message discards waiting action)
- D-018 added: 10-second timeout on all external API calls, Hebrew error on timeout
- SECURITY.md: renumbered controls, added deduplication as control #1, updated credential hygiene for token env vars
- CLAUDE.md: env vars updated with GOOGLE_TOKEN_* vars, clarified GOOGLE_CREDENTIALS_JSON vs tokens
- TASKS.md: pipeline, agent, and integration specs updated throughout

---

<!-- Claude Code appends below this line after each completed task -->

## [2026-05-16] — Task 2b: Live echo test via Railway (partial)
- Railway project created and deployed successfully (web-production-f95ae.up.railway.app)
- All 14 env vars set in Railway (real WhatsApp credentials + placeholders for unused integrations)
- Webhook URL registered in Meta, `messages` field subscribed
- POST→200 confirmed via Meta dashboard "Test" button — plumbing is proven end-to-end
- **Blocked:** real WhatsApp message→webhook delivery requires either (a) a dedicated SIM registered as the bot's WhatsApp Business number, or (b) Meta app publication. Personal number (+972542159121) cannot be registered — already a WhatsApp account. Meta test number is sandbox-only and doesn't receive real incoming messages.
- **Resume when:** dedicated SIM acquired (any cheap prepaid, e.g. Rami Levy ~₪10)

## [2026-05-15] — Task 1: Project Scaffold
- Created repo structure: main.py, config.py, users.py, router.py, plus whatsapp/, claude_agent/, integrations/, security/ packages with stubs
- requirements.txt pinned, .env.example with all required vars, .gitignore covering .env/tokens/audit.log, Procfile for Railway
- system_prompt.py contains the locked SYSTEM_PROMPT constant
- pytest + pytest-asyncio installed; `pytest --collect-only` runs cleanly (0 tests)

## [2026-05-16] — Task 2: Echo Bot (code + tests; live webhook test deferred)
- Installed fastapi, uvicorn[standard], python-dotenv, httpx one at a time (SentinelOne bypass)
- `whatsapp/webhook.py` `parse_incoming`: extracts from_phone/message_type/text/message_id; ignores status updates, non-text messages, malformed payloads
- `whatsapp/client.py` `send_message`: POST to Graph API v19.0 with 10s httpx timeout; returns False on timeout/HTTP error; never logs the access token
- `security/auth.py` `verify_webhook_signature`: HMAC-SHA256 with constant-time compare (pulled forward from Task 4 since main.py needs it)
- `main.py`: GET /webhook verification handshake; POST /webhook verifies signature → 403, parses → echoes via FastAPI BackgroundTask, always 200 on parseable requests
- `tests/test_webhook.py` (22 tests, all green): parse_incoming branches, send_message success/HTTP-error/timeout/no-token-leak, signature verify happy & sad paths, GET handshake, POST signature rejection, POST echoes text, POST ignores status updates, POST tolerates non-JSON
- conftest.py at repo root populates dummy env vars before config import (only fills empty/unset vars)
- **Deferred:** live uvicorn+ngrok end-to-end test against Meta — will run via Railway deploy in Task 11 instead of local ngrok

## [2026-05-16] — Task 3: Claude Integration
- Installed anthropic SDK
- `claude_agent/agent.py`: `async def run(user_phone, message)` with CONVERSATION_HISTORY dict, MAX_HISTORY_TURNS=5, calls claude-sonnet-4-6 with ephemeral cache_control, 1024 max_tokens, empty tools list; on API error returns Hebrew fallback "משהו השתבש, נסה שוב"
- `router.py`: `async def handle_message(from_phone, text)` wraps entire flow in try/except, calls agent.run, sends reply via whatsapp.client.send_message, sends Hebrew fallback on any exception
- `main.py`: updated POST /webhook BackgroundTask to call router.handle_message instead of _echo_task
- `tests/test_agent.py` (5 tests): single message, conversation history, history trimming (while-loop to enforce MAX_HISTORY_TURNS), API error handling, separate histories per user
- `tests/test_router.py` (5 tests): normal path, Claude error fallback, WhatsApp send error fallback (nested try/except), unhandled exception fallback, different phone routing
- Updated `tests/test_webhook.py` webhook tests to mock router.handle_message instead of removed send_message, renamed test names to reflect new routing
- All 32 tests passing (5 agent + 5 router + 22 webhook)
- **Deferred:** live Claude conversation via WhatsApp — will test via Railway in Task 2b once dedicated SIM available
- **Recovery note:** original sandbox push was blocked by a 403 from its local git proxy; commit was exported via `git format-patch`, applied locally with `git am`, and pushed to `origin/main` (local hash `333a279`). Verified 32/32 tests pass on local Python 3.14.
