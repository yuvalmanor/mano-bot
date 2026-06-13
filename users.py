"""User registry. This is the single allowed location for hardcoded phone numbers.

``google_tokens`` maps a user-facing account_key (the same one the Claude tool
schema exposes — ``"personal" | "cgm" | "deals"``) to the name of the config
attribute holding that user's base64-encoded token. The integration layer reads
the env-var name from here and looks up the live value on ``config``. This
keeps the per-user account resolution co-located with the rest of the user
record (Task 6d).
"""

USERS = {
    "+972542159121": {
        "name": "Yuval",
        "language": "he",
        "permissions": ["notion", "gmail", "calendar", "drive", "idea_lab", "web", "knowledge"],
        "google_tokens": {
            "personal": "GOOGLE_TOKEN_PERSONAL",
            "cgm": "GOOGLE_TOKEN_CGM",
            "deals": "GOOGLE_TOKEN_DEALS",
        },
    },
    "+972546900908": {
        "name": "Eden",
        "language": "he",
        "permissions": ["gmail"],
        "google_tokens": {
            "cgm": "GOOGLE_TOKEN_EDEN_CGM",
        },
    },
}


def get_user(phone: str) -> dict | None:
    return USERS.get(phone)


def is_authorized(phone: str) -> bool:
    return phone in USERS


def has_permission(phone: str, integration: str) -> bool:
    user = get_user(phone)
    return user is not None and integration in user.get("permissions", [])


def get_google_token_env_name(phone: str | None, account_key: str) -> str | None:
    """Return the ``config`` attribute name holding ``phone``'s token for ``account_key``.

    Returns None if the user is unknown, if they have no Google access at all,
    or if they don't own that specific account. Callers should then treat the
    request as a missing-token failure (no fallback to another user's tokens).

    When ``phone`` is None (e.g. service-internal callers), we fall back to
    Yuval's tokens — this preserves pre-6d behavior for code paths that don't
    yet plumb a phone through.
    """
    if phone is None:
        yuval = USERS.get("+972542159121") or {}
        return (yuval.get("google_tokens") or {}).get(account_key)
    user = USERS.get(phone)
    if not user:
        return None
    return (user.get("google_tokens") or {}).get(account_key)
