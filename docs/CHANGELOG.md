# CHANGELOG.md — Mano Bot

Claude Code must add an entry here after completing each task.

Format: `## [YYYY-MM-DD] — [description]` followed by bullet points.

---

## [2026-06-13] — Task 13: Phase 2 — dedicated Knowledge DB
- New dedicated Notion DB for saved articles/links/references, separate from the Idea Lab. Lean schema: `Title` (title) / `Topic` (multi_select, free-form tags) / `Source` (url) / `Saved` (created_time); distilled content + link in the page body.
- `config.NOTION_KNOWLEDGE_DB_ID` — **optional** env var (not in REQUIRED_VARS); feature returns `not_configured` until set, so code deploys safely before the DB id exists.
- `integrations/notion.py`: `add_knowledge` / `list_knowledge` / `get_knowledge`, reusing phase-1 helpers (`_idea_body_blocks`, `_fetch_block_text`, `_fetch_comments_text`, `_recent_duplicate_exists`, title/multi_select/url extractors). 5-min dedupe on save.
- New tools `notion_save_knowledge` / `notion_list_knowledge` / `notion_get_knowledge` (perm `knowledge`, Yuval only; save tool is in the single-call guard). System prompt reworked: link/article saving + "save to my DB" routes to the Knowledge DB; "I have an idea" stays Idea Lab; older Idea-Lab items still readable via `notion_get_idea`.
- Tests: +10 in `test_notion.py` / `test_agent.py` (props/body build, dedupe, topic grouping, get assembly, ambiguous, `not_configured` guards, dispatch, Eden denial). 225/225 passing.
- Rollout pending: create the 📚 Knowledge DB in Notion, share it with the bot integration, set `NOTION_KNOWLEDGE_DB_ID` in Railway.

## [2026-06-13] — Task 12: Knowledge DB — read idea content + open links
- New `integrations/web.py`: `fetch_url(url)` fetches a page and returns readable text. Stdlib `html.parser`-based HTML→text (no new pip dep), 10s timeout, ~8000-char cap, SSRF guard (http/https only; blocks localhost/private/link-local hosts). Returns `""` on any failure.
- `integrations/notion.py`: new `get_idea(title)` reads one idea's full content (Description + page body blocks + comments) by the same fuzzy-title match as archive/comment; returns `(status, content)`. `add_idea` extended with optional `content` + `source_url` → writes a source bookmark and chunked (≤1900-char) content paragraphs into the page body. Existing callers unchanged.
- New tools `fetch_url` (perm `web`, given to Yuval) and `notion_get_idea` (perm `idea_lab`); `notion_add_idea` schema gains `content`/`source_url`. Both new tools are read-only (not in the single-call guard).
- System prompt: new "Knowledge DB" subsection (save link → fetch_url + distill + add_idea with content/source_url; recall → list_ideas + get_idea + optional fetch_url) and updated honesty note.
- Tests: new `tests/test_web.py`; extended `tests/test_notion.py` (body-block build + chunking + get_idea ok/not_found/ambiguous/error) and `tests/test_agent.py` (fetch_url/get_idea dispatch, Eden `web` denial, content/url passthrough). 215/215 passing.
- Live verification pending (🔴): outbound to Notion + arbitrary web.

## [2026-05-19] — Task 7b iteration #4: drop event link from reply
- User feedback: do not include the Calendar event URL in the WhatsApp reply.
- `claude_agent/agent.py` dispatch: `calendar_create_event` success now returns plain `"ok"` instead of `"ok: event created. link=<htmlLink>"`. The model never sees the link, so it can't surface it.
- `claude_agent/system_prompt.py`: the Calendar "Creating events" rule now says reply with a short confirmation only and explicitly forbids the link/URL.
- `integrations/gcalendar.create_event` still captures the htmlLink in its dict return — unused by the dispatch, but kept for future use (e.g. audit/debug).
- Tests still pass (186/186) - no test was asserting link content in the tool_result.

## [2026-05-19] — Task 7b iteration #3: multi-turn context rule (stop re-verifying prior turns)
- Observed live: after a successful cancel ("בוטל ✅"), the next user message ("set a reminder to call X tomorrow at 16") triggered Mano to re-call `calendar_cancel_event` for the dentist and narrate "didn't find it — maybe already cancelled" before handling the new request. Wasted tool call, extra latency, confusing UX.
- `claude_agent/system_prompt.py`: new "Multi-turn context" section. Rules: (1) trust prior assistant confirmations - never re-verify with a tool call; (2) treat each user message as a standalone request unless the wording explicitly references the previous turn (pronouns, "also", "the same one"); (3) never narrate a previous turn's result back in a new turn. Placed just before "Avoiding sycophancy" since both target conversation-level behavior.
- Prompt-only change. 186 tests still pass.

