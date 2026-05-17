# Known Issues

Issues that have been observed in production but are not yet fixed. Each
entry should record what was seen, what was tried, and any working hypothesis
about root cause, so the next session can pick up without re-investigating.

---

## ISSUE-001 — Duplicate "already added" reply after Idea Lab comment flow ends

**Status:** Open
**First seen:** 2026-05-17
**Severity:** Low (cosmetic — no duplicate row is created, but the user sees a
confusing tail message that makes the bot look broken)

### Symptom

After the idea-creation + comment flow completes cleanly, Mano sends an extra
unsolicited message implying the idea was already added.

Reproducer (live, 23:01):
```
user: I have an idea: read more philosophy, put it under Self Improvement
bot:  Got it! I'll add this to the Idea Lab: Title / Bucket. Confirm?
user: yes
bot:  Added! Do you have any details or comments you want to add to this idea?
user: no
bot:  Looks like "Read more philosophy" was already added to the Idea Lab in
      the last few minutes — no duplicate was created.   <-- BUG
```

The Notion DB itself is correct (single row, correct bucket). The bug is
purely in the bot's outgoing message.

### What's been tried

1. **Prompt rule** (commit `0defb95`): explicit "after notion_comment_idea, if
   the user says no to more comments, acknowledge and stop. Never call
   notion_add_idea or notion_comment_idea again on the same idea in the same
   turn." → Did not hold.
2. **Code-level single-call guard** (commit `ef30bdd`): in
   `claude_agent/agent.py`, after a successful write-tool call, any further
   call to the same (tool, primary_key) within the same `run()` is replaced
   with a BLOCKED tool_result whose content tells Claude not to mention it.
   → User reports the issue still occurs after this fix.

### Hypotheses to investigate next

- The guard fires, but Claude is generating the "already added" text from the
  conversation context (prior turn's `notion_add_idea` returned `ok` and
  Claude is *narrating* that fact post-hoc), not from the BLOCKED result.
- The duplicate add is happening in a *different* `run()` call — i.e. the
  WhatsApp message "no" arrives as its own turn, the per-turn guard set
  (`invoked_once`) is fresh, and Claude legitimately calls `notion_add_idea`
  again because the prompt rule didn't hold across turns. **If true, the
  guard needs to be cross-turn (e.g. keyed on conversation history + a
  short TTL) or the model needs to be told the prior turn already completed
  the add.**
- The deduplication query in `notion.add_idea` is returning `duplicate` and
  the dispatch surfaces that string back to Claude, who then narrates it
  faithfully. Even with the BLOCKED guard, on a second `run()` the dedupe
  result is what's surfaced because the per-turn guard doesn't fire.

### Suggested next step when picking this up

1. Pull Railway logs for an instance of this happening and check which path
   was taken: `BLOCKED guard fired` vs `notion_add_idea returned duplicate`.
2. If it's the second path, change the dispatch so a `duplicate` return on a
   write tool is reframed as a silent no-op result, e.g.:
   `"noop: this item already exists. Do not mention this; just acknowledge
   the user's last message and end the turn."`
3. Consider persisting `invoked_once`-like state across turns for the same
   `user_phone` with a short TTL (e.g. 5 minutes, mirroring DEDUPE_WINDOW).
