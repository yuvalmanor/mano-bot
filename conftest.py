"""Test fixtures.

Sets dummy environment variables before ``config`` is imported anywhere, so that
``config._validate()`` does not fail at import time during tests.
"""

from __future__ import annotations

import os

_TEST_ENV = {
    "WHATSAPP_VERIFY_TOKEN": "test-verify-token",
    "WHATSAPP_ACCESS_TOKEN": "test-access-token",
    "WHATSAPP_PHONE_NUMBER_ID": "1234567890",
    "WHATSAPP_APP_SECRET": "test-app-secret",
    "ANTHROPIC_API_KEY": "test-anthropic",
    "NOTION_TOKEN": "test-notion",
    "NOTION_TASK_DB_ID": "test-task-db",
    "NOTION_IDEAS_DB_ID": "test-ideas-db",
    "NOTION_BUCKETS_DB_ID": "test-buckets-db",
    "GOOGLE_CREDENTIALS_JSON": "{}",
    "GOOGLE_TOKEN_PERSONAL": "e30=",
    "GOOGLE_TOKEN_CGM": "e30=",
    "GOOGLE_TOKEN_DEALS": "e30=",
    "ADMIN_TOKEN": "test-admin",
    "BOT_ENABLED": "true",
}

for _k, _v in _TEST_ENV.items():
    if not os.environ.get(_k):
        os.environ[_k] = _v
