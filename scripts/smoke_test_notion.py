"""One-off smoke test for the Notion integration.

Runs three checks against the real Notion API using credentials from .env:

1. List buckets from My Life Buckets (verifies token + integration access + bucket DB ID)
2. Create a test task in My Task List (verifies task DB + Bucket relation wiring)
3. Create a test idea in My Ideas (verifies ideas DB)

Run from the repo root:

    python scripts/smoke_test_notion.py

The script never logs the NOTION_TOKEN value. The two created pages are titled
"TEST - delete me" so you can find and remove them after.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make repo root importable when run as `python scripts/smoke_test_notion.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations import notion  # noqa: E402

TEST_TITLE = "TEST - delete me"


def _print(label: str, ok: bool, detail: str = "") -> None:
    mark = "OK  " if ok else "FAIL"
    line = f"[{mark}] {label}"
    if detail:
        line += f"  -  {detail}"
    print(line)


async def main() -> int:
    failures = 0

    # 1. Bucket load -------------------------------------------------------
    await notion._load_buckets()
    names = sorted(notion._BUCKET_NAME_TO_ID.keys())
    if names:
        _print("buckets", True, f"{len(names)} found: {', '.join(names)}")
    else:
        _print(
            "buckets",
            False,
            "no buckets returned - check NOTION_TOKEN, NOTION_BUCKETS_DB_ID, and that Mano Bot is connected to Headquarters",
        )
        failures += 1

    # 2. Add task ----------------------------------------------------------
    test_bucket = "Personal" if "Personal" in names else (names[0] if names else "Personal")
    task_ok = await notion.add_task(TEST_TITLE, test_bucket)
    _print(
        "add_task",
        task_ok,
        f"bucket={test_bucket} (delete the new page from My Task List after verifying)",
    )
    if not task_ok:
        failures += 1

    # 3. Add idea ----------------------------------------------------------
    idea_ok = await notion.add_idea(TEST_TITLE, description="smoke test - delete me")
    _print(
        "add_idea",
        idea_ok,
        "delete the new page from My Ideas after verifying",
    )
    if not idea_ok:
        failures += 1

    print()
    if failures == 0:
        print("All checks passed. Open Notion and verify the two test pages exist, then delete them.")
        return 0
    print(f"{failures} check(s) failed. See audit.log for details.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