## [2026-05-19] — Task 7b iteration #2: calendar cancel + default 10-min alert
- New `integrations/gcalendar.cancel_event_by_query(query, days_window=60)` — searches upcoming events with the Calendar API's `q=` free-text filter, deletes on a unique match, returns `(status, summaries)` mirroring the `gmail_trash_email` ambiguous/not_found pattern. Deletion is permanent (no Trash equivalent on Calendar).
- New Claude tool `calendar_cancel_event`. Wired through `TOOL_PERMISSIONS`, `SINGLE_CALL_TOOLS` (with `query` added to the primary-key fallback so the duplicate guard still works), and the agent dispatch.
- `integrations/gcalendar.create_event`: new `alert_minutes` parameter (default 10). Builds `reminders.overrides=[{popup, minutes}]`. Sentinel `-1` → `useDefault=False, overrides=[]` (explicit no-alert).
- `claude_agent/tools.py`: `calendar_create_event` schema gains optional `alert_minutes` with default-10 / -1=no-alert semantics in the description.
- `claude_agent/agent.py` dispatch: when Claude omits `alert_minutes`, dispatch passes 10. When it passes -1, forward as-is.
- `claude_agent/system_prompt.py`: Calendar section restructured into "Creating events" + "Cancelling events". Creating rule: ALWAYS ask about the alert in the confirmation message (default 10 min); use the per-turn date directive for relative dates; include the htmlLink in the reply after successful create. Cancelling rule: always confirm with title+start time; handle ambiguous/not_found explicitly; deletion is permanent (no 30-day recovery like Gmail trash).
- 186 tests pass (was 175). 11 new: 3 alert paths (default-10, no-alert, custom), 5 cancel paths (not_found, ambiguous, single match deletes, search HTTP error, delete HTTP error), 3 agent-dispatch (cancel happy path, alert_minutes default 10, alert_minutes -1 passthrough).

## [2026-05-19] — Task 7b iteration: date awareness + default 1h + calendar error surfacing
- Root cause of last night's "phantom event" (Calendar API returned 200 OK but Yuval couldn't find the event): the model had no anchor for "today" and resolved "tomorrow" against an imagined date from its training-window past. Event was created — just on the wrong day.
- `claude_agent/agent.py`: new `_date_directive()` injects "Today is <weekday>, <YYYY-MM-DD> in Israel local time (Asia/Jerusalem)" into every user turn, alongside the existing language directive. Code-level anchor so relative dates ("tomorrow", "next Sunday", "this week") resolve against actual today, not the model's prior.
- `claude_agent/agent.py` dispatch: `calendar_create_event` now defaults `end_datetime = start + 1h` when the model omits it. Code-level default the prompt can't bypass.
- `claude_agent/tools.py`: `end_datetime` marked optional in the tool schema; description tells Claude to omit it when the user gives no duration.
- `integrations/gcalendar.py`: `create_event` now returns a dict (`ok`, `html_link`, `reason`) instead of bare bool. The htmlLink from the Calendar API is surfaced back through the tool_result so future "set" replies can include a link to the actual event.
- `claude_agent/agent.py` dispatch: on `ok=False`, the tool_result is now an emphatic "FAILED... event was NOT created... do NOT claim success" string instead of the bare `"error"` — defense against the model narrating success when the write failed.
- `requirements.txt`: added `tzdata==2024.2` so `zoneinfo("Asia/Jerusalem")` works on Windows dev (Railway already has system tzdata).
- Tests: 175 pass (was 171). New: default-1h, error-tool-result, date-directive renders IL date, date-directive injected into user message. 5 existing create_event tests migrated to dict return.

