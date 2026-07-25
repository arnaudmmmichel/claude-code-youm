"""
Turns raw Google Search Console searchAnalytics rows into client-facing
"Opportunités de recherche" findings -- the actual optimization insight
logic, not just a data dump of clicks/impressions.

Three rule types (chosen with Arnaud 2026-07-25; declining-pages trend
analysis and query-to-content-gap detection are documented as good
follow-ups, not built here -- see NETLIFY_DEPLOYMENT.md):

  1. Striking distance -- pages ranking positions 9-20 for a query with
     real impressions. One push (better content, an internal link, a
     title tweak) can move these onto page 1, the highest-leverage single
     lever in SEO since the page already ranks and is already relevant.
  2. High impressions, low CTR -- pages getting shown often but rarely
     clicked relative to what's typical for their ranking position.
     Usually a title/meta-description problem, not a ranking problem.
  3. New/unexpected ranking queries -- queries Youm now ranks for that
     aren't in the tracked "keywords" sheet tab. Organic wins worth
     noticing: either add to tracked keywords, or spin into new content.

Each finding matches site_findings_seed.json's shape (id, title,
description, impact, status) so the SAME rendering/validation code in
control-panel.html and generate_seo_manifest.py's sync_findings_tab()
works unmodified -- plus a "source": "gsc" tag and the raw metrics, so
the client can see the number behind the recommendation, not just prose.
"""

import re
import unicodedata

STRIKING_DISTANCE_MIN_POSITION = 9
STRIKING_DISTANCE_MAX_POSITION = 20
STRIKING_DISTANCE_MIN_IMPRESSIONS = 20

LOW_CTR_MIN_IMPRESSIONS = 50
# Rough, widely-cited expected-CTR-by-position bands -- not a precise
# model (real CTR varies heavily by query intent/SERP features), just a
# simple, transparent threshold for "meaningfully underperforming its
# position," same spirit as prioritize_keywords.py's volume/competition
# score in keyword-search-volume (transparent heuristic, not a black box).
CTR_BENCHMARKS = [
    (3, 0.15),   # positions 1-3: expect >15%
    (10, 0.05),  # positions 4-10: expect >5%
    (20, 0.02),  # positions 11-20: expect >2%
]

NEW_QUERY_MIN_IMPRESSIONS = 10
NEW_QUERY_MIN_CLICKS = 1


def _normalize(text: str) -> str:
    """Lowercase + strip accents, matching check_keyword_coverage.py's own
    normalize() -- keywords and GSC queries don't always agree on accents,
    e.g. "bijoux dores" vs "bijoux dorés"."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _slugify(text: str) -> str:
    """DOM/sheet-id-safe slug -- spaces and anything non-alphanumeric
    collapse to a single hyphen, so ids stay stable and safely embeddable
    in HTML attributes/onclick strings client-side."""
    slug = re.sub(r"[^a-z0-9]+", "-", _normalize(text)).strip("-")
    return slug or "item"


def _expected_ctr(position: float) -> float:
    for max_pos, expected in CTR_BENCHMARKS:
        if position <= max_pos:
            return expected
    return 0.01


def _page_label(page_url: str) -> str:
    """Short, readable label for a URL in client-facing text -- the path
    only, since every URL shares the same youm-paris.com host."""
    return page_url.split("youm-paris.com", 1)[-1] or "/"


def find_striking_distance(rows: list) -> list:
    findings = []
    for row in rows:
        query, page = row["keys"][0], row["keys"][1]
        position, impressions = row["position"], row["impressions"]
        if STRIKING_DISTANCE_MIN_POSITION <= position <= STRIKING_DISTANCE_MAX_POSITION and impressions >= STRIKING_DISTANCE_MIN_IMPRESSIONS:
            findings.append({
                "id": f"gsc-striking-{_slugify(query)}-{_slugify(_page_label(page))}",
                "title": f"« {query} » — page proche de la première page Google",
                "description": f"{_page_label(page)} se classe en position {position:.0f} pour cette recherche, avec {impressions:.0f} apparitions sur 28 jours. Un ajustement ciblé (contenu, maillage interne, titre) peut suffire à la faire progresser vers la première page.",
                "impact": "Élevé",
                "status": "planned",
                "source": "gsc",
                "metric_label": f"Position {position:.0f}",
                "page_url": page,
                "query": query,
                "_sort_impressions": impressions,
            })
    findings.sort(key=lambda f: -f.pop("_sort_impressions"))
    return findings


def find_low_ctr(rows: list) -> list:
    findings = []
    for row in rows:
        query, page = row["keys"][0], row["keys"][1]
        position, impressions, ctr = row["position"], row["impressions"], row["ctr"]
        if impressions < LOW_CTR_MIN_IMPRESSIONS:
            continue
        expected = _expected_ctr(position)
        if ctr < expected / 2:
            findings.append({
                "id": f"gsc-lowctr-{_slugify(query)}-{_slugify(_page_label(page))}",
                "title": f"« {query} » — vue souvent, peu cliquée",
                "description": f"{_page_label(page)} apparaît {impressions:.0f} fois pour cette recherche (position {position:.0f}) mais n'obtient que {ctr*100:.1f}% de clics, bien en dessous de la moyenne attendue à ce niveau. Le titre ou la description affichés dans Google mériteraient d'être retravaillés.",
                "impact": "Moyen",
                "status": "planned",
                "source": "gsc",
                "metric_label": f"{ctr*100:.1f}% de clics",
                "page_url": page,
                "query": query,
            })
    return findings


def find_new_ranking_queries(rows: list, tracked_keywords: list) -> list:
    tracked_normalized = {_normalize(k.get("keyword", "")) for k in tracked_keywords}
    # Aggregate by query alone (rows here are query+page granular) --
    # a query already generating clicks on ANY page counts as "already
    # ranking", the finding doesn't need a specific page attached.
    by_query = {}
    for row in rows:
        query = row["keys"][0]
        agg = by_query.setdefault(query, {"impressions": 0.0, "clicks": 0.0, "page": row["keys"][1]})
        agg["impressions"] += row["impressions"]
        agg["clicks"] += row["clicks"]

    findings = []
    for query, agg in by_query.items():
        if _normalize(query) in tracked_normalized:
            continue
        if agg["impressions"] < NEW_QUERY_MIN_IMPRESSIONS or agg["clicks"] < NEW_QUERY_MIN_CLICKS:
            continue
        findings.append({
            "id": f"gsc-newquery-{_slugify(query)}",
            "title": f"« {query} » — trafic déjà généré sans ciblage actif",
            "description": f"Cette recherche apporte déjà {agg['clicks']:.0f} clic(s) et {agg['impressions']:.0f} apparition(s) sur 28 jours, sans figurer dans les mots-clés suivis. À ajouter au suivi, ou à approfondir avec du contenu dédié.",
            "impact": "Moyen",
            "status": "planned",
            "source": "gsc",
            "metric_label": f"{agg['clicks']:.0f} clics",
            "page_url": agg["page"],
            "query": query,
            "_sort_clicks": agg["clicks"],
        })
    findings.sort(key=lambda f: -f.pop("_sort_clicks"))
    return findings


def build_gsc_findings(rows: list, tracked_keywords: list) -> list:
    """Runs all three rules and returns one combined, de-duplicated list.
    Order: striking distance first (highest-leverage), then low-CTR, then
    new queries -- roughly most to least actionable."""
    return (
        find_striking_distance(rows)
        + find_low_ctr(rows)
        + find_new_ranking_queries(rows, tracked_keywords)
    )
