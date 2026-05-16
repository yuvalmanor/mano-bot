"""User registry. This is the single allowed location for hardcoded phone numbers."""

USERS = {
    "+972542159121": {
        "name": "Yuval",
        "language": "he",
        "permissions": ["notion", "gmail", "calendar", "drive", "idea_lab"],
    },
    "+972546900908": {
        "name": "Eden",
        "language": "he",
        "permissions": [],
    },
}


def get_user(phone: str) -> dict | None:
    return USERS.get(phone)


def is_authorized(phone: str) -> bool:
    return phone in USERS


def has_permission(phone: str, integration: str) -> bool:
    user = get_user(phone)
    return user is not None and integration in user.get("permissions", [])
