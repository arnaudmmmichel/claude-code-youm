"""
Shared Google Sheets client + tab bootstrap for the Youm SEO control panel.

Two auth paths:
  - Service account (GOOGLE_SERVICE_ACCOUNT_B64 env var) -- used on Netlify
    builds, where there's no browser to complete an interactive OAuth
    consent screen and no persistent disk to cache a token.json across
    builds. Checked first so it takes over automatically in that
    environment without any code change at deploy time.
  - Local interactive OAuth (token.json / credentials.json) -- the
    original flow, kept for Arnaud's local/manual runs. Same flow as
    keyword-search-volume/scripts/write_keywords_to_sheet.py and
    youm-control-panel-server/scripts/sheet_status.py.

The service account must be shared as Editor on BLOG_IDEAS_SHEET_YOUM_PARIS
(and any other sheet these scripts touch) -- see
.claude/skills/youm-seo-control-panel/SKILL.md for the one-time setup steps.
"""

import os
import json
import base64
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

SHEET_ENV_VAR = "BLOG_IDEAS_SHEET_YOUM_PARIS"
SERVICE_ACCOUNT_ENV_VAR = "GOOGLE_SERVICE_ACCOUNT_B64"
KEYWORDS_TAB = "keywords"
FINDINGS_TAB = "seo findings"

KEYWORDS_HEADER = [
    "Keyword", "Avg. monthly searches", "Competition",
    "Already targeted", "Target page URL",
    "Client validated", "Validated at",
]
FINDINGS_HEADER = ["Item", "Category", "Status", "Client validated", "Validated at"]


def get_sheet_client():
    import gspread

    b64_key = os.getenv(SERVICE_ACCOUNT_ENV_VAR)
    if b64_key:
        # Same base64-whole-JSON pattern used by the Node Functions
        # (netlify/functions/_lib/sheets-client.ts) -- sidesteps the
        # private-key-newline-in-env-var class of bugs entirely, and keeps
        # both the build step and the Functions reading the same secret.
        key_dict = json.loads(base64.b64decode(b64_key).decode("utf-8"))
        return gspread.service_account_from_dict(key_dict)

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = None
    if os.path.exists('token.json'):
        try:
            with open('token.json', 'r') as f:
                creds = Credentials.from_authorized_user_info(json.load(f), scopes)
        except Exception:
            pass
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, scopes)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as f:
            f.write(creds.to_json())
    return gspread.authorize(creds)


def extract_sheet_id(url: str) -> str:
    if '/d/' in url:
        return url.split('/d/')[1].split('/')[0]
    return url


def require_sheet_url() -> str:
    url = os.getenv(SHEET_ENV_VAR)
    if not url:
        raise SystemExit(f"Error: {SHEET_ENV_VAR} not set in .env")
    return url


def open_spreadsheet(client=None):
    client = client or get_sheet_client()
    sheet_id = extract_sheet_id(require_sheet_url())
    return client.open_by_key(sheet_id)


def get_or_create_tab(spreadsheet, tab_name: str, header: list):
    """Open a worksheet, creating it with the given header if missing.
    If it exists with fewer columns than `header` (an older schema), extend
    the header row in place rather than requiring a manual migration —
    same non-destructive-extend pattern as write_keywords_to_sheet.py."""
    try:
        ws = spreadsheet.worksheet(tab_name)
    except Exception:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(header))
        ws.update(f"A1:{chr(64 + len(header))}1", [header], value_input_option="USER_ENTERED")
        return ws

    current_header = ws.row_values(1)
    if current_header != header and len(current_header) < len(header):
        ws.update(f"A1:{chr(64 + len(header))}1", [header], value_input_option="USER_ENTERED")
    return ws


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
