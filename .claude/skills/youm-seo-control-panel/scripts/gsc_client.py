"""
Google Search Console (Search Analytics) client for the Youm SEO control
panel. Same two-auth-path pattern as sheet_client.py:

  - Service account (GOOGLE_SERVICE_ACCOUNT_B64 env var) -- used on Netlify
    builds. The service account must be added as a Full user directly in
    the Search Console property's own UI (Settings -> Users and
    permissions -> Add user) -- this is a property-level ACL, not a GCP
    IAM grant, same conceptual step as sharing a Google Sheet.
  - Local interactive OAuth (token_gsc.json / credentials.json) -- kept
    for Arnaud's manual runs. Uses a SEPARATE token file from Sheets'
    token.json since it requests a different scope
    (webmasters.readonly) -- reusing token.json would either fail (scope
    not granted) or silently over-broaden what that cached token can do.

Uses plain `requests` against the REST API rather than pulling in
google-api-python-client, consistent with how get_keyword_volumes.py
calls DataForSEO directly instead of a heavier SDK.

SITE_URL is a Domain property (sc-domain:youm-paris.com), confirmed by
Arnaud -- not auto-detected via sites.list, though verify_site_access()
below still calls sites.list once as a sanity check before querying,
since a wrong/unverified property would otherwise fail with a hard-to-
diagnose 403 on the first real query instead.
"""

import os
import json
import base64
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SITE_URL = "sc-domain:youm-paris.com"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
SEARCH_ANALYTICS_URL = f"https://www.googleapis.com/webmasters/v3/sites/{SITE_URL.replace(':', '%3A')}/searchAnalytics/query"
SITES_LIST_URL = "https://www.googleapis.com/webmasters/v3/sites"

SERVICE_ACCOUNT_ENV_VAR = "GOOGLE_SERVICE_ACCOUNT_B64"
LOCAL_TOKEN_FILE = "token_gsc.json"


def get_gsc_credentials():
    """Returns a google.auth Credentials object (service account or local
    OAuth), scoped for read-only Search Analytics access."""
    b64_key = os.getenv(SERVICE_ACCOUNT_ENV_VAR)
    if b64_key:
        from google.oauth2 import service_account

        key_dict = json.loads(base64.b64decode(b64_key).decode("utf-8"))
        return service_account.Credentials.from_service_account_info(key_dict, scopes=SCOPES)

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(LOCAL_TOKEN_FILE):
        try:
            with open(LOCAL_TOKEN_FILE, "r") as f:
                creds = Credentials.from_authorized_user_info(json.load(f), SCOPES)
        except Exception:
            pass
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(LOCAL_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def _authed_request(url: str, method: str = "GET", json_body: dict = None):
    import requests
    from google.auth.transport.requests import Request as GoogleAuthRequest

    creds = get_gsc_credentials()
    creds.refresh(GoogleAuthRequest())
    headers = {"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"}
    resp = requests.request(method, url, headers=headers, json=json_body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def verify_site_access() -> bool:
    """Confirms the credentials actually have access to SITE_URL, by
    checking it appears in sites.list with a permissionLevel other than
    "siteUnverifiedUser". Returns False (not an exception) on any failure
    -- callers treat "no GSC access yet" as a normal, expected state
    (Arnaud may not have added the service account as a user yet),
    exactly like fetch_keywords_from_sheet() treats a missing sheet tab."""
    try:
        data = _authed_request(SITES_LIST_URL)
    except Exception:
        return False
    for entry in data.get("siteEntry", []):
        if entry.get("siteUrl") == SITE_URL and entry.get("permissionLevel") != "siteUnverifiedUser":
            return True
    return False


def query_search_analytics(days: int = 28, dimensions: list = None, row_limit: int = 5000) -> list:
    """Returns raw rows from searchAnalytics.query for the last `days` days
    (Search Console data itself lags ~2-3 days, so this asks for a window
    ending today -- Google simply returns whatever's actually available
    within it, no need to offset the end date manually).

    Each row: {"keys": [...], "clicks": float, "impressions": float,
    "ctr": float, "position": float} -- keys are ordered to match
    `dimensions`, e.g. dimensions=["query","page"] -> keys=[query, page].
    """
    dimensions = dimensions or ["query", "page"]
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": dimensions,
        "rowLimit": row_limit,
    }
    data = _authed_request(SEARCH_ANALYTICS_URL, method="POST", json_body=body)
    return data.get("rows", [])
