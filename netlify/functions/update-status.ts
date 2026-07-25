/**
 * POST /api/update-status  { product_url: string, status: "valide"|"a_refaire" }
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
 * After a successful write, fires the Netlify Build Hook so the whole site
 * rebuilds and every dashboard view reflects the change automatically.
 */

import type { Handler } from "@netlify/functions";
import { getAllValues, updateCell, triggerRebuild } from "./_lib/sheets-client";

export const IMAGES_IA_SHEET_ID = "1r7co4OkM0Di5PJWVnVhETOikx0VhW8e-VZwI96OQ-H0";
export const IMAGES_IA_SHEET_TAB = "images IA";
const COL_URL = 2; // 1-indexed column B
const COL_STATUS = 3; // 1-indexed column C

export const STATUS_MAP: Record<string, string> = {
  valide: "validé",
  a_refaire: "à refaire",
};

export function normalizeUrl(url: string): string {
  return url.trim().split("?")[0].replace(/\/+$/, "");
}

/** Shared with delete-asset.ts, which also needs to write "à refaire" to
 * this same sheet as part of its combined archive+sheet-write action --
 * exported so that logic lives in exactly one place. Returns the matched
 * row number, or null if no row's product_url matched. */
export async function writeImagesIaStatus(productUrl: string, statusKey: string): Promise<number | null> {
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
      return rowNumber;
    }
  }
  return null;
}

export const handler: Handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ ok: false, error: "Method not allowed" }) };
  }

  let body: { product_url?: string; status?: string };
  try {
    body = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "Invalid JSON body" }) };
  }

  const { product_url, status } = body;
  if (!product_url || !status) {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "product_url and status are required" }) };
  }
  if (!(status in STATUS_MAP)) {
    return {
      statusCode: 400,
      body: JSON.stringify({ ok: false, error: `Unknown status: ${status} -- expected one of ${Object.keys(STATUS_MAP).join(", ")}` }),
    };
  }

  try {
    const rowNumber = await writeImagesIaStatus(product_url, status);
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
