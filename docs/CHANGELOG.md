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

---

<!-- Claude Code appends below this line after each completed task -->
