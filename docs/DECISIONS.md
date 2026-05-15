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
**Date:** 2026-05-10

---

### D-003 — WhatsApp: Meta Cloud API directly

**Decision:** Meta Cloud API, not Twilio.
**Rationale:** Free for user-initiated messages. Twilio adds per-message cost. Direct = less abstraction.
**Date:** 2026-05-10

---

### D-004 — No conversation memory in v1

**Decision:** Claude receives only the current message. No history persisted.
**Rationale:** Simplest implementation. Avoids storing message content. Most interactions are single-turn commands. History can be added in v2 with proper storage design.
**Date:** 2026-05-10

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
**Date:** 2026-05-10

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
