"""
Writes a client validation ("Oui" + timestamp) back into the Google Sheet
row matching a keyword, article, or site-finding item.

Split out from seo_panel_server.py so the same write-back logic can later be
called from a Netlify Function (or any other host) without depending on
Python's http.server -- only this module's update_validation() needs a
non-stdlib-server home when the panel moves to Netlify.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sheet_client import (  # noqa: E402
    get_sheet_client, open_spreadsheet, get_or_create_tab, now_iso,
    KEYWORDS_TAB, FINDINGS_TAB, KEYWORDS_HEADER, FINDINGS_HEADER,
)

VALID_TYPES = {"keyword", "article", "site_finding"}


def update_validation(item_type: str, item_id: str, label: str) -> dict:
    """Find the sheet row matching this item and mark it client-validated.

    item_type: "keyword" -> matched by keyword text (column A of 'keywords')
               "article" | "site_finding" -> matched by title/finding text
               (column A of 'seo findings')
    label: the human-readable text to match on (keyword string, article
           title, or finding title) -- the manifest's id fields are
           slug-derived and not guaranteed to round-trip to the exact sheet
           cell text, so matching is done on the display label instead.

    Returns {"matched": bool, "row_number": int|None}.
    """
    if item_type not in VALID_TYPES:
        raise ValueError(f"Unknown item_type: {item_type!r} -- expected one of {sorted(VALID_TYPES)}")
    if not label or not label.strip():
        raise ValueError("label is required to locate the sheet row")

    client = get_sheet_client()
    spreadsheet = open_spreadsheet(client)
    target = label.strip().lower()

    if item_type == "keyword":
        ws = get_or_create_tab(spreadsheet, KEYWORDS_TAB, KEYWORDS_HEADER)
        validated_col = KEYWORDS_HEADER.index("Client validated") + 1
        validated_at_col = KEYWORDS_HEADER.index("Validated at") + 1
    else:
        ws = get_or_create_tab(spreadsheet, FINDINGS_TAB, FINDINGS_HEADER)
        validated_col = FINDINGS_HEADER.index("Client validated") + 1
        validated_at_col = FINDINGS_HEADER.index("Validated at") + 1

    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if row and row[0].strip().lower() == target:
            ws.update_cell(i, validated_col, "Oui")
            ws.update_cell(i, validated_at_col, now_iso())
            return {"matched": True, "row_number": i}

    return {"matched": False, "row_number": None, "item_id": item_id}