## [2026-05-18] — Task 6d code done: per-user Google account resolution + Eden gmail wiring
- `users.py`: each user record now carries a `google_tokens` map (`account_key` → config attribute name). Yuval has all three; Eden has `cgm` → `GOOGLE_TOKEN_EDEN_CGM`. New helper `get_google_token_env_name(phone, account_key)`. Eden now has `gmail` in `permissions` (no notion / calendar / drive yet).
- `config.py` + `.env.example`: optional `GOOGLE_TOKEN_EDEN_CGM` (`os.getenv`, default `""`). Dev environments without it still boot.
- `integrations/gmail.py`, `integrations/contacts.py`, `integrations/drive.py`: all public funcs (`send_email`, `search_inbox`, `trash_by_query`, `lookup_contact`, `search_files`) accept optional `user_phone`. Token resolution flows through the user-record mapping — Eden's `cgm` → her token, not Yuval's. `user_phone=None` falls back to Yuval's tokens for service-internal callers. Audit lines now carry the actual caller phone (was always `""`).
- `claude_agent/agent.py`: `_dispatch_tool` receives and threads `user_phone` to gmail / contacts / drive calls.
- `claude_agent/system_prompt.py`: Users section updated; new "Per-user account routing" section makes the per-caller mapping explicit and bans cross-user fallthrough in prose.
- 171 tests pass (was 161). New `tests/test_user_account_resolution.py` (10) covers: yuval/eden mapping, unknown-phone, none-phone Yuval fallback, gmail Eden-cgm vs Yuval-cgm token selection, Eden personal-fails-closed, Eden cgm with no EDEN_CGM env var fails closed, contacts/drive same routing. Three existing tests updated to expect the new `user_phone` kwarg on dispatch.
- OAuth + Railway env var for Eden's account remains TODO — code is ready, awaiting Eden running `scripts/oauth_setup_google.py --manual` for `edeng.cgm@gmail.com` and pasting the base64 token into Railway as `GOOGLE_TOKEN_EDEN_CGM`.

## [2026-05-18] — Task 6c live-verified end-to-end (✅ Done)
- Iterated during live verify: (1) read scope widened from cgm-only to all three accounts after the re-OAuth, (2) `search_inbox` now scopes to `in:inbox category:primary` by default with a single-retry fallback when zero hits — fixes Google Workspace accounts (deals@cgm-ventures.com) that don't have category tabs enabled, (3) em-dash / en-dash scrubber on every outgoing reply (hard backstop for the prompt's "no LLM punctuation" rule the model kept violating).
- Added `gmail_trash_email` (move to Trash via `messages.trash`, recoverable 30 days). Required `gmail.modify` scope and a second OAuth re-run on all three accounts.
- Final tool surface for Gmail: `gmail_send_email`, `gmail_search_inbox`, `gmail_trash_email`, `contacts_lookup`.
- 161 tests pass (was 136 at start of 6c).

