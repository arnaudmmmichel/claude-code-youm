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

const SHEET_ID = "1r7co4OkM0Di5PJWVnVhETOikx0VhW8e-VZwI96OQ-H0";
const SHEET_TAB = "images IA";
const COL_URL = 2; // 1-indexed column B
const COL_STATUS = 3; // 1-indexed column C

const STATUS_MAP: Record<string, string> = {
  valide: "validé",
  a_refaire: "à refaire",
};

function normalizeUrl(url: string): string {
  return url.trim().split("?")[0].replace(/\/+$/, "");
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
    const sheetValue = STATUS_MAP[status];
    const target = normalizeUrl(product_url);

    const rows = await getAllValues(SHEET_ID, SHEET_TAB);
    for (let i = 1; i < rows.length; i++) {
      const row = rows[i];
      if (row && row.length > COL_URL - 1 && normalizeUrl(row[COL_URL - 1] || "") === target) {
        const rowNumber = i + 1;
        await updateCell(SHEET_ID, SHEET_TAB, rowNumber, COL_STATUS, sheetValue);
        await triggerRebuild();
        return { statusCode: 200, body: JSON.stringify({ ok: true, matched: true, row_number: rowNumber }) };
      }
    }

    return { statusCode: 200, body: JSON.stringify({ ok: true, matched: false }) };
  } catch (e) {
    console.error("update-status.ts error:", e);
    return { statusCode: 500, body: JSON.stringify({ ok: false, error: `Unexpected error: ${(e as Error).message}` }) };
  }
};
