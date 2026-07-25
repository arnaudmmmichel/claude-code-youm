/**
 * POST /api/restore-asset
 *   { media_path: string, source_json_path?: string, product_url?: string }
 *
 * Reverses delete-asset.ts's archive action -- moves the media file (and
 * its .source.json sidecar, if given) from output/youm_paris/_archive/
 * back to their original location, and clears the "images IA" sheet's
 * status back to "en attente" (not a re-validation event, so this does
 * NOT stamp the Image/Video validé date columns -- see
 * writeImagesIaStatus()'s en_attente branch).
 *
 * Deliberately does NOT regenerate the .html detail page that
 * delete-asset.ts hard-deleted -- that page's real template lives in
 * Python's youm-ai-model-image/scripts/generate_model_image.py, and
 * duplicating it here would create a second copy to keep in sync
 * manually. A restored card is fully usable (image/video, title,
 * product link) but has no "Ouvrir" detail-page link until the next
 * full content-generation run touches it -- same as any card that never
 * had one. Documented as a deliberate simplification, not a bug.
 *
 * Paths are relative to output/youm_paris/, same convention as
 * delete-asset.ts. Triggers the build hook so the restored card
 * reappears in its normal tab (and disappears from the "À refaire"
 * filter) automatically, no manual step.
 */

import type { Handler } from "@netlify/functions";
import { moveRepoFile, triggerRebuild } from "./_lib/sheets-client";
import { writeImagesIaStatus } from "./update-status";

const OUTPUT_ROOT = "output/youm_paris";

export const handler: Handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ ok: false, error: "Method not allowed" }) };
  }

  let body: { media_path?: string; source_json_path?: string; product_url?: string };
  try {
    body = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "Invalid JSON body" }) };
  }

  const { media_path, source_json_path, product_url } = body;
  if (!media_path) {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "media_path is required" }) };
  }

  try {
    const restored = await moveRepoFile(
      `${OUTPUT_ROOT}/_archive/${media_path}`,
      `${OUTPUT_ROOT}/${media_path}`,
      `Restore ${media_path}`
    );

    let sourceJsonRestored = false;
    if (source_json_path) {
      sourceJsonRestored = await moveRepoFile(
        `${OUTPUT_ROOT}/_archive/${source_json_path}`,
        `${OUTPUT_ROOT}/${source_json_path}`,
        `Restore ${source_json_path}`
      );
    }

    let sheetRowNumber: number | null = null;
    if (product_url) {
      sheetRowNumber = await writeImagesIaStatus(product_url, "en_attente");
    }

    await triggerRebuild();

    return {
      statusCode: 200,
      body: JSON.stringify({
        ok: true,
        restored,
        source_json_restored: sourceJsonRestored,
        sheet_matched: sheetRowNumber !== null,
        sheet_row_number: sheetRowNumber,
      }),
    };
  } catch (e) {
    console.error("restore-asset.ts error:", e);
    return { statusCode: 500, body: JSON.stringify({ ok: false, error: `Unexpected error: ${(e as Error).message}` }) };
  }
};
