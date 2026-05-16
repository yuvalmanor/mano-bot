"""Notion integration. Implemented in Task 5."""

from __future__ import annotations


async def add_task(title: str, bucket: str, due_date: str | None = None) -> bool:
    raise NotImplementedError("integrations.notion.add_task is implemented in Task 5")


async def list_tasks(filter_bucket: str | None = None) -> str:
    raise NotImplementedError("integrations.notion.list_tasks is implemented in Task 5")


async def add_idea(title: str, description: str | None = None) -> bool:
    raise NotImplementedError("integrations.notion.add_idea is implemented in Task 5")
