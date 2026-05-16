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

## [2026-05-16] — Task 6a: Gmail integration (code + mocked tests)
- `integrations/gmail.py`: `send_email(to, subject, body, account_key)` decodes the per-account base64 token from env (`GOOGLE_TOKEN_PERSONAL`/`_CGM`/`_DEALS`), builds a `Credentials` object, refreshes via `asyncio.to_thread` if expired, and POSTs an RFC 822 + base64url-encoded message to the Gmail REST API via httpx (10s timeout). All failure modes return False; never raises; never logs the access token.
- `claude_agent/tools.py`: added `gmail_send_email` Anthropic tool with `to`/`subject`/`body`/`account_key` (enum: personal|cgm|deals); description nudges Claude to confirm with the user and avoid LLM-style punctuation per system prompt.
- `claude_agent/agent.py`: dispatch wired for `gmail_send_email`; `TOOL_PERMISSIONS` extended (`gmail_send_email` → `gmail`) so Eden's denied calls return Hebrew error as `tool_result is_error=true` instead of dispatching.
- `scripts/oauth_setup_google.py`: one-off helper that runs `InstalledAppFlow.run_local_server` with gmail.send + calendar.events + drive.readonly scopes, prints a single base64 line to stdout to paste into the matching Railway env var. 🔴 — opens browser + loopback port.
- `tests/test_gmail.py` (12 tests): bad account key; missing/invalid base64/invalid JSON token; happy path with header + RFC822 body inspection; refresh-on-expired-creds; refresh-failure → False; HTTP error → False; httpx timeout → False; never-logs-token check; agent-level dispatch for Yuval (authorized) and Eden (permission_denied tool_result).
- All 77 tests passing (65 prior + 12 new).
- README: "Google Auth Setup" section expanded with Google Cloud Console prereqs (enable APIs, OAuth consent screen test users), exact helper invocations per account, Railway paste steps with a 3-row mapping table, and a verify step.
- **Split rationale:** OAuth flow (browser + loopback) is 🔴 and live verification requires Task 2b SIM. Code/tests proceed now as Task 6a (🟡 — pip already installed in Task 1). Live OAuth + send verification is Task 6b.

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

## [2026-05-16] — Task 4: Security Layer
- `security/auth.py` `authorize_sender`: allowlist check via users.is_authorized; unauthorized attempts logged to audit (phone masked, no message content)
- `security/rate_limiter.py`: sliding-window per-phone limiter, 20 msg / 10 min, in-memory deque; Hebrew warning message; `_reset_for_tests` helper
- `security/audit.py` `log_action`: appends `[iso ts] | phone=****1234 | action=X | details=X | status=X` to `audit.log`; swallows OSError so audit never breaks the request path; AUDIT_LOG_PATH overridable via env
- `claude_agent/agent.py`: PENDING_ACTIONS store + TTL_MINUTES + CONFIRM_WORDS / CANCEL_WORDS constants (consumed by Task 5 onward)
- `main.py`: SEEN_MESSAGE_IDS set + FIFO queue (cap 1000) with `is_duplicate()` helper; POST /webhook pipeline rewritten to: signature → BOT_ENABLED kill switch → parse → dedup → authorize → rate-limit (warning sent via background) → enqueue handler
- `tests/conftest.py`: autouse fixture resets dedup + rate-limit state between tests
- `tests/test_security.py` (15 tests): authorize_sender allow/deny, rate-limit under/over/per-phone/window-expiry, audit masking + OSError-swallow, dedup new/duplicate/FIFO-eviction, POST pipeline for unknown sender / dedup / rate-limited / BOT_ENABLED=false
- Reinstalled `anthropic` (was missing from .venv post sandbox recovery) so router import chain resolves under pytest
- All 47 tests passing (5 agent + 5 router + 22 webhook + 15 security)

