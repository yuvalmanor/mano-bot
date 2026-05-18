# DECISIONS.md — Architecture & Design Decisions

Records significant decisions made during design and development.
Before overriding any decision, understand the rationale. If you do override, document it here.

---

### D-001 — Stack: Python + FastAPI

**Decision:** Python + FastAPI, not n8n or no-code tools.
**Rationale:** Yuval has engineering background — code is maintainable. Full control over security logic. n8n hides what's happening and limits customization.
**Alternatives:** n8n (rejected), Make/Zapier (rejected — too limited)
**Date:** 2026-05-10

---

### D-002 — Hosting: Railway

**Decision:** Railway for hosting.
**Rationale:** Auto-deploys from GitHub, provides HTTPS automatically (required by Meta), ~$5/mo, easy env var management.
**Note:** `Procfile` is used for the process command (`web: uvicorn ...`). Railway detects it via Nixpacks — this is intentional and works correctly; do not replace with `railway.json` unless explicitly deciding to change the build system.
**Date:** 2026-05-10

---

### D-003 — WhatsApp: Meta Cloud API directly

**Decision:** Meta Cloud API, not Twilio.
**Rationale:** Free for user-initiated messages. Twilio adds per-message cost. Direct = less abstraction.
**Date:** 2026-05-10

---

### D-004 — Rolling 5-message conversation history

**Decision:** Claude receives the last 5 messages per phone number (user + assistant turns), stored in memory.
**Rationale:** Without any history the bot cannot handle references to prior context ("follow up on that email", "yes, that one") — a day-1 UX failure. 5 messages covers the vast majority of multi-turn interactions (confirm flows, clarifications, follow-ups) without meaningful memory risk. No persistence — history resets on process restart, which is acceptable. Full history storage deferred to v2.
**Implementation:** `CONVERSATION_HISTORY: dict[str, list[dict]]` in `claude_agent/agent.py`, max 5 user+assistant turn pairs (10 entries), trimmed oldest-first when full.
**Privacy note:** History lives only in process memory — it is never written to disk or logs.
**Date:** 2026-05-15

---

### D-005 — Confirm before all writes

**Decision:** Every write (Notion, Gmail, Calendar, Drive) requires explicit user confirmation.
**Rationale:** Bot has access to production accounts — mistakes are real. 5-minute TTL prevents stale confirmations.
**Date:** 2026-05-10

---

### D-006 — Minimal Google OAuth scopes

**Decision:** Only minimum scopes per integration.
- Gmail: `gmail.send` only
- Calendar: `calendar.events` only
- Drive: `drive.readonly` only
**Rationale:** If credentials are compromised, blast radius is limited. Bot cannot read emails.
**Date:** 2026-05-11

---

### D-007 — Silent 200 for unknown senders

**Decision:** Unknown phone numbers get 200 with no reply. Bot does not reveal its existence.
**Rationale:** Returning an error reveals the endpoint is active. Silent 200 is standard webhook security practice.
**Date:** 2026-05-11

---

### D-008 — Partial phone masking in audit log

**Decision:** Phones in audit.log show last 4 digits only (e.g. `+XXX...1234`).
**Rationale:** Audit log may be seen during debugging. Full number is unnecessary PII.
**Date:** 2026-05-11

---

### D-009 — Security before integrations

**Decision:** Task 4 (security layer) must complete before Tasks 5–8 (integrations).
**Rationale:** Adding real account access before hardening auth is risky. Security-first is non-negotiable.
**Date:** 2026-05-11

---

### D-010 — Eden: no permissions in v1

**Decision:** Eden starts with empty permissions. Gmail/Calendar/Drive TBD, Notion explicitly denied.
**Rationale:** Better to start with no access and add explicitly than to grant and revoke.
**Known limitation:** Changing permissions currently requires editing `users.py` and redeploying. This is acceptable for a 2-user system with infrequent permission changes. A config-driven permission system is a v2 concern.
**Date:** 2026-05-10

---

### D-014 — Message deduplication via seen message IDs

**Decision:** Track the last 1000 `message_id` values in an in-memory set. Drop any webhook that arrives with a seen ID before any processing.
**Rationale:** Meta Cloud API has at-least-once delivery — the same webhook can arrive twice, especially under load or after retries. Without deduplication, a double delivery could fire two Notion writes or send two emails after a single "כן". 1000 IDs covers hours of traffic for 2 users with negligible memory cost.
**Implementation:** `SEEN_MESSAGE_IDS: set[str]` in `main.py`, checked immediately after signature verification. Evict oldest entry when set exceeds 1000 (use a deque for FIFO ordering).
**Date:** 2026-05-15

---

