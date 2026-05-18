# TESTING.md — Mano Bot

Manual test checklist. Updated during Task 10 (End-to-End Testing).
Mark each test ✅ Pass or ❌ Fail with notes. Claude Code fills in results after Yuval runs tests.

⚠️ **ngrok is a 🔴 step.** Apply the full commit-before-execute protocol (CLAUDE.md) before running it. If ngrok triggers SentinelOne, fall back to Railway: push to main → Railway auto-deploys → use Railway URL in Meta webhook settings.

---

## Local Setup (run before any test)

```bash
# Install dependencies (one package at a time — SentinelOne caution)
pip install fastapi
pip install "uvicorn[standard]"
pip install python-dotenv
# ... (see requirements.txt for full list)

# Configure environment
cp .env.example .env   # then fill in all values

# Unit tests (no server, no network)
pytest tests/

# For webhook integration testing: push to Railway
git add . && git commit -m "your message" && git push
# Railway auto-deploys → use Railway URL in Meta webhook dashboard
```

---

## Task 2 — Echo Bot

| Test | Status | Notes |
|---|---|---|
| Unit tests pass (mocked HTTP, no server needed) | 🔲 | |
| GET /webhook with correct verify_token → returns challenge | 🔲 | |
| GET /webhook with wrong verify_token → 403 | 🔲 | |
| Send WhatsApp message via Railway → receive identical echo back | ✅ | 2026-05-17 via dedicated SIM +972543278745 (Task 2b); Claude integration now layered on top — see Task 3 row |
| Delivery/read receipts produce no reply | ✅ | 2026-05-17 — `parse_incoming` returns None for `statuses` payloads (covered by test_parse_incoming_ignores_status_updates) |

---

## Task 3 — Claude Integration

| Test | Status | Notes |
|---|---|---|
| Send "שלום" → Hebrew reply from Claude (not echo) | ✅ | 2026-05-17 — "הלו הלו" → "היי! במה אפשר לעזור? :-)" (Task 2b live verification) |
| Send English message → Claude replies in same language | ✅ | 2026-05-17 — original spec was "Hebrew by default"; behavior changed mid-task (commit 0f95196) to mirror the user's language per message. Verified: "What's the time in Tokyo right now?" → Hebrew reply (pre-change), then post-switch "What's the time in NYC right now?" → English reply. |
| Send "reply in English" → Claude switches to English | ✅ | 2026-05-17 — "Got it, switching to English from now on!" then subsequent English Q gets English reply. Switch held across turns. |
| Claude is concise and direct (no filler, no pleasantries) | ✅ | 2026-05-17 — "tell me a joke" → "Why don't scientists trust atoms? Because they make up everything!" Short, direct, no LLM dashes. |

---

## Task 4 — Security Layer

| Test | Status | Notes |
|---|---|---|
| POST with missing X-Hub-Signature-256 → 403 | 🔲 | |
| POST with wrong signature → 403 | 🔲 | |
| POST with correct signature → processed normally | 🔲 | |
| Message from unregistered phone → 200, no reply, audit log entry | 🔲 | |
| 21st message from same phone in 10 min → Hebrew rate limit warning | 🔲 | |
| Pending action not confirmed in 5 min → expired, user informed | 🔲 | |
| Pending action cancelled with "לא" → cancelled, bot acks | 🔲 | |
| BOT_ENABLED=false → all messages silently ignored, /health still works | 🔲 | |

---

## Task 5 — Notion Integration

| Test | Status | Notes |
|---|---|---|
| "תוסיף משימה לקרוא מייל" → bot proposes with bucket, asks לאשר? | 🔲 | |
| Reply "כן" → task appears in My Task List in Notion | 🔲 | |
| Reply "לא" → bot confirms cancellation, no task created | 🔲 | |
| "תראה לי את המשימות" → formatted list per bucket → date → priority | 🔲 | |
| "תראה לי משימות ב-Business" → filtered list | 🔲 | |
| "יש לי רעיון — chatbot לדיירים" → routes to Idea Lab, confirms | 🔲 | |
| Idea appears in Idea Lab with status 🌱 Raw | 🔲 | |
| Eden's phone sends task request → Hebrew denial | 🔲 | |

