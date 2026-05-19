"""Anthropic tool definitions.

Tool dispatch (mapping tool name → coroutine) lives in ``claude_agent.agent``.
Permission checks (``has_permission(phone, integration)``) are applied there
before any tool function is called.
"""

from __future__ import annotations

BUCKETS = [
    "Business",
    "Career",
    "Self Improvement",
    "Personal",
    "Productive Ideas",
    "Job",
    "Health",
    "Fitness",
    "Family & Friends",
    "Journal",
    "Relationship",
    "Admin",
    "Marketing",
    "Economics",
    "Study",
]

TOOLS: list[dict] = [
    {
        "name": "notion_add_task",
        "description": "Add a task to Notion My Task List. Always confirm with the user before calling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "bucket": {"type": "string", "enum": BUCKETS},
                "due_date": {
                    "type": "string",
                    "description": "ISO date string (YYYY-MM-DD), optional",
                },
            },
            "required": ["title", "bucket"],
        },
    },
    {
        "name": "notion_archive_task",
        "description": (
            "Archive a task from Notion My Task List by fuzzy title match (moves "
            "to Notion trash, recoverable from the UI). Always confirm with the "
            "user before calling. If the tool returns 'ambiguous', ask the user "
            "which one and call again with a more specific title."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Substring of the task title (case-insensitive).",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "notion_list_tasks",
        "description": "List tasks from Notion My Task List. Optional bucket filter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_bucket": {"type": "string"},
            },
        },
    },
    {
        "name": "notion_add_idea",
        "description": (
            "Add an idea to the Idea Lab. Always confirm with the user before "
            "calling. After a successful add, ask the user if they have any "
            "details or comments about the idea; if yes, call notion_comment_idea."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "bucket": {"type": "string", "enum": BUCKETS},
            },
            "required": ["title"],
        },
    },
    {
        "name": "notion_list_ideas",
        "description": "List ideas from Notion Idea Lab. Optional bucket filter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_bucket": {"type": "string"},
            },
        },
    },
    {
        "name": "notion_archive_idea",
        "description": (
            "Archive an idea from the Idea Lab by fuzzy title match (moves to "
            "Notion trash, recoverable from the UI). Always confirm with the "
            "user before calling. If the tool returns 'ambiguous', ask the user "
            "which one and call again with a more specific title."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Substring of the idea title (case-insensitive).",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "notion_comment_idea",
        "description": (
            "Add a Notion page comment to an idea in the Idea Lab, matched by "
            "fuzzy title (case-insensitive substring). Use this when the user "
            "supplies details/comments about an idea after it was created. "
            "If the tool returns 'ambiguous', ask the user which one and call "
            "again with a more specific title."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "idea_title": {
                    "type": "string",
                    "description": "Substring of the idea title (case-insensitive).",
                },
                "comment": {"type": "string"},
            },
            "required": ["idea_title", "comment"],
        },
    },
    {
        "name": "gmail_send_email",
        "description": (
            "Send an email from one of Yuval's Gmail accounts. Always confirm "
            "recipient, subject, body, and account with the user before calling. "
            "Write the body in casual everyday language — no LLM-style punctuation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "account_key": {
                    "type": "string",
                    "enum": ["personal", "cgm", "deals"],
                    "description": (
                        "personal=yuvalmanor@gmail.com, cgm=yuval.cgm@gmail.com, "
                        "deals=deals@cgm-ventures.com"
                    ),
                },
            },
            "required": ["to", "subject", "body", "account_key"],
        },
    },
    {
        "name": "gmail_search_inbox",
        "description": (
            "Search a Gmail inbox and return matching messages (sender, "
            "subject, date, snippet). Use Gmail query syntax: 'from:alice@x.com', "
            "'subject:invoice', 'newer_than:7d', or plain keywords. By default "
            "results are scoped to the Primary tab of the inbox; pass "
            "'category:promotions' or 'in:sent' to override."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query. Empty string returns the most recent Primary inbox messages.",
                },
                "account_key": {
                    "type": "string",
                    "enum": ["personal", "cgm", "deals"],
                    "description": (
                        "personal=yuvalmanor@gmail.com, cgm=yuval.cgm@gmail.com, "
                        "deals=deals@cgm-ventures.com"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max messages to return (default 10, capped at 25).",
                },
            },
            "required": ["query", "account_key"],
        },
    },
    {
        "name": "gmail_trash_email",
        "description": (
            "Move a single email to Trash (recoverable from Gmail UI for 30 "
            "days — NOT permanently deleted). Identifies the message by a "
            "Gmail query (use 'from:', 'subject:', or distinguishing keywords). "
            "ALWAYS confirm with the user before calling. If the tool returns "
            "'ambiguous', present the candidate subjects and ask which one — "
            "do NOT pick on the user's behalf."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail query that uniquely identifies one message (e.g. 'from:angi@email.angi.com subject:\"how can we help\"').",
                },
                "account_key": {
                    "type": "string",
                    "enum": ["personal", "cgm", "deals"],
                    "description": "Which account's inbox to trash from.",
                },
            },
            "required": ["query", "account_key"],
        },
    },
    {
        "name": "contacts_lookup",
        "description": (
            "Look up a person in the account's Google contacts (saved contacts + "
            "people the account has emailed in the past). Returns name/email "
            "matches. Use BEFORE asking the user for an email address when they "
            "name a recipient (e.g. 'send from cgm to Alice'). Currently only "
            "the 'cgm' account is searchable. If results are empty, ask the user "
            "for the address. If multiple, present them and ask which."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name or email substring to search for.",
                },
                "account_key": {
                    "type": "string",
                    "enum": ["cgm"],
                    "description": "cgm=yuval.cgm@gmail.com contacts.",
                },
            },
            "required": ["query", "account_key"],
        },
    },
    {
        "name": "calendar_create_event",
        "description": (
            "Create an event on Yuval's Google Calendar. Always confirm title, "
            "start, end, alert, and description with the user before calling. "
            "Times must be RFC3339 strings (e.g. 2026-05-20T14:00:00+03:00). "
            "When the user does not specify a duration, OMIT end_datetime - "
            "the server defaults to start + 1 hour. When the user does not "
            "specify an alert, OMIT alert_minutes - the server defaults to a "
            "popup 10 minutes before. Pass alert_minutes=-1 ONLY when the user "
            "explicitly says no alert."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_datetime": {
                    "type": "string",
                    "description": "RFC3339 start, e.g. 2026-05-20T14:00:00+03:00",
                },
                "end_datetime": {
                    "type": "string",
                    "description": (
                        "RFC3339 end, e.g. 2026-05-20T15:00:00+03:00. Optional - "
                        "omit it when the user has not specified a duration; "
                        "the server will default to start + 1 hour."
                    ),
                },
                "description": {"type": "string"},
                "alert_minutes": {
                    "type": "integer",
                    "description": (
                        "Minutes before the event for a popup reminder. Default "
                        "is 10 when omitted. Pass -1 for no reminder. Any "
                        "non-negative int sets the reminder to that many "
                        "minutes before (0 = at event start time)."
                    ),
                },
            },
            "required": ["title", "start_datetime"],
        },
    },
    {
        "name": "calendar_cancel_event",
        "description": (
            "Cancel (delete) a calendar event on Yuval's primary calendar by "
            "free-text query. Searches upcoming events in the next days_window "
            "days (default 60) - matches against title, description, location, "
            "and attendees. ALWAYS confirm with the user before calling: "
            "summarize the candidate event and ask לאשר?/confirm?. If the tool "
            "returns ambiguous, present the list and ask which one. If "
            "not_found, tell the user no matching event was found. Deletion "
            "is permanent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Free-text search (title keywords, attendee name, etc.). "
                        "Be specific enough to match a single event."
                    ),
                },
                "days_window": {
                    "type": "integer",
                    "description": "Look-ahead window in days (default 60).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "drive_search_files",
        "description": (
            "Search Google Drive by filename substring on one of Yuval's accounts. "
            "Read-only — returns matching file names with their view links."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Substring to match in file names."},
                "account_key": {
                    "type": "string",
                    "enum": ["personal", "cgm", "deals"],
                    "description": (
                        "personal=yuvalmanor@gmail.com, cgm=yuval.cgm@gmail.com, "
                        "deals=deals@cgm-ventures.com"
                    ),
                },
            },
            "required": ["query", "account_key"],
        },
    },
    {
        "name": "calendar_list_events",
        "description": "List upcoming events from Yuval's Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Look-ahead window in days (default 7).",
                },
            },
        },
    },
]