## [2026-05-16] — Task 5: live setup complete
- Yuval connected the Mano Bot internal integration to both parent pages: Headquarters (contains My Task List + My Life Buckets) and Idea Lab (contains My Ideas).
- 4 NOTION_* env vars set in Railway (NOTION_TOKEN, NOTION_TASK_DB_ID, NOTION_IDEAS_DB_ID, NOTION_BUCKETS_DB_ID); auto-redeployed.
- Added `scripts/smoke_test_notion.py` — runs `_load_buckets` + `add_task` + `add_idea` against the real API. Useful for re-verifying Notion plumbing when credentials change. Not run yet (deferred with Task 2b live verification).
- Task 5 status: ✅ done. Live WhatsApp→Notion verification will run once the dedicated SIM unblocks Task 2b.

## [2026-05-16] — Task 5: Notion schema alignment
- Reviewed Yuval's actual Notion DBs via MCP — initial implementation assumed a wrong schema (`Name`/`Due` props + `Bucket` as select). Real schema has `Task`/`Idea` titles, `Date` for due dates, and `Bucket` as a *relation* to a separate "My Life Buckets" DB.
- `integrations/notion.py` rewritten: lazy-cached bucket name↔page_id resolver (`_load_buckets`, single query against My Life Buckets), `add_task` sets `Bucket` as `{"relation": [{"id": ...}]}`, unknown bucket names create task without relation (audit `status=ok_no_bucket`).
- `add_idea` uses `Idea` title prop; `list_tasks` extracts `Task` title and resolves `Bucket` relation back to a name via the reverse cache; filter-by-bucket uses `relation.contains` predicate.
- Added `NOTION_BUCKETS_DB_ID` env var; conftest test default added.
- Tests rewritten: 14 → 14 mocked-httpx tests (real-schema variants + bucket cache load-once test), all green; 65 total passing.
- README "Notion setup" section rewritten with the actual DB IDs (Headquarters parent + Idea Lab parent), the easy "connect Mano Bot to parent pages" step, and a note that the 15 SYSTEM_PROMPT buckets must exist as pages in My Life Buckets.

## [2026-05-16] — Task 5: Notion Integration
- `integrations/notion.py`: direct Notion REST API via httpx with 10s timeout, expects DB schema (Name/Bucket/Due/Priority for tasks, Name/Description for ideas). `add_task`, `add_idea` return bool; `list_tasks(filter_bucket)` returns Hebrew-friendly string grouped by bucket → due → priority. All errors logged to audit, never raise.
- `claude_agent/tools.py`: 3 Anthropic tool definitions (`notion_add_task` with 15-bucket enum, `notion_list_tasks`, `notion_add_idea`).
- `claude_agent/agent.py`: rewritten with tool-use loop (MAX_TOOL_ITERATIONS=5). Maps tool name → required permission key (`notion_add_task`/`notion_list_tasks` → `notion`; `notion_add_idea` → `idea_lab`); denied calls return Hebrew error as `tool_result is_error=true` instead of dispatching. History stores only user/assistant text turns; tool_use/tool_result blocks live inside a single turn only.
- `tests/test_notion.py` (10 tests): add_task happy path + due_date + HTTP error + timeout; add_idea with/without description; list_tasks empty/HTTP-error/with-bucket-filter; list_tasks formats by bucket with Hebrew title extraction.
- `tests/test_agent.py` rewritten (9 tests): existing 5 tests updated to use typed mock blocks + stop_reason; 4 new tests for tool-use (authorized dispatch, Eden permission-denied tool_result, list_tasks dispatch, MAX_TOOL_ITERATIONS exhaustion).
- README: full "Notion setup" section with exact links/URLs — integration creation at notion.so/profile/integrations, DB schemas with exact property names, the easy-to-miss "Connections → Connect to" step, DB ID extraction from URL, env var placement.
- All 61 tests passing (47 prior + 14 new).
- **Deferred:** live Notion verification — runs after `NOTION_TOKEN`/`NOTION_TASK_DB_ID`/`NOTION_IDEAS_DB_ID` are set up per README and a dedicated SIM unblocks Task 2b.

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
