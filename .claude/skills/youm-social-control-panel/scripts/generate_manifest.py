"""
Scans output/youm_paris/instagram/cloudinary-images/ for generated Instagram
post assets (made by cloudinary-instagram-image-youm) and writes manifest.js
(in output/youm_paris/, next to control-panel.html) for the dashboard to read.

manifest.js (not manifest.json) is used deliberately: control-panel.html is
opened directly as a file:// URL with no local server, and browsers block
fetch() of local files from file:// pages. A <script src="manifest.js"> tag
has no such restriction, so the manifest is emitted as
`window.__MANIFEST__ = {...};` instead of raw JSON. Same pattern as Linxet's
control-panel skills.

Three source types exist for Youm Instagram: cloudinary-images/*.png from
cloudinary-instagram-image-youm (flat text-overlay cards), ai-model-images/*.jpg
from youm-ai-model-image (photorealistic AI-model lifestyle photos), and
ai-model-videos/*.mp4 from youm-ai-model-video (8s Veo 3.1 image-to-video
clips, added 2026-07-22). Each carries a distinct "source_type" field
("cloudinary-card" / "ai-model" / "ai-model-video") so the dashboard can
visually tell them apart, and a "type" field ("image" or "video") that
controls which preview element the dashboard renders.

Pinterest now has FIVE generation pipelines (added 2026-07-22):
pinterest/cloudinary-images/ from cloudinary-pinterest-image-youm (one pin =
one {slug}.png + one {slug}.html detail page + one {slug}.source.json
sidecar — was 3 layout variants per pin until Arnaud picked one layout and
asked to drop the other two the same day; older pins with -1/-2/-3 files
still on disk are still grouped into one card each for backward
compatibility); pinterest/text-pins/ from pinterest-text-pin-youm
(standalone quote cards, one file = one pin, same shape as an Instagram
cloudinary-card entry); and THREE sibling collage templates sharing the
same pinterest/cloudinary-images/ folder but distinct filename suffixes —
cloudinary-pinterest-collage-youm ({slug}-collage.png, plain product-photo
grid), cloudinary-pinterest-lifestyle-collage-youm ({slug}-lifestyle.png,
1 featured + N supporting AI lifestyle photos), and
cloudinary-pinterest-pairs-collage-youm ({slug}-pairs.png, 2 products x
packshot+AI photo). All three collage scanners share one helper,
_scan_collage_family(), since their file shape is identical (one PNG, one
HTML detail page, one source.json sidecar per pin, no numbered variants).
Manually-tracked pins (added via the dashboard's own "+ Ajouter un pin" form)
still live entirely in localStorage and are NOT written here — this script
only ever writes scanned, disk-backed pins to the "pinterest_pins" manifest key.

Usage:
    python .claude/skills/youm-social-control-panel/scripts/generate_manifest.py
    python .claude/skills/youm-social-control-panel/scripts/generate_manifest.py --open
"""
import argparse
import json
import os
import webbrowser
from datetime import datetime

try:
    from PIL import Image
except ImportError:
    Image = None

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
YOUM_FOLDER = os.path.join(REPO_ROOT, "output", "youm_paris")
IMAGES_FOLDER = os.path.join(YOUM_FOLDER, "instagram", "cloudinary-images")
AI_MODEL_IMAGES_FOLDER = os.path.join(YOUM_FOLDER, "ai-model-images")
AI_MODEL_VIDEOS_FOLDER = os.path.join(YOUM_FOLDER, "ai-model-videos")
PINTEREST_ARTICLE_FOLDER = os.path.join(YOUM_FOLDER, "pinterest", "cloudinary-images")
PINTEREST_TEXT_PIN_FOLDER = os.path.join(YOUM_FOLDER, "pinterest", "text-pins")
MANIFEST_PATH = os.path.join(YOUM_FOLDER, "manifest.js")
CONTROL_PANEL_PATH = os.path.join(YOUM_FOLDER, "control-panel.html")


def title_from_slug(filename: str) -> str:
    slug = os.path.splitext(filename)[0]
    return slug.replace("-", " ").replace("_", " ").strip().title()