### D-015 — OAuth tokens stored as env vars, not filesystem

**Decision:** Google OAuth tokens are stored as base64-encoded env vars in Railway (`GOOGLE_TOKEN_PERSONAL`, `GOOGLE_TOKEN_CGM`, `GOOGLE_TOKEN_DEALS`), not as `token_*.json` files on disk.
**Rationale:** Railway has an ephemeral filesystem — files written during a running process are lost on redeploy. Storing tokens as files means every deploy breaks Gmail/Calendar/Drive until the user re-runs the OAuth flow. Env vars in Railway persist across deploys. `google-auth` supports loading credentials from a dict rather than a file.
**OAuth setup flow:** Run the browser flow locally once per account → serialize the resulting token to JSON → base64-encode → paste into Railway env var. Document in README.
**`GOOGLE_CREDENTIALS_JSON`** — this is the static OAuth client credentials (client_id, client_secret), downloaded once from Google Cloud Console and never changes. Keep as-is. The per-user tokens above are separate.
**Date:** 2026-05-15

---

### D-016 — Async webhook processing (return 200 immediately)

**Decision:** `POST /webhook` returns 200 to Meta immediately after signature verification and deduplication, then processes the message in a FastAPI `BackgroundTask`.
**Rationale:** Meta expects a 200 within ~20 seconds. A Claude API call + an integration call (Notion, Gmail, etc.) can exceed this under normal latency. If Meta doesn't get a timely 200, it retries — triggering duplicate processing. Returning 200 immediately and processing in the background eliminates the timeout window entirely.
**Implementation:** FastAPI's `BackgroundTasks` — no additional infrastructure needed.
**Date:** 2026-05-15

---

### D-017 — New message while pending action is waiting: overwrite

**Decision:** If a new non-confirmation message arrives while a pending action is waiting for "כן"/"לא", the pending action is silently discarded and the new message is processed normally.
**Rationale:** The alternative (queuing) is complex and likely to confuse users. The alternative (blocking new messages) is worse UX. Overwriting is the most natural behavior: if the user changed their mind and sent something else, the old action is implicitly abandoned. The 5-minute TTL handles the case where the user walks away entirely.
**Date:** 2026-05-15

---

### D-018 — Integration timeouts: 10 seconds per external call

**Decision:** All external API calls (Notion, Gmail, Calendar, Drive, WhatsApp send) have a 10-second `httpx` timeout. On timeout: return Hebrew error ("השירות לא זמין, נסה שוב בעוד כמה דקות"), log to audit.
**Rationale:** Without timeouts, a slow external API holds the background task indefinitely and blocks that phone's next message (since pending action store is per-phone). 10 seconds is generous for all these APIs under normal conditions.
**No retries in v1** — a timeout surfaces to the user as a retriable error. Automatic retries risk duplicate writes and are deferred to v2.
**Date:** 2026-05-15

---

### D-011 — SentinelOne: managed risk protocol, not tool avoidance

**Decision:** Tools that may trigger SentinelOne (ngrok, uvicorn, outbound API calls) are used normally but classified as 🔴 high risk, requiring the full commit-before-execute protocol. Railway serves as a fallback if a specific tool does trigger quarantine.
**Rationale:** SentinelOne EDR previously quarantined all project files when ngrok + uvicorn + outbound calls ran together. The right response is not to avoid the best tools for the job, but to manage the risk: always have work committed and pushed before executing risky steps, so a quarantine event only costs minutes of recovery, not hours of lost work.
**Alternatives considered:** Banning ngrok entirely (rejected — ngrok is the right tool for local webhook testing; Railway-only testing is slower and less flexible).
**Date:** 2026-05-15

---

### D-012 — Commit-before-execute protocol for 🔴 steps

**Decision:** Before any 🔴 step, Claude Code must warn Yuval, explicitly ask him to commit and push, and wait for confirmation before proceeding.
**Rationale:** If SentinelOne quarantines files mid-task, having the latest state on GitHub means recovery is a single `git clone`. The protocol costs seconds and eliminates the risk of losing hours of work.
**Date:** 2026-05-15

---

### D-013 — claude.ai web as fallback for 🔴 steps

**Decision:** For any 🔴 step, Claude Code offers running it via Claude Code on claude.ai (web) as an alternative to local execution. Yuval decides.
**Rationale:** The Claude Desktop app on the corporate machine is subject to SentinelOne file quarantine. The web interface does not interact with the local filesystem the same way. For the highest-risk steps (OAuth flows, full integration testing), web is meaningfully safer.
**Date:** 2026-05-15

---

### D-019 — Live echo test via Railway before Task 3, not at Task 11

