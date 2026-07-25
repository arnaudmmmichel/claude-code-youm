/**
 * POST /api/delete-asset
 *   { media_path: string, source_json_path?: string, html_path?: string, product_url?: string }
 *
 * Fully-automated replacement for the AI Image/AI Vidéo tabs' old
 * "À refaire" flow, which used to show a copy-pasteable `rm` command for
 * Arnaud to run manually -- a leftover from the panel's original
 * local-only design that broke the "every click propagates automatically,
 * no manual step" requirement once the panel moved to Netlify.
 *
 * Netlify's deployed output isn't a writable filesystem, so the only way
 * to make a file disappear from (or reappear in) the site is to change it
 * in the GitHub repo and let the build-hook-triggered rebuild pick that
 * up -- same pattern as validate.ts/update-status.ts, just acting on
 * GitHub's Contents API instead of (in addition to) Google Sheets.
 *
 * Paths are all relative to output/youm_paris/ (e.g.
 * "ai-model-images/foo.jpg"), matching the manifest's own `filename` shape.
 *
 * Behavior:
 *   - media_path is ARCHIVED (moved to output/youm_paris/_archive/<path>),
 *     not hard-deleted -- Arnaud asked to keep a real backup of the actual
 *     image/video, not just a text record, in case a click was a mistake.
 *   - source_json_path is ALSO ARCHIVED (moved alongside the media file)
 *     as of 2026-07-25 -- previously hard-deleted, but that made the "À
 *     refaire" filter view impossible to build meaningfully (no title/
 *     product link survived for an archived card). The sidecar is small,
 *     cheap to keep, and is exactly the metadata restore-asset.ts and the
 *     manifest's archived-item scan need.
 *   - html_path (the detail page) is still HARD-DELETED -- it's a
 *     regenerable webpage, not data; keeping it out of _archive/ avoids
 *     ever serving a stale detail page for an archived card. Restoring an
 *     item does NOT regenerate it (see restore-asset.ts).
 *   - Any path that doesn't exist (404 from GitHub) is skipped, not an
 *     error -- e.g. a card with no detail page still deletes cleanly.
 *   - If product_url is given, also writes "à refaire" into the "images
 *     IA" sheet (reusing update-status.ts's writeImagesIaStatus(), not a
 *     second round-trip from the client).
 *   - Triggers the build hook once at the end, after all file operations
 *     and the sheet write succeed -- the resulting rebuild's manifest scan
 *     picks up the archived pair under _archive/ (see generate_manifest.py's
 *     scan_archived_assets()) so the "À refaire" filter shows it, while it
 *     disappears from the normal tab view with no manual step.
 */

import type { Handler } from "@netlify/functions";
import { moveRepoFile, getRepoFile, deleteRepoFile, triggerRebuild } from "./_lib/sheets-client";
import { writeImagesIaStatus } from "./update-status";

const OUTPUT_ROOT = "output/youm_paris";
const VIDEO_EXTENSIONS = [".mp4"];

/** Derived from the file extension rather than a separate client-sent
 * field -- one less thing for the caller to get wrong, and the extension
 * is already an unambiguous source of truth for image vs video. */
function assetTypeFromPath(path: string): "image" | "video" {
  return VIDEO_EXTENSIONS.some(ext => path.toLowerCase().endsWith(ext)) ? "video" : "image";
}

export const handler: Handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ ok: false, error: "Method not allowed" }) };
  }

  let body: { media_path?: string; source_json_path?: string; html_path?: string; product_url?: string };
  try {
    body = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "Invalid JSON body" }) };
  }

  const { media_path, source_json_path, html_path, product_url } = body;
  if (!media_path) {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "media_path is required" }) };
  }

  try {
    const archived = await moveRepoFile(
      `${OUTPUT_ROOT}/${media_path}`,
      `${OUTPUT_ROOT}/_archive/${media_path}`,
      `Archive ${media_path} (à refaire)`
    );

    let sourceJsonArchived = false;
    if (source_json_path) {
      sourceJsonArchived = await moveRepoFile(
        `${OUTPUT_ROOT}/${source_json_path}`,
        `${OUTPUT_ROOT}/_archive/${source_json_path}`,
        `Archive ${source_json_path} (à refaire)`
      );
    }

    let htmlDeleted = false;
    if (html_path) {
      const file = await getRepoFile(`${OUTPUT_ROOT}/${html_path}`);
      if (file) {
        await deleteRepoFile(`${OUTPUT_ROOT}/${html_path}`, file.sha, `Delete ${html_path} (à refaire)`);
        htmlDeleted = true;
      }
    }

    let sheetRowNumber: number | null = null;
    if (product_url) {
      sheetRowNumber = await writeImagesIaStatus(product_url, "a_refaire", assetTypeFromPath(media_path));
    }

    await triggerRebuild();

    return {
      statusCode: 200,
      body: JSON.stringify({
        ok: true,
        archived,
        source_json_archived: sourceJsonArchived,
        html_deleted: htmlDeleted,
        sheet_matched: sheetRowNumber !== null,
        sheet_row_number: sheetRowNumber,
      }),
    };
  } catch (e) {
    console.error("delete-asset.ts error:", e);
    return { statusCode: 500, body: JSON.stringify({ ok: false, error: `Unexpected error: ${(e as Error).message}` }) };
  }
};
