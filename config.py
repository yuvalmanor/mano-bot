"""Environment variable loading and validation.

Loads from .env via python-dotenv, validates all required vars are present at
import time, and fails loud if any are missing. Never logs credential values.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

REQUIRED_VARS: tuple[str, ...] = (
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_APP_SECRET",
    "ANTHROPIC_API_KEY",
    "NOTION_TOKEN",
    "NOTION_TASK_DB_ID",
    "NOTION_IDEAS_DB_ID",
    "GOOGLE_CREDENTIALS_JSON",
    "GOOGLE_TOKEN_PERSONAL",
    "GOOGLE_TOKEN_CGM",
    "GOOGLE_TOKEN_DEALS",
    "ADMIN_TOKEN",
)


def _validate() -> None:
    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )


_validate()

WHATSAPP_VERIFY_TOKEN = os.environ["WHATSAPP_VERIFY_TOKEN"]
WHATSAPP_ACCESS_TOKEN = os.environ["WHATSAPP_ACCESS_TOKEN"]
WHATSAPP_PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
WHATSAPP_APP_SECRET = os.environ["WHATSAPP_APP_SECRET"]

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_TASK_DB_ID = os.environ["NOTION_TASK_DB_ID"]
NOTION_IDEAS_DB_ID = os.environ["NOTION_IDEAS_DB_ID"]

GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]
GOOGLE_TOKEN_PERSONAL = os.environ["GOOGLE_TOKEN_PERSONAL"]
GOOGLE_TOKEN_CGM = os.environ["GOOGLE_TOKEN_CGM"]
GOOGLE_TOKEN_DEALS = os.environ["GOOGLE_TOKEN_DEALS"]

ADMIN_TOKEN = os.environ["ADMIN_TOKEN"]
BOT_ENABLED = os.getenv("BOT_ENABLED", "true").strip().lower() == "true"
