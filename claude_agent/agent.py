"""Claude interaction loop with tool use."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from anthropic import AsyncClient

import config
from claude_agent.system_prompt import SYSTEM_PROMPT
from claude_agent.tools import TOOLS
from integrations import contacts, drive, gcalendar, gmail, notion, web
from security.audit import log_action
from users import has_permission

logger = logging.getLogger(__name__)

CONVERSATION_HISTORY: dict[str, list[dict]] = {}
MAX_HISTORY_TURNS = 5

HEBREW_ERROR = "משהו השתבש, נסה שוב"
HEBREW_PERMISSION_DENIED = "אין לך הרשאה לפעולה הזו"

PENDING_ACTIONS: dict[str, dict] = {}
TTL_MINUTES = 5
CONFIRM_WORDS = {"כן", "yes", "אשר", "ok", "confirm", "כן."}
CANCEL_WORDS = {"לא", "no", "ביטול", "cancel", "בטל", "לא."}

MAX_TOOL_ITERATIONS = 5

# Map tool name → required permission key in users.USERS[*]["permissions"].
TOOL_PERMISSIONS: dict[str, str] = {
    "notion_add_task": "notion",
    "notion_archive_task": "notion",
    "notion_list_tasks": "notion",
    "notion_add_idea": "idea_lab",
    "notion_list_ideas": "idea_lab",
    "notion_archive_idea": "idea_lab",
    "notion_comment_idea": "idea_lab",
    "notion_get_idea": "idea_lab",
    "notion_save_knowledge": "knowledge",
    "notion_list_knowledge": "knowledge",
    "notion_get_knowledge": "knowledge",
    "fetch_url": "web",
    "gmail_send_email": "gmail",
    "gmail_search_inbox": "gmail",
    "gmail_trash_email": "gmail",
    "contacts_lookup": "gmail",
    "calendar_create_event": "calendar",
    "calendar_list_events": "calendar",
    "calendar_cancel_event": "calendar",
    "drive_search_files": "drive",
}

_HEBREW_RE = re.compile(r"[֐-׿]")

# Em-dash (U+2014) and en-dash (U+2013) are explicitly banned by the system
# prompt's "no LLM-style punctuation" rule. The model still leaks them ~10%
# of the time, so this is the hard backstop applied to every outgoing reply.
_DASH_SUBSTITUTIONS = (("—", "-"), ("–", "-"))


def _scrub_llm_punctuation(text: str) -> str:
    for src, dst in _DASH_SUBSTITUTIONS:
        text = text.replace(src, dst)
    return text


def _detect_language(text: str) -> str:
    """Return ``"he"`` if the message contains Hebrew chars, else ``"en"``.

    Mirrors the spec's language-priority rule at the code level so it can't be
    overridden by stale conversation history or prompt-template leakage.
    """
    return "he" if _HEBREW_RE.search(text or "") else "en"


def _language_directive(lang: str) -> str:
    if lang == "he":
        return (
            "[Language directive for THIS turn: reply in Hebrew (informal, "
            "אתה). This applies to confirmation prompts, follow-up questions, "
            "and every word of your reply.]"
        )
    return (
        "[Language directive for THIS turn: reply in English. This applies to "
        "confirmation prompts, follow-up questions, and every word of your "
        "reply, regardless of any prior Hebrew turns in this conversation.]"
    )


_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def _date_directive(now: datetime | None = None) -> str:
    """Per-turn directive carrying today's date + weekday in Israel local time.

    The model's training-knowledge cutoff is months in the past; without an
    explicit "today is X" anchor, relative phrases like "tomorrow" or "next
    Sunday" get resolved against an imagined date and land on the wrong
    calendar day. Injecting the real date at message-time is the code-level
    backstop.
    """
    if now is None:
        now = datetime.now(_ISRAEL_TZ)
    weekday = now.strftime("%A")
    date_str = now.strftime("%Y-%m-%d")
    return (
        f"[Today is {weekday}, {date_str} in Israel local time (Asia/Jerusalem). "
        "Use this when resolving relative dates like 'tomorrow', 'next Sunday', "
        "'this week'. Do NOT use any date from your training data.]"
    )


async def _dispatch_tool(name: str, args: dict, user_phone: str | None = None) -> str:
    """Run a tool and return a string result for the tool_result block.

    ``user_phone`` is plumbed through to the Google integrations so per-user
    account resolution can pick the right token (Eden's ``cgm`` vs Yuval's).
    """
    if name == "notion_add_task":
        return await notion.add_task(
            title=args["title"],
            bucket=args["bucket"],
            due_date=args.get("due_date"),
        )
    if name == "notion_list_tasks":
        text = await notion.list_tasks(filter_bucket=args.get("filter_bucket"))
        return text or "(no tasks)"
    if name == "notion_archive_task":
        status, matches = await notion.archive_task(title=args["title"])
        if status == "ok":
            return f"ok: archived '{matches[0]}'"
        if status == "not_found":
            return "not_found"
        if status == "ambiguous":
            return "ambiguous: " + " | ".join(matches)
        return "error"
    if name == "notion_add_idea":
        return await notion.add_idea(
            title=args["title"],
            description=args.get("description"),
            bucket=args.get("bucket"),
            content=args.get("content"),
            source_url=args.get("source_url"),
        )
    if name == "notion_list_ideas":
        text = await notion.list_ideas(filter_bucket=args.get("filter_bucket"))
        return text or "(no ideas)"
    if name == "notion_get_idea":
        status, content = await notion.get_idea(title=args["title"])
        if status == "ok":
            return content
        if status == "not_found":
            return "not_found"
        if status == "ambiguous":
            return "ambiguous: " + content
        return "error"
    if name == "notion_save_knowledge":
        return await notion.add_knowledge(
            title=args["title"],
            topics=args.get("topics"),
            content=args.get("content"),
            source_url=args.get("source_url"),
        )
    if name == "notion_list_knowledge":
        text = await notion.list_knowledge(topic=args.get("topic"))
        return text or "(no items)"
    if name == "notion_get_knowledge":
        status, content = await notion.get_knowledge(title=args["title"])
        if status == "ok":
            return content
        if status == "not_found":
            return "not_found"
        if status == "ambiguous":
            return "ambiguous: " + content
        if status == "not_configured":
            return "not_configured"
        return "error"
    if name == "fetch_url":
        text = await web.fetch_url(url=args["url"])
        return text or "(could not read this link)"
    if name == "notion_archive_idea":
        status, matches = await notion.archive_idea(title=args["title"])
        if status == "ok":
            return f"ok: archived '{matches[0]}'"
        if status == "not_found":
            return "not_found"
        if status == "ambiguous":
            return "ambiguous: " + " | ".join(matches)
        return "error"
    if name == "notion_comment_idea":
        status, matches = await notion.add_idea_comment(
            idea_title=args["idea_title"], comment=args["comment"]
        )
        if status == "ok":
            return f"ok: commented on '{matches[0]}'"
        if status == "not_found":
            return "not_found"
        if status == "ambiguous":
            return "ambiguous: " + " | ".join(matches)
        return "error"
    if name == "gmail_send_email":
        ok = await gmail.send_email(
            to=args["to"],
            subject=args["subject"],
            body=args["body"],
            account_key=args["account_key"],
            user_phone=user_phone,
        )
        return "ok" if ok else "error"
    if name == "gmail_search_inbox":
        text = await gmail.search_inbox(
            query=args.get("query", ""),
            account_key=args["account_key"],
            max_results=int(args.get("max_results", 10)),
            user_phone=user_phone,
        )
        return text or "(no messages)"
    if name == "gmail_trash_email":
        status, subjects = await gmail.trash_by_query(
            query=args["query"],
            account_key=args["account_key"],
            user_phone=user_phone,
        )
        if status == "ok":
            return f"ok: trashed '{subjects[0]}'"
        if status == "not_found":
            return "not_found"
        if status == "ambiguous":
            return "ambiguous: " + " | ".join(subjects)
        return "error"
    if name == "contacts_lookup":
        results = await contacts.lookup_contact(
            query=args["query"],
            account_key=args["account_key"],
            user_phone=user_phone,
        )
        if not results:
            return "no_match"
        lines = [f"{r['name'] or '(no name)'} <{r['email']}>" for r in results[:10]]
        return "matches:\n" + "\n".join(lines)
    if name == "calendar_create_event":
        start = args["start_datetime"]
        end = args.get("end_datetime") or ""
        if not end:
            try:
                start_dt = datetime.fromisoformat(start)
                end = (start_dt + timedelta(hours=1)).isoformat()
            except ValueError:
                return (
                    "error: invalid start_datetime. The event was NOT created. "
                    "Tell the user the calendar write failed and ask them to "
                    "rephrase the time."
                )
        alert_minutes = args.get("alert_minutes")
        if alert_minutes is None:
            alert_minutes = 10
        result = await gcalendar.create_event(
            title=args["title"],
            start_datetime=start,
            end_datetime=end,
            description=args.get("description"),
            alert_minutes=int(alert_minutes),
        )
        if result.get("ok"):
            return "ok"
        reason = result.get("reason") or "unknown"
        return (
            f"error: calendar write FAILED (reason={reason}). The event was "
            "NOT created on the calendar. Tell the user the action failed - "
            "do NOT claim success."
        )
    if name == "calendar_list_events":
        text = await gcalendar.list_upcoming_events(days=int(args.get("days", 7)))
        return text or "(no events)"
    if name == "calendar_cancel_event":
        status, summaries = await gcalendar.cancel_event_by_query(
            query=args["query"],
            days_window=int(args.get("days_window", 60)),
        )
        if status == "ok":
            return f"ok: cancelled '{summaries[0]}'"
        if status == "not_found":
            return "not_found"
        if status == "ambiguous":
            return "ambiguous: " + " | ".join(summaries)
        return "error"
    if name == "drive_search_files":
        text = await drive.search_files(
            query=args["query"],
            account_key=args["account_key"],
            user_phone=user_phone,
        )
        return text or "(no files)"
    return f"unknown tool: {name}"


def _extract_text(content_blocks: list) -> str:
    parts = []
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _serialize_assistant_content(content_blocks: list) -> list[dict]:
    """Convert SDK content blocks back into dict form for the next API call."""
    out: list[dict] = []
    for block in content_blocks:
        btype = getattr(block, "type", None)
        if btype == "text":
            out.append({"type": "text", "text": block.text})
        elif btype == "tool_use":
            out.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return out


async def run(user_phone: str, message: str) -> str:
    """Run a Claude turn (with optional tool use) for ``user_phone``.

    Loads history, calls claude-sonnet-4-6 with SYSTEM_PROMPT (cached) and the
    full tool list. If Claude requests tools, permissions are checked against
    ``users.has_permission`` and each tool is dispatched; the loop continues
    until Claude returns a text-only reply or MAX_TOOL_ITERATIONS is hit.

    History stores only user/assistant text turns — intermediate tool_use /
    tool_result blocks are not persisted across turns.
    """
    if user_phone not in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[user_phone] = []

    history = CONVERSATION_HISTORY[user_phone]
    messages: list[dict] = list(history)
    # Inject a per-turn language directive so tool-flow replies don't drift
    # back to Hebrew when the latest user message is English (or vice versa).
    # The directive is added only to the message sent to Claude — history
    # persists the original user text.
    lang_directive = _language_directive(_detect_language(message))
    date_directive = _date_directive()
    messages.append(
        {"role": "user", "content": f"{date_directive}\n{lang_directive}\n\n{message}"}
    )

    client = AsyncClient(api_key=config.ANTHROPIC_API_KEY)
    final_text = ""

    # Per-turn guard: write/mutate tools may only fire once per (tool, title).
    # The prompt asks Claude not to re-add an idea after the user declines more
    # comments, but the rule has been unreliable in practice — this is the
    # hard backstop so duplicate adds become structurally impossible.
    SINGLE_CALL_TOOLS = {
        "notion_add_idea",
        "notion_save_knowledge",
        "notion_add_task",
        "notion_archive_idea",
        "notion_archive_task",
        "calendar_create_event",
        "calendar_cancel_event",
        "gmail_send_email",
        "gmail_trash_email",
    }
    invoked_once: set[tuple[str, str]] = set()

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
                tools=TOOLS,
            )

            if response.stop_reason != "tool_use":
                final_text = _extract_text(response.content)
                break

            # Append assistant turn (with tool_use blocks) to the running messages.
            messages.append(
                {
                    "role": "assistant",
                    "content": _serialize_assistant_content(response.content),
                }
            )

            # Build tool_result blocks for every tool_use block in this response.
            tool_results: list[dict] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_name = block.name
                required = TOOL_PERMISSIONS.get(tool_name)
                if required and not has_permission(user_phone, required):
                    log_action(
                        user_phone, tool_name, f"perm={required}", "denied"
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": HEBREW_PERMISSION_DENIED,
                            "is_error": True,
                        }
                    )
                    continue
                # Single-call guard for write tools — block the second call
                # on the same primary key within one turn.
                tool_args = dict(block.input)
                primary_key = (
                    tool_args.get("title")
                    or tool_args.get("idea_title")
                    or tool_args.get("subject")
                    or tool_args.get("query")
                    or ""
                ).strip().lower()
                guard_key = (tool_name, primary_key)
                if tool_name in SINGLE_CALL_TOOLS and guard_key in invoked_once:
                    log_action(
                        user_phone, tool_name, f"key={primary_key}", "blocked_duplicate"
                    )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                "BLOCKED: this tool already ran successfully in "
                                "this turn for the same item. Do NOT mention "
                                "this block or any 'already added' message to "
                                "the user. The previous flow is complete — just "
                                "acknowledge the user's last message briefly "
                                "and end the turn."
                            ),
                        }
                    )
                    continue

                log_action(user_phone, tool_name, "", "invoked")
                try:
                    result = await _dispatch_tool(tool_name, tool_args, user_phone)
                except Exception as exc:
                    logger.error(
                        "Tool %s raised %s", tool_name, exc.__class__.__name__
                    )
                    log_action(user_phone, tool_name, "", "exception")
                    result = "error"

                if (
                    tool_name in SINGLE_CALL_TOOLS
                    and isinstance(result, str)
                    and result.startswith("ok")
                ):
                    invoked_once.add(guard_key)

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

            messages.append({"role": "user", "content": tool_results})
        else:
            # Loop exhausted without a terminal response.
            logger.error("Tool-use loop exceeded MAX_TOOL_ITERATIONS")
            final_text = HEBREW_ERROR
    except Exception as exc:
        logger.error(
            "Claude API error for phone ****%s: %s",
            user_phone[-4:] if len(user_phone) > 4 else "****",
            exc.__class__.__name__,
        )
        return HEBREW_ERROR

    if not final_text:
        final_text = HEBREW_ERROR

    final_text = _scrub_llm_punctuation(final_text)

    # Persist only the user message and the final assistant text to history.
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": final_text})
    while len(history) > MAX_HISTORY_TURNS * 2:
        history[:2] = []

    return final_text
