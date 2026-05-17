"""One-off helper to obtain a Google user token for the bot.

Two flow modes:

* **default (loopback)** — `InstalledAppFlow.run_local_server`. Opens a browser
  AND binds a temporary localhost port for the OAuth redirect. 🔴 SentinelOne
  risk: port binding + outbound HTTPS together.

* **--manual** — auth-URL + paste-redirect flow. Prints the auth URL to the
  terminal, you sign in in your browser, copy the full URL the browser lands on
  (which will show "site can't be reached" — that's expected, no listener),
  paste it back. Token exchange is a single outbound HTTPS POST. 🟡 risk only.

Usage:
    python scripts/oauth_setup_google.py <account_key> [--manual]

<account_key> is one of: personal | cgm | deals
  personal → yuvalmanor@gmail.com   → paste output into GOOGLE_TOKEN_PERSONAL
  cgm      → yuval.cgm@gmail.com    → paste output into GOOGLE_TOKEN_CGM
  deals    → deals@cgm-ventures.com → paste output into GOOGLE_TOKEN_DEALS

Prereqs:
  - GOOGLE_CREDENTIALS_JSON is set in your local .env (the static OAuth client
    credentials JSON downloaded from Google Cloud Console).
  - The Google Cloud project's OAuth consent screen has the target Gmail
    account enrolled as a test user, and Gmail/Calendar/Drive APIs are enabled.

Output:
  Prints a single base64 string to stdout. Copy that whole line and paste it
  into the matching Railway env var (no quotes, no newlines).
"""

from __future__ import annotations

import base64
import json
import os
import sys

from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow, InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts.other.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]

ACCOUNT_HINTS = {
    "personal": "yuvalmanor@gmail.com",
    "cgm": "yuval.cgm@gmail.com",
    "deals": "deals@cgm-ventures.com",
}

# Any fixed localhost port works for the manual flow — nothing listens there,
# we just need a redirect URI Google accepts for Desktop OAuth clients
# (Google allows any http://localhost:<port> for Desktop type).
MANUAL_REDIRECT_URI = "http://localhost:8765"


def _emit_token(creds, account_key: str) -> None:
    token_dict = json.loads(creds.to_json())
    encoded = base64.b64encode(json.dumps(token_dict).encode()).decode()
    env_var = f"GOOGLE_TOKEN_{account_key.upper()}"
    print(
        f"\n--- Paste this whole line into Railway as {env_var} ---",
        file=sys.stderr,
    )
    print(encoded)
    print("--- (no quotes, no newlines) ---", file=sys.stderr)


def _run_loopback(client_config: dict, account_key: str) -> int:
    print("A browser window will open. Sign in with the EXACT account above.", file=sys.stderr)
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _emit_token(creds, account_key)
    return 0


def _run_manual(client_config: dict, account_key: str) -> int:
    # oauthlib refuses to parse a non-HTTPS authorization_response by default.
    # For the manual flow we redirect to http://localhost:8765 (loopback only,
    # never leaves the machine), so this is the documented workaround.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = MANUAL_REDIRECT_URI
    auth_url, _state = flow.authorization_url(
        prompt="consent", access_type="offline", include_granted_scopes="true"
    )
    print("\n=== STEP 1 — Open this URL in your browser ===", file=sys.stderr)
    print(auth_url)
    print(
        "\n=== STEP 2 — Sign in with the account above, approve the scopes. ===\n"
        "Google will then try to redirect to http://localhost:8765/... and your\n"
        "browser will show a connection-error page. THAT IS EXPECTED — no server\n"
        "is listening. Look at the address bar: the URL contains ?code=...&...\n",
        file=sys.stderr,
    )
    redirected = input("=== STEP 3 — Paste the FULL redirected URL here, then Enter:\n> ").strip()
    if not redirected:
        print("ERROR: empty input", file=sys.stderr)
        return 1
    try:
        flow.fetch_token(authorization_response=redirected)
    except Exception as exc:
        print(f"ERROR: token exchange failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    _emit_token(flow.credentials, account_key)
    return 0


def main() -> int:
    args = sys.argv[1:]
    manual = False
    if "--manual" in args:
        manual = True
        args.remove("--manual")
    if len(args) != 1 or args[0] not in ACCOUNT_HINTS:
        print(__doc__, file=sys.stderr)
        return 2

    account_key = args[0]
    expected_email = ACCOUNT_HINTS[account_key]

    load_dotenv()
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        print("ERROR: GOOGLE_CREDENTIALS_JSON not set in .env", file=sys.stderr)
        return 1

    try:
        client_config = json.loads(creds_json)
    except json.JSONDecodeError as exc:
        print(f"ERROR: GOOGLE_CREDENTIALS_JSON is not valid JSON: {exc}", file=sys.stderr)
        return 1

    mode = "manual" if manual else "loopback"
    print(
        f"Starting OAuth flow ({mode}) for account_key={account_key} "
        f"(expected: {expected_email})",
        file=sys.stderr,
    )

    if manual:
        return _run_manual(client_config, account_key)
    return _run_loopback(client_config, account_key)


if __name__ == "__main__":
    sys.exit(main())
