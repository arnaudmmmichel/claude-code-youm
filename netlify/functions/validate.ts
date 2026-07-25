/**
 * POST /api/validate  { type: "keyword"|"article"|"site_finding", id, label }
 *
 * Ports .claude/skills/youm-seo-control-panel/scripts/validate_item.py's
 * update_validation() to a Netlify Function. Same matching rule: `label`
 * (the human-readable display text, not the manifest's slug-derived `id`)
 * is matched case-insensitively against column A of the "keywords" tab
 * (for type=keyword) or the "seo findings" tab (for type=article|
 * site_finding), then writes "Oui" + a timestamp into that row's
 * "Client validated"/"Validated at" columns.
 *
 * After a successful write, fires the Netlify Build Hook so the whole site
 * rebuilds (re-scanning blog HTML + re-reading every sheet tab) -- this is
 * what makes the client's click propagate to the Overview/SEO tabs
 * automatically, without Arnaud re-running a script by hand.
 */

import type { Handler } from "@netlify/functions";
import { requireSheetId, getAllValues, updateCell, ensureTabExists, nowIso, triggerRebuild } from "./_lib/sheets-client";

const KEYWORDS_TAB = "keywords";
const FINDINGS_TAB = "seo findings";
const KEYWORDS_HEADER = [
  "Keyword", "Avg. monthly searches", "Competition",
  "Already targeted", "Target page URL",
  "Client validated", "Validated at",
];
const FINDINGS_HEADER = ["Item", "Category", "Status", "Client validated", "Validated at"];

const VALID_TYPES = new Set(["keyword", "article", "site_finding"]);

export const handler: Handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: JSON.stringify({ ok: false, error: "Method not allowed" }) };
  }

  let body: { type?: string; id?: string; label?: string };
  try {
    body = JSON.parse(event.body || "{}");
  } catch {
    return { statusCode: 400, body: JSON.stringify({ ok: false, error: "Invalid JSON body" }) };
  }

  const { type, id, label } = body;
  if (!type || !VALID_TYPES.has(type) || !id || !label || !label.trim()) {
    return {
      statusCode: 400,
      body: JSON.stringify({ ok: false, error: `type (one of ${[...VALID_TYPES].join(", ")}), id, and label are required` }),
    };
  }

  try {
    const sheetId = requireSheetId();
    const tabName = type === "keyword" ? KEYWORDS_TAB : FINDINGS_TAB;
    const header = type === "keyword" ? KEYWORDS_HEADER : FINDINGS_HEADER;
    await ensureTabExists(sheetId, tabName, header);

    const validatedCol = header.indexOf("Client validated") + 1;
    const validatedAtCol = header.indexOf("Validated at") + 1;

    const rows = await getAllValues(sheetId, tabName);
    const target = label.trim().toLowerCase();

    for (let i = 1; i < rows.length; i++) {
      const row = rows[i];
      if (row && row[0] && row[0].trim().toLowerCase() === target) {
        const rowNumber = i + 1; // 1-indexed, header is row 1
        await updateCell(sheetId, tabName, rowNumber, validatedCol, "Oui");
        await updateCell(sheetId, tabName, rowNumber, validatedAtCol, nowIso());
        await triggerRebuild();
        return { statusCode: 200, body: JSON.stringify({ ok: true, matched: true, row_number: rowNumber }) };
      }
    }

    return { statusCode: 200, body: JSON.stringify({ ok: true, matched: false, item_id: id }) };
  } catch (e) {
    console.error("validate.ts error:", e);
    return { statusCode: 500, body: JSON.stringify({ ok: false, error: `Unexpected error: ${(e as Error).message}` }) };
  }
};
