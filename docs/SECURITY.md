# SECURITY.md — Mano Bot Security Model

This document describes the security design of Mano Bot.
Every developer (including Claude Code) must read this before touching auth, webhook, or integration code.

---

## Threat Model

Mano Bot has significant access: 3 Gmail accounts, Google Calendar, Google Drive, and Notion.
It runs 24/7 and is reachable via a public HTTPS endpoint.

### Assets to Protect
- Gmail (3 accounts — personal, CGM personal, CGM business)
- Google Calendar
- Google Drive (3 accounts)
- Notion workspace
- WhatsApp conversation content
- API credentials (Anthropic, Meta, Google, Notion)

### Threat Actors
- External attacker who discovers the webhook URL
- Someone with a non-allowlisted phone number sending commands
- Compromised Railway environment
- Credentials leaked via logs or GitHub
- Prompt injection via crafted WhatsApp messages

---

## Controls

### 1. Message Deduplication
**Threat:** Meta delivers the same webhook twice (at-least-once delivery), causing duplicate writes or duplicate emails.
**Control:** In-memory set of the last 1000 `message_id` values. Any webhook with a seen ID is dropped immediately after signature verification — before authorization, rate limiting, or any processing.

### 2. Webhook Signature Verification
**Threat:** Attacker replays or forges webhook requests to execute commands.
**Control:** Every incoming POST /webhook request is verified against Meta's HMAC-SHA256 signature.
- Header: `X-Hub-Signature-256: sha256=<hmac>`
- Secret: `WHATSAPP_APP_SECRET` (env var, never logged)
- Comparison: `hmac.compare_digest` — constant-time, prevents timing attacks
- Failure: return 403 immediately, no processing

### 3. Phone Number Allowlist
**Threat:** Unknown phone number sends commands to the bot.
**Control:** Every sender is checked against the `USERS` dict in `users.py`.
- If not in allowlist: audit log + return 200 silently (never reveal the bot exists)
- Only Yuval and Eden are in the allowlist

### 4. Permission System
**Threat:** Eden (or future users) accessing integrations they're not allowed.
**Control:** Every integration call checks `has_permission(phone, integration)` before executing.
- Eden currently has no integration permissions
- Denial returns a Hebrew message — never an error or stack trace

### 5. Rate Limiting
**Threat:** Message flood, runaway loops, API cost explosion.
**Control:** Max 20 messages per phone per 10-minute window.
- In-memory (sufficient for 2 users)
- On limit: one Hebrew warning, then silence
- Audit logged

### 6. Pending Action TTL
**Threat:** Stale confirmation sent accidentally long after the action was proposed.
**Control:** Pending actions expire after 5 minutes.
- On expiry: action discarded, user informed in Hebrew
- Only exact confirmation/cancellation words are accepted
- If a new non-confirmation message arrives while an action is pending, the pending action is discarded and the new message is processed normally (see D-017)

### 7. Scoped Google OAuth
**Threat:** Compromised token grants full Google account access.
**Control:** Minimum required OAuth scopes only:
- Gmail: `gmail.send` only — cannot read, delete, or access other data
- Calendar: `calendar.events` only
- Drive: `drive.readonly` only

### 8. Credential Hygiene
**Threat:** Credentials leak via logs, GitHub, or error messages.
**Controls:**
- `.env` is gitignored — never committed
- Google OAuth tokens are stored as Railway env vars (`GOOGLE_TOKEN_PERSONAL`, `GOOGLE_TOKEN_CGM`, `GOOGLE_TOKEN_DEALS`) — not as files on disk, which would be lost on redeploy (see D-015)
- `GOOGLE_CREDENTIALS_JSON` is the static OAuth client credentials (client_id/client_secret from Google Cloud Console) — separate from the per-user tokens above
- `SECRETS.md` is gitignored (used as a local scratchpad for credentials during incident rotation — never commit it)
- `credentials*.json` is gitignored
- Logging never outputs token values, access tokens, or API keys
- Phone numbers in audit log are masked: last 4 digits only (e.g. `+XXX...1234`)
- Error messages to users are generic Hebrew strings — never raw Python exceptions

### 9. Kill Switch
**Threat:** Bot behaves unexpectedly and needs immediate shutdown.
**Control:** `BOT_ENABLED` env var in Railway.
- If `BOT_ENABLED=false`: all messages ignored, 200 returned, health check still works
- Can be toggled instantly in Railway dashboard — no redeployment needed

### 10. Admin Audit Endpoint
**Control:** `GET /audit` protected by `ADMIN_TOKEN` header.
- Returns last 50 audit entries
- No credential content ever appears in the audit log

### 11. Dependency Pinning
**Threat:** Malicious or breaking dependency update introduced silently.
**Control:** `requirements.txt` pins exact versions for all packages.
- Update intentionally and explicitly — never `pip install --upgrade` blindly

---

## Known Gaps (v1)

- **Conversation history in memory only** — 5-message rolling history resets on process restart. Acceptable for v1; persistent history in v2 must not store content in plaintext.
- **Token refresh not persisted to env var** — `google-auth` refreshes the access token automatically in memory using the refresh token. On process restart, it reloads from the env var and refreshes again — this works under normal operation. Failure mode: if Google revokes the refresh token (user manually revokes access in Google Account Security, or token is inactive for 6 months), the bot breaks silently and requires a manual re-run of the OAuth flow. Mitigation: monitor for `401` errors in logs. Fix in v2: write refreshed token back to Railway env var via Railway API after each refresh.
- **No retry logic** — timed-out integration calls surface as a Hebrew error to the user. The user must resend. Automatic retries deferred to v2.
- **Permissions require code deploy to change** — adding or removing permissions for Eden requires editing `users.py` and pushing. Acceptable for 2 users; config-driven permissions in v2.
- **Voice messages** — not yet implemented; when added, audio must not be stored after transcription.
- **Railway compromise** — if Railway is breached, all env vars (including OAuth tokens) are exposed. Mitigation: rotate credentials regularly.
- **SIM swap attack** — if Yuval's phone number is hijacked, attacker gains full access. No current mitigation. Consider 2FA challenge in v2.

---

## Incident Response

If credentials are suspected compromised:
1. Set `BOT_ENABLED=false` in Railway immediately
2. Revoke Meta access token in Meta Business Manager
3. Revoke Google OAuth tokens in Google Account Security
4. Rotate `ANTHROPIC_API_KEY` in Anthropic console
5. Rotate `NOTION_TOKEN` in Notion integrations
6. Review `audit.log` for unauthorized actions
7. Re-generate all credentials before re-enabling

---

## Pre-Deploy Security Checklist

```
[ ] .env not committed (git status clean)
[ ] No credentials in any log output
[ ] No credentials hardcoded in any .py file
[ ] Webhook signature verification is active
[ ] Phone allowlist is current
[ ] All Google OAuth scopes are minimal
[ ] BOT_ENABLED is set in Railway
[ ] WHATSAPP_APP_SECRET is set in Railway
[ ] audit.log is gitignored
[ ] No sensitive data in CHANGELOG or DECISIONS
```
