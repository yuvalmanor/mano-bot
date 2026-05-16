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
        "description": "Add an idea to the Idea Lab. Always confirm with the user before calling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title"],
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
]
