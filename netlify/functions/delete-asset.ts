/**
 * POST /api/delete-asset
 *   { media_path: string, sidecar_paths: string[], product_url?: string }
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
 *   - sidecar_paths (the .html detail page + .source.json, typically 2
 *     entries) are HARD-DELETED -- cheap to regenerate, not worth archiving.
 *   - Any path that doesn't exist (404 from GitHub) is skipped, not an
 *     error -- e.g. a card with no detail page still deletes cleanly.
 *   - If product_url is given, also writes "à refaire" into the "images
 *     IA" sheet (reusing update-status.ts's writeImagesIaStatus(), not a
 *     second round-trip from the client).
 *   - Triggers the build hook once at the end, after all file operations
 *     and the sheet write succeed -- the resulting rebuild's manifest scan
 *     excludes _archive/ (see generate_manifest.py) and any card missing
 *     its .html/.source.json, so the card disappears from the dashboard
 *     with no manual step.
 */

import type { Handler } from "@netlify/functions";
import { moveRepoFile, getRepoFile, deleteRepoFile, triggerRebuild } from "./_lib/sheets-client";
import { writeImagesIaStatus } from "./update-status";

const OUTPUT_ROOT = "output/youm_paris";

export const handler: Handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ ok: false, error: "Method not allowed" }) };
  }

  let body: { media_path?: string; sidecar_paths?: string[]; product_url?: string };
  try {
    body = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "Invalid JSON body" }) };
  }

  const { media_path, sidecar_paths, product_url } = body;
  if (!media_path) {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "media_path is required" }) };
  }

  try {
    const archived = await moveRepoFile(
      `${OUTPUT_ROOT}/${media_path}`,
      `${OUTPUT_ROOT}/_archive/${media_path}`,
      `Archive ${media_path} (à refaire)`
    );

    const deletedSidecars: string[] = [];
    for (const sidecarPath of sidecar_paths || []) {
      const file = await getRepoFile(`${OUTPUT_ROOT}/${sidecarPath}`);
      if (!file) continue; // already absent -- not an error, nothing to do
      await deleteRepoFile(`${OUTPUT_ROOT}/${sidecarPath}`, file.sha, `Delete ${sidecarPath} (à refaire)`);
      deletedSidecars.push(sidecarPath);
    }

    let sheetRowNumber: number | null = null;
    if (product_url) {
      sheetRowNumber = await writeImagesIaStatus(product_url, "a_refaire");
    }

    await triggerRebuild();

    return {
      statusCode: 200,
      body: JSON.stringify({
        ok: true,
        archived,
        deleted_sidecars: deletedSidecars,
        sheet_matched: sheetRowNumber !== null,
        sheet_row_number: sheetRowNumber,
      }),
    };
  } catch (e) {
    console.error("delete-asset.ts error:", e);
    return { statusCode: 500, body: JSON.stringify({ ok: false, error: `Unexpected error: ${(e as Error).message}` }) };
  }
};
