"""One-off helper to obtain a Google user token for the bot.

🔴 RISK: Opens a browser for the Google OAuth flow and listens on a local
loopback port for the redirect. Run this once per Gmail account, paste the
printed base64 string into the corresponding Railway env var, and you're done.

Usage:
    python scripts/oauth_setup_google.py <account_key>

Where <account_key> is one of: personal | cgm | deals
  personal → yuvalmanor@gmail.com   → paste output into GOOGLE_TOKEN_PERSONAL
  cgm      → yuval.cgm@gmail.com    → paste output into GOOGLE_TOKEN_CGM
  deals    → deals@cgm-ventures.com → paste output into GOOGLE_TOKEN_DEALS

Prereqs:
  - GOOGLE_CREDENTIALS_JSON is set in your local .env (the static OAuth client
    credentials JSON downloaded from Google Cloud Console).
  - The Google Cloud project's OAuth consent screen includes the target Gmail
    account as a test user, and the gmail.send + calendar.events + drive.readonly
    scopes are enabled.

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
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]

ACCOUNT_HINTS = {
    "personal": "yuvalmanor@gmail.com",
    "cgm": "yuval.cgm@gmail.com",
    "deals": "deals@cgm-ventures.com",
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ACCOUNT_HINTS:
        print(__doc__, file=sys.stderr)
        return 2

    account_key = sys.argv[1]
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

    print(
        f"Starting OAuth flow for account_key={account_key} "
        f"(expected: {expected_email})",
        file=sys.stderr,
    )
    print("A browser window will open. Sign in with the EXACT account above.", file=sys.stderr)

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")

    token_dict = json.loads(creds.to_json())
    encoded = base64.b64encode(json.dumps(token_dict).encode()).decode()

    env_var = f"GOOGLE_TOKEN_{account_key.upper()}"
    print(
        f"\n--- Paste this whole line into Railway as {env_var} ---",
        file=sys.stderr,
    )
    print(encoded)
    print(f"--- (no quotes, no newlines) ---", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