def image_dimensions(filepath: str):
    if Image is None:
        return None, None
    try:
        with Image.open(filepath) as img:
            return img.width, img.height
    except Exception:
        return None, None


def load_source_sidecar(filepath: str) -> dict:
    sidecar_path = os.path.splitext(filepath)[0] + ".source.json"
    if not os.path.isfile(sidecar_path):
        return {}
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def resolve_video_product_url(video_sidecar: dict) -> str:
    """youm-ai-model-video's own sidecar only stores source_image (a local
    file path to the source AI image, not a product URL) — added
    2026-07-23 so the control-panel server can match a video card back to
    an "images IA" sheet row for status write-back. Looks up the source
    image's own .source.json (written by youm-ai-model-image) for its
    product_url. Returns "" if no source_image, no sidecar, or no
    product_url field — never raises, this is a best-effort enrichment."""
    source_image = video_sidecar.get("source_image") or ""
    if not source_image:
        return ""
    image_sidecar = load_source_sidecar(source_image)
    return image_sidecar.get("product_url") or ""


def scan_instagram_images() -> list:
    entries = []
    if not os.path.isdir(IMAGES_FOLDER):
        return entries
    for filename in os.listdir(IMAGES_FOLDER):
        if not filename.lower().endswith(".png"):
            continue
        filepath = os.path.join(IMAGES_FOLDER, filename)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        width, height = image_dimensions(filepath)
        sidecar = load_source_sidecar(filepath)
        detail_page_path = os.path.splitext(filepath)[0] + ".html"
        reldir = "instagram/cloudinary-images"
        detail_page = f"{reldir}/{os.path.splitext(filename)[0]}.html" if os.path.isfile(detail_page_path) else None
        entries.append({
            "platform": "instagram",
            "filename": f"{reldir}/{filename}",
            "detail_page": detail_page,
            "title": title_from_slug(filename),
            "type": "image",
            "source_type": "cloudinary-card",
            "caption": sidecar.get("caption") if sidecar else None,
            "source": sidecar.get("source") if sidecar else None,
            "size_kb": round(stat.st_size / 1024, 1),
            "width": width,
            "height": height,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def scan_ai_model_images() -> list:
    entries = []
    if not os.path.isdir(AI_MODEL_IMAGES_FOLDER):
        return entries
    for filename in os.listdir(AI_MODEL_IMAGES_FOLDER):
        if not filename.lower().endswith(".jpg"):
            continue
        filepath = os.path.join(AI_MODEL_IMAGES_FOLDER, filename)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        width, height = image_dimensions(filepath)
        sidecar = load_source_sidecar(filepath)
        reldir = "ai-model-images"
        model = sidecar.get("model") if sidecar else None
        season = sidecar.get("season") if sidecar else None
        detail_page_path = os.path.splitext(filepath)[0] + ".html"
        detail_page = f"{reldir}/{os.path.splitext(filename)[0]}.html" if os.path.isfile(detail_page_path) else None
        entries.append({
            "platform": "instagram",
            "filename": f"{reldir}/{filename}",
            "detail_page": detail_page,
            "title": sidecar.get("title") or title_from_slug(filename),
            "type": "image",
            "source_type": "ai-model",
            "caption": sidecar.get("caption_instagram") if sidecar else None,
            "caption_pinterest": sidecar.get("caption_pinterest") if sidecar else None,
            "source": sidecar.get("product_url") if sidecar else None,
            "product_url": sidecar.get("product_url") if sidecar else None,
            "model": f"#{model}" if model else None,
            "season": season,
            "size_kb": round(stat.st_size / 1024, 1),
            "width": width,
            "height": height,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def scan_ai_model_videos() -> list:
    entries = []
    if not os.path.isdir(AI_MODEL_VIDEOS_FOLDER):
        return entries
    for filename in os.listdir(AI_MODEL_VIDEOS_FOLDER):
        if not filename.lower().endswith(".mp4"):
            continue
        filepath = os.path.join(AI_MODEL_VIDEOS_FOLDER, filename)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        sidecar = load_source_sidecar(filepath)
        reldir = "ai-model-videos"
        detail_page_path = os.path.splitext(filepath)[0] + ".html"
        detail_page = f"{reldir}/{os.path.splitext(filename)[0]}.html" if os.path.isfile(detail_page_path) else None
        entries.append({
            "platform": "instagram",
            "filename": f"{reldir}/{filename}",
            "detail_page": detail_page,
            "title": title_from_slug(filename),
            "type": "video",
            "source_type": "ai-model-video",
            "caption": sidecar.get("caption_instagram") if sidecar else None,
            "caption_tiktok": sidecar.get("caption_tiktok") if sidecar else None,
            "caption_youtube_title": sidecar.get("caption_youtube_title") if sidecar else None,
            "caption_youtube_description": sidecar.get("caption_youtube_description") if sidecar else None,
            "source": sidecar.get("source_image") if sidecar else None,
            "product_url": resolve_video_product_url(sidecar) if sidecar else None,
            "duration": sidecar.get("duration_seconds") if sidecar else None,
            "size_kb": round(stat.st_size / 1024, 1),
            "width": None,
            "height": None,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def scan_archived_assets(source_folder: str, reldir: str, extension: str, source_type: str) -> list:
    """Scans output/youm_paris/_archive/{ai-model-images,ai-model-videos}/
    for cards marked "à refaire" via delete-asset.ts -- added 2026-07-25 so
    the AI Image/AI Vidéo "À refaire" filter option has real data to show,
    instead of an item just vanishing forever with no review trail.

    _archive/ was already invisible to scan_ai_model_images()/
    scan_ai_model_videos() (os.listdir() is non-recursive, so a sibling
    _archive/ subfolder was structurally never visited) -- this is a new
    scan pointed AT that folder, not an exclusion added to the existing
    ones.

    Archived items no longer have an .html detail page (delete-asset.ts
    hard-deletes it) -- detail_page is always None here. The .source.json
    sidecar DOES survive (moved alongside the media as of 2026-07-25,
    previously hard-deleted), so title/product_url/etc. are still real."""
    entries = []
    archive_folder = os.path.join(source_folder, "..", "_archive", reldir)
    archive_folder = os.path.normpath(archive_folder)
    if not os.path.isdir(archive_folder):
        return entries
    for filename in os.listdir(archive_folder):
        if not filename.lower().endswith(extension):
            continue
        filepath = os.path.join(archive_folder, filename)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        sidecar = load_source_sidecar(filepath)
        # "filename" is the path the browser must actually load the media
        # from (under _archive/, its real current location) -- distinct
        # from "original_filename", the pre-archive path restore-asset.ts
        # needs to know where to move it BACK to. Conflating these two
        # (an earlier version of this function did) breaks every archived
        # card's <img>/<video> src, since it pointed at a path that no
        # longer has a file there.
        base_slug = os.path.splitext(filename)[0]
        entries.append({
            "filename": f"_archive/{reldir}/{filename}",
            "original_filename": f"{reldir}/{filename}",
            "original_source_json": f"{reldir}/{base_slug}.source.json",
            "detail_page": None,
            "title": sidecar.get("title") or title_from_slug(filename),
            "type": "video" if extension == ".mp4" else "image",
            "source_type": source_type,
            "product_url": sidecar.get("product_url") if sidecar else None,
            "archived": True,
            "size_kb": round(stat.st_size / 1024, 1),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def scan_pinterest_article_pins() -> list:
    """One pin = one {slug}.png + one {slug}.html + one {slug}.source.json.

    Single-layout since 2026-07-22 (was 3 layout-variant PNGs per pin,
    {slug}-1.png/-2.png/-3.png, before Arnaud picked one layout and asked to
    drop the other two) — still handles old -1/-2/-3 files left on disk from
    pins generated before the change, grouping them under one card exactly
    like before, so nothing already on disk disappears from the dashboard."""
    entries = []
    if not os.path.isdir(PINTEREST_ARTICLE_FOLDER):
        return entries

    # Suffixes owned by the 4 sibling collage-template scanners below —
    # excluded here so e.g. {slug}-collage.png doesn't get misparsed as a
    # numbered "variant" of the plain text pin (its suffix isn't a digit,
    # so it would otherwise fall into the "no digit suffix" branch and be
    # treated as its own unrelated single-file pin, duplicating what the
    # collage scanner already reports). "-collage-compact" must be listed
    # even though it doesn't literally end with "-collage" — Python's
    # str.endswith() only matches the full literal suffix, so
    # "{slug}-collage-compact".endswith("-collage") is False and it would
    # otherwise fall through uncaught.
    COLLAGE_SUFFIXES = ("-collage", "-collage-compact", "-lifestyle", "-pairs")

    slugs = {}
    for filename in os.listdir(PINTEREST_ARTICLE_FOLDER):
        if not filename.lower().endswith(".png"):
            continue
        base = os.path.splitext(filename)[0]
        if any(base.endswith(suf) for suf in COLLAGE_SUFFIXES):
            continue
        if "-" in base and base.rsplit("-", 1)[1].isdigit():
            slug, variant_num = base.rsplit("-", 1)
        else:
            slug, variant_num = base, "1"
        slugs.setdefault(slug, []).append((variant_num, filename))

    reldir = "pinterest/cloudinary-images"
    for slug, variant_files in slugs.items():
        variant_files.sort(key=lambda vf: vf[0])
        first_filepath = os.path.join(PINTEREST_ARTICLE_FOLDER, variant_files[0][1])
        if not os.path.isfile(first_filepath):
            continue
        stat = os.stat(first_filepath)
        sidecar = load_source_sidecar(os.path.join(PINTEREST_ARTICLE_FOLDER, f"{slug}.png"))
        detail_page_path = os.path.join(PINTEREST_ARTICLE_FOLDER, f"{slug}.html")
        detail_page = f"{reldir}/{slug}.html" if os.path.isfile(detail_page_path) else None

        variants = []
        sidecar_variants = sidecar.get("variants", {}) if sidecar else {}
        for num, filename in variant_files:
            width, height = image_dimensions(os.path.join(PINTEREST_ARTICLE_FOLDER, filename))
            # Old sidecars nest per-variant copy under "variants"."variant_N";
            # new sidecars (single layout) carry hook/headline/label flat at
            # the top level — fall back to that when there's no variants dict.
            v = sidecar_variants.get(f"variant_{num}", {}) if sidecar_variants else {}
            headline = v.get("headline") or (sidecar.get("hook") or sidecar.get("headline") if sidecar else None)
            variants.append({
                "filename": f"{reldir}/{filename}",
                "headline": headline,
                "width": width,
                "height": height,
            })

        entries.append({
            "id": f"pinterest-article-{slug}",
            "source_type": "pinterest-article",
            "title": sidecar.get("pin_title") or title_from_slug(slug) if sidecar else title_from_slug(slug),
            "pin_title": sidecar.get("pin_title") if sidecar else None,
            "pin_description": sidecar.get("pin_description") if sidecar else None,
            "board": sidecar.get("board") if sidecar else None,
            "dest_url": sidecar.get("dest_url") if sidecar else None,
            "source": sidecar.get("source") if sidecar else None,
            "detail_page": detail_page,
            "variants": variants,
            "filename": variants[0]["filename"] if variants else None,
            "size_kb": round(stat.st_size / 1024, 1),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def _scan_collage_family(suffix: str, source_type: str, id_prefix: str, count_label: str) -> list:
    """Shared scanner for the 3 collage-template skills added 2026-07-22
    (cloudinary-pinterest-collage-youm, -lifestyle-collage-youm, -pairs-
    collage-youm) — each writes exactly one {slug}{suffix}.png +
    {slug}{suffix}.html + {slug}{suffix}.source.json per pin (no numbered
    variants, unlike the text-only pin's -1/-2/-3 history), so one file =
    one manifest entry, simpler than scan_pinterest_article_pins()'s
    variant-grouping logic. Reused for all 3 rather than duplicated three
    times since the shape is identical — only the suffix, source_type,
    id_prefix, and the human-readable count_label (for the dashboard
    badge) differ per template."""
    entries = []
    if not os.path.isdir(PINTEREST_ARTICLE_FOLDER):
        return entries
    reldir = "pinterest/cloudinary-images"
    suffix_lower = f"{suffix}.png"
    for filename in os.listdir(PINTEREST_ARTICLE_FOLDER):
        if not filename.lower().endswith(suffix_lower):
            continue
        filepath = os.path.join(PINTEREST_ARTICLE_FOLDER, filename)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        width, height = image_dimensions(filepath)
        sidecar = load_source_sidecar(filepath)
        base = os.path.splitext(filename)[0]
        slug = base[: -len(suffix)] if base.endswith(suffix) else base
        detail_page_path = os.path.join(PINTEREST_ARTICLE_FOLDER, f"{base}.html")
        detail_page = f"{reldir}/{base}.html" if os.path.isfile(detail_page_path) else None
        headline = (sidecar.get("hook") or sidecar.get("pin_title")) if sidecar else None

        entries.append({
            "id": f"{id_prefix}-{slug}",
            "source_type": source_type,
            "title": sidecar.get("pin_title") or title_from_slug(slug) if sidecar else title_from_slug(slug),
            "pin_title": sidecar.get("pin_title") if sidecar else None,
            "pin_description": sidecar.get("pin_description") if sidecar else None,
            "board": sidecar.get("board") if sidecar else None,
            "dest_url": sidecar.get("dest_url") if sidecar else None,
            "source": sidecar.get("source") if sidecar else None,
            "detail_page": detail_page,
            "count_label": count_label,
            "variants": [{"filename": f"{reldir}/{filename}", "headline": headline, "width": width, "height": height}],
            "filename": f"{reldir}/{filename}",
            "size_kb": round(stat.st_size / 1024, 1),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def scan_pinterest_product_collage_pins() -> list:
    """cloudinary-pinterest-collage-youm — plain product-photo grid,
    {slug}-collage.png."""
    return _scan_collage_family("-collage", "pinterest-collage", "pinterest-collage", "collage produits")


def scan_pinterest_compact_collage_pins() -> list:
    """cloudinary-pinterest-collage-compact-youm — same plain product-photo
    grid mechanics as the sibling above, but fixed at a 2x2 (max 4 photo)
    layout instead of up to 6 — {slug}-collage-compact.png. Added
    2026-07-24 as a "fewer, bigger cells" variant, not a replacement."""
    return _scan_collage_family("-collage-compact", "pinterest-collage-compact", "pinterest-collage-compact", "collage compact")


def scan_pinterest_lifestyle_collage_pins() -> list:
    """cloudinary-pinterest-lifestyle-collage-youm — 1 featured + N
    supporting lifestyle photos, {slug}-lifestyle.png."""
    return _scan_collage_family("-lifestyle", "pinterest-lifestyle", "pinterest-lifestyle", "collage lifestyle")


def scan_pinterest_pairs_collage_pins() -> list:
    """cloudinary-pinterest-pairs-collage-youm — 2 products x packshot+IA,
    {slug}-pairs.png."""
    return _scan_collage_family("-pairs", "pinterest-pairs", "pinterest-pairs", "collage pairs")


def scan_pinterest_text_pins() -> list:
    entries = []
    if not os.path.isdir(PINTEREST_TEXT_PIN_FOLDER):
        return entries
    reldir = "pinterest/text-pins"
    for filename in os.listdir(PINTEREST_TEXT_PIN_FOLDER):
        if not filename.lower().endswith(".png"):
            continue
        filepath = os.path.join(PINTEREST_TEXT_PIN_FOLDER, filename)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        width, height = image_dimensions(filepath)
        sidecar = load_source_sidecar(filepath)
        slug = os.path.splitext(filename)[0]
        detail_page_path = os.path.join(PINTEREST_TEXT_PIN_FOLDER, f"{slug}.html")
        detail_page = f"{reldir}/{slug}.html" if os.path.isfile(detail_page_path) else None

        entries.append({
            "id": f"pinterest-text-{slug}",
            "source_type": "pinterest-text",
            "title": sidecar.get("pin_title") or title_from_slug(slug) if sidecar else title_from_slug(slug),
            "pin_title": sidecar.get("pin_title") if sidecar else None,
            "pin_description": sidecar.get("pin_description") if sidecar else None,
            "board": sidecar.get("board") if sidecar else None,
            "dest_url": sidecar.get("dest_url") if sidecar else None,
            "source": sidecar.get("source") if sidecar else None,
            "detail_page": detail_page,
            "variants": [{"filename": f"{reldir}/{filename}", "headline": sidecar.get("quote") if sidecar else None, "width": width, "height": height}],
            "filename": f"{reldir}/{filename}",
            "size_kb": round(stat.st_size / 1024, 1),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="Open control-panel.html in the default browser after regenerating")
    args = parser.parse_args()

    # Split by source_type into three separate top-level arrays (added
    # 2026-07-23, replacing the single mixed "posts" array) so the dashboard
    # can show Instagram / AI Image / AI Video as three independent tabs
    # instead of badges within one Instagram tab.
    instagram_entries = scan_instagram_images()
    instagram_entries.sort(key=lambda e: e["created"])
    ai_image_entries = scan_ai_model_images()
    ai_image_entries.sort(key=lambda e: e["created"])
    ai_video_entries = scan_ai_model_videos()
    ai_video_entries.sort(key=lambda e: e["created"])

    # "À refaire" filter data -- archived cards, separate arrays (not
    # merged into ai_images/ai_videos with a flag) so the normal tab's
    # total/posted counts never need to account for a mixed state.
    ai_image_archived_entries = scan_archived_assets(AI_MODEL_IMAGES_FOLDER, "ai-model-images", ".jpg", "ai-model")
    ai_image_archived_entries.sort(key=lambda e: e["modified"], reverse=True)
    ai_video_archived_entries = scan_archived_assets(AI_MODEL_VIDEOS_FOLDER, "ai-model-videos", ".mp4", "ai-model-video")
    ai_video_archived_entries.sort(key=lambda e: e["modified"], reverse=True)

    # Pinterest: article-tied and standalone text pins are no longer scanned
    # (Arnaud asked to keep only the 3 collage templates going forward,
    # 2026-07-23) — only one example article pin was kept on disk manually,
    # so it still appears here, but no new ones will show up unless
    # cloudinary-pinterest-image-youm / pinterest-text-pin-youm run again.
    pin_entries = (
        scan_pinterest_article_pins()
        + scan_pinterest_text_pins()
        + scan_pinterest_product_collage_pins()
        + scan_pinterest_compact_collage_pins()
        + scan_pinterest_lifestyle_collage_pins()
        + scan_pinterest_pairs_collage_pins()
    )
    pin_entries.sort(key=lambda e: e["created"])

    payload = {
        "generated": datetime.now().isoformat(),
        "posts": instagram_entries,
        "ai_images": ai_image_entries,
        "ai_videos": ai_video_entries,
        "ai_images_archived": ai_image_archived_entries,
        "ai_videos_archived": ai_video_archived_entries,
        "pinterest_pins": pin_entries,
    }

    os.makedirs(YOUM_FOLDER, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        f.write("window.__MANIFEST__ = ")
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write(";\n")

    print(f"Wrote {len(instagram_entries)} Instagram post(s) to {MANIFEST_PATH}")
    for e in instagram_entries:
        print(f"  - [{e['type']}] {e['filename']}  ({e['created'][:10]})")
    print(f"Wrote {len(ai_image_entries)} AI image(s).")
    for e in ai_image_entries:
        print(f"  - [{e['type']}] {e['filename']}  ({e['created'][:10]})")
    print(f"Wrote {len(ai_video_entries)} AI video(s).")
    for e in ai_video_entries:
        print(f"  - [{e['type']}] {e['filename']}  ({e['created'][:10]})")
    print(f"Wrote {len(ai_image_archived_entries)} archived AI image(s) and {len(ai_video_archived_entries)} archived AI video(s) (À refaire filter).")
    print(f"Wrote {len(pin_entries)} scanned Pinterest pin(s) (collage templates; article/text kept only as manual leftovers on disk).")
    for e in pin_entries:
        print(f"  - [{e['source_type']}] {e['id']}  ({e['created'][:10]})")
    print("Manually-added Pinterest pins (via '+ Ajouter un pin') still live only in the dashboard's localStorage and are not written here.")

    if args.open:
        webbrowser.open(f"file:///{CONTROL_PANEL_PATH.replace(os.sep, '/')}")


if __name__ == "__main__":
    main()