---

## Task 6 — Gmail Integration

| Test | Status | Notes |
|---|---|---|
| "שלח מייל #personal ל-test@example.com" → bot drafts, confirms | ✅ | 2026-05-18 |
| Reply "כן" → email sent from yuvalmanor@gmail.com, appears in Sent | ✅ | 2026-05-18 |
| "שלח מייל #cgm ל-..." → sent from yuval.cgm@gmail.com | ✅ | 2026-05-18 |
| "שלח מייל #deals ל-..." → sent from deals@cgm-ventures.com | ✅ | 2026-05-18 |
| Email tone is casual, no "—" punctuation | ✅ | 2026-05-18 — em-dash scrubber added in agent.py (commit d4ab7f8) as code-level backstop |
| Reply "לא" → email not sent, bot confirms cancellation | ✅ | 2026-05-18 |

### Task 6c — Read + Contacts + Trash + Default routing

| Test | Status | Notes |
|---|---|---|
| "שלח מייל לאליס" (no `#cgm`) → drafts from **personal** account by default | ✅ | 2026-05-18 |
| "שלח מייל from cgm to <real contact>" → bot calls `contacts_lookup`, finds them, asks for content, drafts, confirms, sends | ✅ | 2026-05-18 |
| "send from cgm to <name not in contacts>" → bot reports no match, asks for email address | ✅ | 2026-05-18 |
| "תקרא מיילים from cgm" → returns Primary-tab subject/from/snippet | ✅ | 2026-05-18 |
| "List last 3 emails from personal/deals" → reads Primary inbox (after scope-widening commit c6fb00e) | ✅ | 2026-05-18 — deals required the Workspace fallback (commit da3256d) since business accounts have no category tabs |
| "List last 3 emails from cgm" returned Promotions / Sent items | ✅ Fixed | 2026-05-18 — `search_inbox` now scopes to `in:inbox category:primary` by default (commit d4ab7f8) |
| "delete the last email from cgm" → confirms, trashes message, recoverable from Gmail UI | ✅ | 2026-05-18 — `gmail_trash_email` tool + `gmail.modify` scope (commit da3256d) |

---

## Task 7 — Google Calendar Integration

| Test | Status | Notes |
|---|---|---|
| "תוסיף פגישה עם רועי ביום ראשון ב-10" → bot proposes event, confirms | 🔲 | |
| Reply "כן" → event appears in Google Calendar | 🔲 | |
| "מה יש לי השבוע" → upcoming 7-day events listed | 🔲 | |
| Ambiguous time → bot asks for clarification before confirming | 🔲 | |

---

## Task 8 — Google Drive Integration

| Test | Status | Notes |
|---|---|---|
| "תמצא deal calculator #personal" → file name + link returned | 🔲 | |
| "תמצא חוזה #deals" → searches deals@cgm-ventures.com Drive | 🔲 | |
| File not found → "לא מצאתי קובץ כזה" | 🔲 | |

---

## Task 9 — Audit Logging

| Test | Status | Notes |
|---|---|---|
| After test session: audit.log exists and has entries | 🔲 | |
| All action types logged: message, tool calls, confirms, cancels, unauthorized | 🔲 | |
| No credential values visible in audit.log | 🔲 | |
| Phone numbers masked (last 4 digits only) | 🔲 | |
| GET /audit with correct ADMIN_TOKEN → returns last 50 entries | 🔲 | |
| GET /audit with wrong token → 403 | 🔲 | |

---

## Task 11 — Production (Railway)

| Test | Status | Notes |
|---|---|---|
| Railway deploy succeeds (no build errors) | 🔲 | |
| Meta webhook URL updated to Railway HTTPS domain | 🔲 | |
| Real WhatsApp message from Yuval's phone → Claude reply | 🔲 | |
| Add Notion task → confirm → in Notion | 🔲 | |
| Send email #personal → confirm → sent | 🔲 | |
| Create calendar event → confirm → in Calendar | 🔲 | |
| Railway logs contain no message content | 🔲 | |

---

## Regression Log

Add a row here whenever a bug is found and fixed, to prevent it recurring.

| Date | Bug | Fix | Regression test |
|---|---|---|---|
| — | — | — | — |