**Decision:** Do not defer the live WhatsApp webhook test to Task 11 (production deploy). Instead, run it as Task 2b via Railway immediately after the echo code lands, using placeholder env vars for everything except the four WhatsApp vars.
**Rationale:** The echo is the foundation all later tasks build on. If signature verification, payload parsing, or the Meta→Railway→WhatsApp network path is broken, it's far cheaper to discover that before Claude integration, Notion, Gmail, etc. are layered on top. Shift the validation left.
**Alternative rejected:** Testing at Task 11 — too late; a broken webhook would require re-testing all tasks.
**Note:** ngrok is still avoided. Railway is 🟡 (git push only for Claude's part); Yuval sets up the Railway project and Meta webhook in the dashboard (~5 min).
**Date:** 2026-05-16

---

### D-021 — Gmail scope widened beyond send (supersedes D-006 for Gmail)

**Decision:** Gmail OAuth grants `gmail.send` + `gmail.readonly` + `gmail.modify` (plus People API scopes for contacts). Calendar and Drive scopes are unchanged.
**Rationale:** Task 6c sharpened the Gmail product surface: read the Primary inbox, look up contacts before asking the user for an email address, and trash messages. Each of these is a real product capability worth a scope, and the failure mode of read/trash is bounded — read returns metadata + snippets (no message bodies parsed by the bot), trash is reversible from the Gmail UI for 30 days. Permanent delete (`mail.google.com`) was explicitly NOT requested.
**Alternative rejected:** Keep send-only and ask the user for every recipient address + every "what's in my inbox" question. Bot becomes an outbound-only sender, which makes the contacts-lookup and read flows impossible.
**Date:** 2026-05-18

---

### D-022 — Gmail read defaults to Primary tab with empty-result fallback

**Decision:** `gmail.search_inbox` injects `in:inbox category:primary` into every query that doesn't already specify `in:`/`label:`/`category:`. If that returns zero hits AND the filter was injected (not user-supplied), retry once without `category:primary`.
**Rationale:** The tool is named "search inbox" and the user's stated intent is the Primary tab — not Promotions, Social, Updates, Spam, or Sent. Gmail's `messages.list` with empty `q` returns ALL mail, which surfaced Sent items and promo emails in live verification. Workspace / business accounts (deals@cgm-ventures.com) don't have category tabs enabled, so `category:primary` would always return zero hits there — the single-retry fallback handles that without a probe call or account-type detection.
**Alternative rejected:** Detect account type up-front (Workspace vs personal Gmail) and choose the filter accordingly. Rejected — requires an extra API call per search and Google doesn't expose a clean "is this a Workspace account?" endpoint.
**Date:** 2026-05-18

---

### D-023 — Code-level scrubbers as backstops for unreliable prompt rules

**Decision:** When a prompt rule is critical to product UX but the model violates it more than ~5% of the time, add a code-level scrubber on the final reply as a hard backstop. Keep the prompt rule as the soft intent. Currently scrubbed: em-dash (U+2014) and en-dash (U+2013) → plain `-` (`_scrub_llm_punctuation` in `claude_agent/agent.py`).
**Rationale:** Two prior instances showed prompt-only rules don't hold reliably enough for product-critical behavior — the Hebrew-language leak (fixed with per-turn language directive in `0f95196`) and the per-turn write-tool dedup (fixed with `invoked_once` set in `ef30bdd`). Em-dash leak is the same class: model emits banned punctuation ~10% of the time despite explicit prompt rules. Code-level scrubber is deterministic; prompt rule stays for cases where the scrubber can't reach (e.g. body of email Mano composes — the scrubber runs on the reply only, not on intermediate tool inputs).
**Alternative rejected:** Strengthen the prompt rule further. Tried three times for the Hebrew leak, three times for the em-dash leak. Diminishing returns and the prompt is already dense.
**Date:** 2026-05-18

---

### D-020 — Sender phone normalization at the parse boundary

**Decision:** `whatsapp/webhook.py::parse_incoming` prepends `+` to the sender phone if missing. All downstream code (users registry, audit log, router) sees a single canonical form (`+<country><number>`).
**Rationale:** Meta Cloud API delivers the `from` field as bare digits (`972542159121`), but `users.py` stores numbers with the `+` prefix. The exact-match allowlist was silently denying every real inbound message — discovered in Task 2b live testing. Tests had been passing because constructed payloads used the `+` form; tests now also cover the bare-digit case.
**Alternative rejected:** Normalize inside `is_authorized` / `get_user` / `has_permission`. Rejected because it puts the same normalization in three places and the registry-side functions are also called from places that already pass canonical form (router, audit). Single normalization at the entry boundary is simpler.
**Date:** 2026-05-17
