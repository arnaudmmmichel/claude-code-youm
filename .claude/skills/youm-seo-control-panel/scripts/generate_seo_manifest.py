#!/usr/bin/env python3
"""
Builds output/youm_paris/seo-manifest.js (window.__SEO_MANIFEST__ = {...}),
the data source for the client-facing "SEO" tab in
output/youm_paris/control-panel.html.

Written as manifest.js (not .json) for the same reason as the existing
manifest.js next to it: control-panel.html can be opened as a file:// page
where fetch() of local files is blocked, but a <script src="..."> tag isn't.
Kept as a SEPARATE file from manifest.js (not merged into it) so
regenerating one never risks the other, and each generator stays focused on
one platform's data shape.

Three top-level arrays, each client-safe (plain language, no file paths, no
internal jargon):

  keywords[]      -- read live from the "keywords" tab of
                      BLOG_IDEAS_SHEET_YOUM_PARIS via Google Sheets. Empty
                      array (not an error) if the tab doesn't exist yet or
                      the sheet is unreachable -- the dashboard shows an
                      empty state rather than crashing.
  articles[]       -- one entry per output/youm_paris/blog/*.html that
                      carries a real <title> + meta description + JSON-LD
                      schema. Articles missing that (the pre-2026-07-22
                      batch) are counted but not listed individually --
                      this is a client deliverable, not an internal gap
                      report, so a wall of "missing" rows would misrepresent
                      an in-progress rollout as neglect.
  site_findings[]  -- curated from data/site_findings_seed.json (a
                      client-safe rewrite of the latest website-audit
                      report). Not auto-parsed from the audit markdown --
                      that report is written in internal analyst language
                      ("per the checklist...") unsuitable for direct
                      client display.

Each array's entries carry validation_status ("pending"/"validated") +
validated_at, read from the Google Sheet's "Client validated"/"Validated
at" columns so re-running this script never resets a client's prior
approvals back to pending.

Usage:
  python .claude/skills/youm-seo-control-panel/scripts/generate_seo_manifest.py
  python .claude/skills/youm-seo-control-panel/scripts/generate_seo_manifest.py --open
"""

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sheet_client import (  # noqa: E402
    get_sheet_client, open_spreadsheet, get_or_create_tab,
    KEYWORDS_TAB, FINDINGS_TAB, KEYWORDS_HEADER, FINDINGS_HEADER,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
YOUM_FOLDER = os.path.join(REPO_ROOT, "output", "youm_paris")
BLOG_FOLDER = os.path.join(YOUM_FOLDER, "blog")
MANIFEST_PATH = os.path.join(YOUM_FOLDER, "seo-manifest.js")
CONTROL_PANEL_PATH = os.path.join(YOUM_FOLDER, "control-panel.html")
SEED_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "site_findings_seed.json")


class ArticleHeadParser(HTMLParser):
    """Extract <title>, meta description, and JSON-LD schema block(s) from
    a Youm blog article's <head>. Unlike seo-weekly-audit's ArticleParser
    (which only records schema *presence*), this reads the actual JSON-LD
    payload so the real target keyword and FAQ count can be surfaced."""

    def __init__(self):
        super().__init__()
        self.title = None
        self.meta_description = None
        self._in_title = False
        self._in_ldjson = False
        self._ldjson_chunks = []
        self.ld_blocks = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and attrs_dict.get("name") == "description":
            self.meta_description = attrs_dict.get("content", "")
        elif tag == "script" and attrs_dict.get("type") == "application/ld+json":
            self._in_ldjson = True
            self._ldjson_chunks = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_ldjson:
            self._in_ldjson = False
            raw = "".join(self._ldjson_chunks).strip()
            if raw:
                try:
                    self.ld_blocks.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        elif self._in_ldjson:
            self._ldjson_chunks.append(data)