## [2026-05-17] — Task 6c: Gmail read + contacts lookup + default-personal routing (code done)
- `integrations/contacts.py` (new): People API lookup against both `searchContacts` (saved) and `otherContacts:search` (anyone you've emailed). Returns deduped `{name, email}` list. 10s timeout, never raises.
- `integrations/gmail.py`: new `search_inbox(query, account_key, max_results)` using Gmail `messages.list` + `messages.get` (format=metadata). Expanded `ALL_SCOPES` constant — credentials now load with gmail.send + gmail.readonly + contacts.readonly + contacts.other.readonly + calendar.events + drive.readonly.
- `claude_agent/tools.py`: new tools `gmail_search_inbox` (cgm-only) and `contacts_lookup` (cgm-only).
- `claude_agent/agent.py`: dispatch + permission entries (`gmail`) for the two new tools; contacts result formatted as "matches:\n…" string for Claude.
- `claude_agent/system_prompt.py`: default account = personal when `#cgm`/`#deals` not stated; multi-turn "send from cgm to <name>" flow (contacts_lookup → ask-if-missing → ask-for-content → draft casual → confirm); cgm-only read rule.
- `scripts/oauth_setup_google.py`: SCOPES expanded — existing tokens (send-only) will need re-OAuth before read + contacts work.
- README: People API added to Cloud Console enable list; OAuth scope list updated; re-OAuth note.
- TASKS.md: 6b folded into new 6c; 6d added (Eden wiring).
- TESTING.md: new Task 6c subsection (6 rows).
- 146 tests pass (was 136). New: 5 in `tests/test_contacts.py` (no-token, merge+dedupe, timeout, 4xx-on-one-endpoint, ignore-no-email-rows); 5 in `tests/test_gmail.py` (bad account, happy path summary format, empty list, list HTTP error, timeout).

## [2026-05-17] — Idea Lab hardening + language-leak code fix + KNOWN_ISSUES.md
- `claude_agent/agent.py`: per-message language detection (Hebrew chars → he, else en) injects a per-turn directive into the user message. Prompt-only language mirroring kept leaking Hebrew on tool flows after three prompt rewrites; this is the code-level backstop.
- `claude_agent/agent.py`: per-turn single-call guard for write/mutate tools (`notion_add_idea/task`, `notion_archive_*`, `calendar_create_event`, `gmail_send_email`). Second invocation on the same primary key in one `run()` is short-circuited with a BLOCKED tool_result.
- `integrations/notion.py`: `add_idea` now accepts optional bucket (resolved against My Life Buckets, same path as `add_task`); 5-minute dedupe pre-query on both `add_task` and `add_idea`; return type narrowed to string status (`ok` / `ok_no_bucket` / `duplicate` / `error`). New `add_idea_comment` (Notion page comment via `/v1/comments`, fuzzy-title match), `archive_idea`, and `list_ideas`.
- `claude_agent/tools.py`: bucket on `notion_add_idea`; new tools `notion_comment_idea`, `notion_list_ideas`, `notion_archive_idea`.
- `claude_agent/system_prompt.py`: Idea Lab is now bucket-aware; explicit end-of-flow rule after add/comment; "do not search Tasks for Ideas" cross-DB ban; new "Honesty about capabilities" section ("I don't have a way to do X" instead of fishing for context); anti-sycophancy section.
- 136 tests pass (up from 124): added coverage for idea bucket happy path + unknown bucket fallback, both add tools' duplicate short-circuit, `add_idea_comment` (ok/not_found/ambiguous), `archive_idea` (3 branches), `list_ideas` (group-by-bucket + unknown-bucket-empty).
- Root cause of the two "Recipe App" rows: Claude was firing `notion_add_idea` twice within a turn (dedupe pre-query + per-turn guard now prevent it). Misconfigured local `NOTION_IDEAS_DB_ID` (was pointing at My Life Buckets DB) found and corrected mid-session — Railway env was unaffected.
- New file: [docs/KNOWN_ISSUES.md](KNOWN_ISSUES.md) with ISSUE-001 — bogus "already added a moment ago" tail message still appears after the comment flow ends with "no", even after the per-turn guard. Hypothesis: the duplicate add happens in the *next* WhatsApp turn (its own `run()`), so the per-turn guard set is fresh and the dedupe query's `duplicate` return gets narrated. Suggested next step: change dispatch so a `duplicate` return becomes a silent no-op tool_result; consider persisting `invoked_once`-like state across turns per-phone with a short TTL.

## [2026-05-17] — Task 3 closed out + language-mirroring behavior change
- All 4 TESTING.md Task 3 rows live-verified via dedicated SIM (Hebrew default, English-input handling, explicit "reply in English" switch, conciseness/tone)
- Behavior change: system prompt now mirrors the user's language per message instead of defaulting to Hebrew and requiring an explicit switch. Hebrew register guidance retained for Hebrew messages.

## [2026-05-17] — Task 2b: Live WhatsApp→Claude end-to-end verified
- Dedicated SIM activated (+972543278745, 012 Mobile); registered with Meta Cloud API as WABA `951549647669591` / phone-number ID `1140561589137653`
- Permanent system-user access token issued (`whatsapp_business_messaging` + `whatsapp_business_management`, no expiration); `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` updated in Railway
- Fresh Anthropic API key created (previous Console workspace never existed → 401s); auto-reload billing configured
- **Bug fix:** `whatsapp/webhook.py` now prepends `+` to bare sender phones — Meta delivers `from` without the `+`, but `users.py` keys are `+`-prefixed, so the exact-match allowlist was silently denying real inbound messages. Tests had been passing because constructed payloads used the `+` form. Added a regression test pinning the bare-digit case.
- Live confirmation: WhatsApp "הלו הלו" → "היי! במה אפשר לעזור? :-)"
- Unblocks Tasks 3/5/6b/7b/8b live verification.

## [2026-05-16] — Task 9: Audit endpoint + confirm/cancel logging
- Added `GET /audit` admin endpoint protected by `X-Admin-Token` (constant-time compare), returns last 50 lines as text/plain
- Added `security.audit.tail(n)` helper for reading recent log lines
- Router now audit-logs `user_confirm` / `user_cancel` when an incoming message matches the existing CONFIRM_WORDS / CANCEL_WORDS sets (case-insensitive, trimmed)
- 9 new tests (116 total) passing. Tool invocations, write outcomes, and unauthorized attempts were already covered across integrations + security layer.

## [2026-05-16] — Task 8a: Google Drive code + mocked tests
- Implemented `integrations/drive.py` (`search_files`, read-only) using the same base64-env-var token pattern as gmail/gcalendar; query escaping handles apostrophes
- Added `drive_search_files` Claude tool + agent dispatch + `drive` permission mapping
- 13 new tests (107 total) passing; live verification deferred to Task 8b (gated on Task 2b SIM). OAuth helper already includes `drive.readonly` scope so no re-OAuth needed.

## [2026-05-16] — Task 7a: Google Calendar code + mocked tests
- Implemented `integrations/gcalendar.py` (`create_event`, `list_upcoming_events`) following the gmail.py pattern (base64 env-var token, httpx, asyncio.to_thread refresh)
- Added `calendar_create_event` and `calendar_list_events` Claude tools + agent dispatch + `calendar` permission mapping
- 17 new tests (94 total) passing; live verification deferred to Task 7b (gated on Task 2b SIM). OAuth helper already includes `calendar.events` scope so no re-OAuth needed.

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

## [2026-05-23] — Task 10: End-to-end testing complete
- Core flows verified live via WhatsApp: Claude conversation, Gmail (send/read/trash/contacts), Google Calendar (create/list/cancel/alerts), Notion (tasks + ideas).
- Skipped: Task 4 security live tests (unit tests cover signature/rate-limit paths), Task 8 Drive (deferred), Task 9 audit endpoint (deferred).
- TESTING.md updated with all results.

## [2026-05-23] — Task 8b: Google Drive live verification deferred
- Live testing skipped for now. Code (Task 8a) is complete and tested with mocked HTTP. Resume when Drive search is needed in production.

## [2026-05-23] — Task 7b: Google Calendar live verification ✅
- All calendar flows verified end-to-end via WhatsApp: create event with relative date ("מחר ב-10"), default 1h duration + 10-min alert, custom alert minutes, no-alert (-1), list upcoming events, cancel by name (unique match), cancel with ambiguous match.
- No code changes — prompt-only and dispatch logic from 7b iterations held up in production.

## [2026-05-16] — Task 6b: Live OAuth tokens in Railway (end-to-end deferred)
- `scripts/oauth_setup_google.py` extended with `--manual` flow: prints auth URL, user signs in in their own browser, copies the failed-redirect URL (browser shows ERR_CONNECTION_REFUSED on http://localhost:8765, expected — no listener), pastes back, script extracts the code and POSTs once to oauth2.googleapis.com/token. No port binding, drops the OAuth risk from 🔴 to 🟡. README "Run the helper" section rewritten with the manual walkthrough.
- Discovered loopback flow won't work cross-machine for Desktop OAuth clients (the original "run on Claude Code web" plan), pivoted to the manual flow.
- Set `OAUTHLIB_INSECURE_TRANSPORT=1` in the manual flow so oauthlib will parse the http://localhost authorization_response (loopback only, documented workaround).
- Ran OAuth 3× locally (personal/cgm/deals), one base64 token pasted into each of `GOOGLE_TOKEN_PERSONAL` / `GOOGLE_TOKEN_CGM` / `GOOGLE_TOKEN_DEALS` in Railway. First personal-token attempt was leaked into chat context — revoked at myaccount.google.com/permissions, re-issued, never reshared. Tokens never written back to local .env.
- Railway boot crashed on first redeploy with `RuntimeError: Missing required environment variables: NOTION_BUCKETS_DB_ID` — unrelated to Gmail, just an orphaned gap from Task 5. Set the var to `2dd484a7ece581618bc0f697560561dd` (My Life Buckets DB page ID), Railway redeployed clean → Active. Tripped a second time afterwards: Railway holds edited variables in a "staged changes" state until you click the explicit **Apply Changes** / **Save** button in the Variables tab top banner — without that, redeploys silently use the previous values. Clicking Apply finally took it live.
- **Deferred:** live WhatsApp → Gmail send test (`תשלח מייל ל-... מהאישי "x" "y"` → confirm → `כן` → check Sent folder). Same blocker as Tasks 3/5: needs the dedicated SIM from Task 2b.

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
