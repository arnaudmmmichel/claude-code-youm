/**
 * POST /api/update-status  { product_url: string, status: "valide"|"a_refaire", asset_type?: "image"|"video" }
 *
 * Ports .claude/skills/youm-control-panel-server/scripts/sheet_status.py's
 * update_status() to a Netlify Function -- writes "validé"/"à refaire"
 * into the "images IA" Google Sheet tab (column C), matched by exact
 * product_url (trailing slash + query string stripped, same normalization
 * as the Python version). Used by the AI Image/AI Vidéo tabs' "Validé"/
 * "À refaire" actions.
 *
 * Same hardcoded SHEET_ID as the original -- this is a different
 * spreadsheet from BLOG_IDEAS_SHEET_YOUM_PARIS (the "images IA" sheet
 * youm-ai-model-image reads from), not an env var in the Python version
 * either.
 *
 * If asset_type is given, also stamps the current time into "Image
 * validé date" (col Z) or "Video validé date" (col AA) -- added
 * 2026-07-25 so Arnaud can see WHEN a card was last validated/marked à
 * refaire, not just its current status. Both actions (validé and à
 * refaire) write this timestamp; the two dedicated image/video columns
 * were appended at the END of this 25-column sheet rather than inserted
 * in the middle, since other scripts (youm-product-info-scraper,
 * youm-ai-model-video --from-sheet, Make.com) hardcode column positions
 * that would otherwise shift.
 *
 * Video logo-branding queue (added 2026-07-27): when asset_type === "video"
 * and status === "valide", this ALSO flips "Video IA" (col X) to "à
 * brander" -- a queue marker, NOT the final state. Netlify Functions have
 * no ffmpeg and no persistent filesystem, and every attempt at doing the
 * timed logo overlay purely via Cloudinary URL transformations produced
 * inconsistent/broken results across repeated testing (documented in
 * youm-ai-model-video/SKILL.md and .claude/skills/youm-ai-model-video/
 * scripts/add_logo_overlay.py's own docstring) -- so the actual branding
 * still runs locally, via `add_logo_overlay.py --from-sheet`, on whichever
 * machine Arnaud has ffmpeg available (his own PC). That script polls for
 * "à brander" rows, brands them, writes "video+logo", and flips "Video IA"
 * to "Done" -- same self-consuming-queue pattern as youm-product-info-
 * scraper's "nouveau" -> "priorité" flip. This function's job stops at
 * queuing the row; it does NOT attempt any video processing itself.
 *
 * After a successful write, fires the Netlify Build Hook so the whole site
 * rebuilds and every dashboard view reflects the change automatically.
 */

import type { Handler } from "@netlify/functions";
import { getAllValues, updateCell, nowIso, triggerRebuild } from "./_lib/sheets-client";

export const IMAGES_IA_SHEET_ID = "1r7co4OkM0Di5PJWVnVhETOikx0VhW8e-VZwI96OQ-H0";
export const IMAGES_IA_SHEET_TAB = "images IA";
const COL_URL = 2; // 1-indexed column B
const COL_STATUS = 3; // 1-indexed column C
const COL_VIDEO_IA = 24; // 1-indexed column X
const COL_IMAGE_VALIDATED_DATE = 26; // 1-indexed column Z
const COL_VIDEO_VALIDATED_DATE = 27; // 1-indexed column AA
const VIDEO_BRAND_QUEUE_STATUS = "à brander";

export const STATUS_MAP: Record<string, string> = {
  valide: "validé",
  a_refaire: "à refaire",
  // Used by restore-asset.ts when un-archiving a card -- clears the
  // status back to a neutral "not yet reviewed" state rather than
  // leaving a stale "à refaire" in the sheet after the item's been
  // restored. Deliberately does NOT stamp a validated-date column below
  // (see the assetType branch) -- "restored to pending" isn't a
  // validation event worth timestamping.
  en_attente: "",
};

export function normalizeUrl(url: string): string {
  return url.trim().split("?")[0].replace(/\/+$/, "");
}

/** Shared with delete-asset.ts, which also needs to write "à refaire" to
 * this same sheet as part of its combined archive+sheet-write action --
 * exported so that logic lives in exactly one place. Returns the matched
 * row number, or null if no row's product_url matched. */
export async function writeImagesIaStatus(productUrl: string, statusKey: string, assetType?: "image" | "video"): Promise<number | null> {
  if (!(statusKey in STATUS_MAP)) {
    throw new Error(`Unknown status: ${statusKey} -- expected one of ${Object.keys(STATUS_MAP).join(", ")}`);
  }
  const sheetValue = STATUS_MAP[statusKey];
  const target = normalizeUrl(productUrl);

  const rows = await getAllValues(IMAGES_IA_SHEET_ID, IMAGES_IA_SHEET_TAB);
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    if (row && row.length > COL_URL - 1 && normalizeUrl(row[COL_URL - 1] || "") === target) {
      const rowNumber = i + 1;
      await updateCell(IMAGES_IA_SHEET_ID, IMAGES_IA_SHEET_TAB, rowNumber, COL_STATUS, sheetValue);
      if (statusKey !== "en_attente") {
        if (assetType === "image") {
          await updateCell(IMAGES_IA_SHEET_ID, IMAGES_IA_SHEET_TAB, rowNumber, COL_IMAGE_VALIDATED_DATE, nowIso());
        } else if (assetType === "video") {
          await updateCell(IMAGES_IA_SHEET_ID, IMAGES_IA_SHEET_TAB, rowNumber, COL_VIDEO_VALIDATED_DATE, nowIso());
        }
      }
      if (assetType === "video" && statusKey === "valide") {
        await updateCell(IMAGES_IA_SHEET_ID, IMAGES_IA_SHEET_TAB, rowNumber, COL_VIDEO_IA, VIDEO_BRAND_QUEUE_STATUS);
      }
      return rowNumber;
    }
  }
  return null;
}

export const handler: Handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ ok: false, error: "Method not allowed" }) };
  }

  let body: { product_url?: string; status?: string; asset_type?: string };
  try {
    body = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "Invalid JSON body" }) };
  }

  const { product_url, status, asset_type } = body;
  if (!product_url || !status) {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "product_url and status are required" }) };
  }
  if (!(status in STATUS_MAP)) {
    return {
      statusCode: 400,
      body: JSON.stringify({ ok: false, error: `Unknown status: ${status} -- expected one of ${Object.keys(STATUS_MAP).join(", ")}` }),
    };
  }
  if (asset_type !== undefined && asset_type !== "image" && asset_type !== "video") {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: `Unknown asset_type: ${asset_type} -- expected "image" or "video"` }) };
  }

  try {
    const rowNumber = await writeImagesIaStatus(product_url, status, asset_type as "image" | "video" | undefined);
    if (rowNumber !== null) {
      await triggerRebuild();
      return { statusCode: 200, body: JSON.stringify({ ok: true, matched: true, row_number: rowNumber }) };
    }
    return { statusCode: 200, body: JSON.stringify({ ok: true, matched: false }) };
  } catch (e) {
    console.error("update-status.ts error:", e);
    return { statusCode: 500, body: JSON.stringify({ ok: false, error: `Unexpected error: ${(e as Error).message}` }) };
  }
};