def _find_entities(ld_blocks: list, type_name: str) -> list:
    """JSON-LD entities can nest arbitrarily deep -- an @graph wrapper at
    the top, and within it e.g. FAQPage.mainEntity[] holding the actual
    Question entities (the shape html-blog's youm.md prompt emits). Walk
    the whole structure recursively rather than assuming a fixed shape, and
    return every dict matching @type anywhere in it."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("@type") == type_name:
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for block in ld_blocks:
        walk(block)
    return found


def scan_articles() -> tuple:
    """Returns (optimized_articles, in_progress_count)."""
    optimized = []
    in_progress = 0
    if not os.path.isdir(BLOG_FOLDER):
        return optimized, in_progress

    for filename in sorted(os.listdir(BLOG_FOLDER)):
        if not filename.lower().endswith(".html"):
            continue
        filepath = os.path.join(BLOG_FOLDER, filename)
        if not os.path.isfile(filepath):
            continue
        try:
            with open(filepath, encoding="utf-8") as f:
                html = f.read()
        except Exception:
            continue

        parser = ArticleHeadParser()
        parser.feed(html)

        has_title = bool(parser.title and parser.title.strip())
        has_meta = bool(parser.meta_description and len(parser.meta_description.strip()) > 30)
        blog_postings = _find_entities(parser.ld_blocks, "BlogPosting")
        has_schema = bool(blog_postings)

        if not (has_title and has_meta and has_schema):
            in_progress += 1
            continue

        posting = blog_postings[0]
        faq_count = len(_find_entities(parser.ld_blocks, "Question"))
        slug = os.path.splitext(filename)[0]

        optimized.append({
            "id": f"article-{slug}",
            "title": parser.title.strip(),
            "meta_description": parser.meta_description.strip(),
            "keyword": posting.get("keywords") or None,
            "published": posting.get("datePublished") or None,
            "faq_count": faq_count,
        })

    optimized.sort(key=lambda a: a.get("published") or "", reverse=True)
    return optimized, in_progress


def load_site_findings() -> list:
    try:
        with open(SEED_PATH, encoding="utf-8") as f:
            seed = json.load(f)
    except FileNotFoundError:
        return []
    return [f for f in seed.get("findings", []) if not str(f.get("id", "")).startswith("_")]


def fetch_keywords_from_sheet() -> list:
    """Read the "keywords" tab live. Returns [] (not an error) if the sheet
    or tab isn't reachable/doesn't exist yet -- the dashboard shows an empty
    state, since keyword-search-volume may simply not have been run yet."""
    try:
        client = get_sheet_client()
        spreadsheet = open_spreadsheet(client)
        ws = spreadsheet.worksheet(KEYWORDS_TAB)
    except (Exception, SystemExit) as e:
        print(f"Warning: could not read '{KEYWORDS_TAB}' tab ({e}) -- keywords[] will be empty.", file=sys.stderr)
        return []

    rows = ws.get_all_values()
    if not rows:
        return []
    header = rows[0]
    entries = []
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        record = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
        validated = (record.get("Client validated") or "").strip().lower() == "oui"
        entries.append({
            "id": f"keyword-{record.get('Keyword', '').strip().lower().replace(' ', '-')}",
            "keyword": record.get("Keyword", "").strip(),
            "avg_monthly_searches": record.get("Avg. monthly searches", ""),
            "competition": record.get("Competition", ""),
            "already_targeted": record.get("Already targeted", ""),
            "target_url": record.get("Target page URL", ""),
            "validation_status": "validated" if validated else "pending",
            "validated_at": record.get("Validated at", "") or None,
        })
    return entries


def apply_validation_by_title(items: list, validated_by_title: dict, title_key: str = "title"):
    """Shared merge step for articles and site_findings (both validate
    against the "seo findings" tab, matched by their display title) --
    keywords validate against the separate "keywords" tab instead, handled
    by fetch_keywords_from_sheet()."""
    for item in items:
        title = item[title_key]
        if title in validated_by_title:
            item["validation_status"] = "validated"
            item["validated_at"] = validated_by_title[title]
        else:
            item.setdefault("validation_status", "pending")
            item.setdefault("validated_at", None)
    return items


def read_findings_tab_validation() -> dict:
    """Returns {item_title: validated_at} for every row marked "Oui" in the
    "seo findings" tab. Empty dict (not an error) if the tab doesn't exist
    yet -- every item then defaults to pending, which is correct for a
    freshly-bootstrapped tab."""
    try:
        client = get_sheet_client()
        spreadsheet = open_spreadsheet(client)
        ws = spreadsheet.worksheet(FINDINGS_TAB)
        rows = ws.get_all_values()
    except (Exception, SystemExit):
        return {}

    validated = {}
    if rows:
        header = rows[0]
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            record = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
            if (record.get("Client validated") or "").strip().lower() == "oui":
                validated[record.get("Item", "").strip()] = record.get("Validated at", "") or None
    return validated


def fetch_gsc_findings(tracked_keywords: list) -> list:
    """Queries Google Search Console for the last 28 days and runs the
    three recommendation rules in gsc_insights.py. Returns [] (not an
    error) if GSC access isn't set up yet (Arnaud hasn't added the
    service account as a property user) or any call fails -- same
    "never crash the whole manifest build over an optional data source"
    pattern as fetch_keywords_from_sheet()."""
    try:
        import gsc_client
        from gsc_insights import build_gsc_findings

        if not gsc_client.verify_site_access():
            print("Warning: GSC service account does not yet have access to the property -- search_console_findings[] will be empty.", file=sys.stderr)
            return []

        rows = gsc_client.query_search_analytics(days=28)
        return build_gsc_findings(rows, tracked_keywords)
    except Exception as e:
        print(f"Warning: could not fetch Search Console data ({e}) -- search_console_findings[] will be empty.", file=sys.stderr)
        return []


def sync_findings_tab(items: list, category: str, ws=None):
    """Ensure every current item (site finding or optimized article) has a
    row in the "seo findings" tab, so a "Valider" click always has
    somewhere to write to. Non-destructive: only appends rows for titles
    not already present. Reuses an already-open worksheet handle (`ws`)
    across calls so two categories in the same run don't each re-open the
    spreadsheet, and don't race each other's "next empty row" calculation."""
    try:
        if ws is None:
            client = get_sheet_client()
            spreadsheet = open_spreadsheet(client)
            ws = get_or_create_tab(spreadsheet, FINDINGS_TAB, FINDINGS_HEADER)
        existing = {row[0].strip() for row in ws.get_all_values()[1:] if row and row[0].strip()}
    except (Exception, SystemExit) as e:
        print(f"Warning: could not sync '{FINDINGS_TAB}' tab ({e}) -- validation write-back may not work until this is resolved.", file=sys.stderr)
        return ws

    new_rows = []
    for item in items:
        title = item.get("title")
        if title and title not in existing:
            status = item.get("status") or "done"
            new_rows.append([title, category, status, "Non", ""])
            existing.add(title)

    if new_rows:
        next_row = len(ws.col_values(1)) + 1
        ws.update(range_name=f"A{next_row}:E{next_row + len(new_rows) - 1}", values=new_rows, value_input_option="USER_ENTERED")
        print(f"Added {len(new_rows)} new {category.lower()} row(s) to '{FINDINGS_TAB}' tab.")
    return ws


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="Open control-panel.html?tab=seo after regenerating")
    parser.add_argument("--skip-sheet-sync", action="store_true", help="Skip syncing new rows into the 'seo findings' tab (still reads validation status)")
    args = parser.parse_args()

    articles, articles_in_progress = scan_articles()
    site_findings = load_site_findings()

    validated_by_title = read_findings_tab_validation()
    articles = apply_validation_by_title(articles, validated_by_title)
    site_findings = apply_validation_by_title(site_findings, validated_by_title)

    keywords = fetch_keywords_from_sheet()
    search_console_findings = fetch_gsc_findings(keywords)
    search_console_findings = apply_validation_by_title(search_console_findings, validated_by_title)

    if not args.skip_sheet_sync:
        ws = sync_findings_tab(site_findings, "Site")
        ws = sync_findings_tab(articles, "Article", ws=ws)
        sync_findings_tab(search_console_findings, "GSC", ws=ws)

    payload = {
        "generated": datetime.now().isoformat(),
        "keywords": keywords,
        "articles": articles,
        "articles_in_progress_count": articles_in_progress,
        "site_findings": site_findings,
        "search_console_findings": search_console_findings,
    }

    os.makedirs(YOUM_FOLDER, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        f.write("window.__SEO_MANIFEST__ = ")
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write(";\n")

    print(f"Wrote {len(keywords)} keyword row(s), {len(articles)} optimized article(s) "
          f"(+{articles_in_progress} in progress), {len(site_findings)} site finding(s), "
          f"{len(search_console_findings)} Search Console finding(s) to {MANIFEST_PATH}")

    if args.open:
        webbrowser.open(f"file:///{CONTROL_PANEL_PATH.replace(os.sep, '/')}?tab=seo")


if __name__ == "__main__":
    main()
