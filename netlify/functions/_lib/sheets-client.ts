/**
 * Shared Google Sheets access for the two write-back Functions
 * (validate.ts, update-status.ts). Mirrors the Python
 * .claude/skills/youm-seo-control-panel/scripts/sheet_client.py helper,
 * but auth here is service-account ONLY -- Functions have no browser to
 * complete an interactive OAuth consent screen and no persistent disk to
 * cache a token across invocations, unlike the local Python scripts which
 * still support that flow for Arnaud's manual runs.
 *
 * The service account JSON key is stored as a single base64-encoded env
 * var (GOOGLE_SERVICE_ACCOUNT_B64) rather than separate client_email/
 * private_key vars, specifically to avoid the private-key-newline-escaping
 * class of bugs that Netlify env vars are prone to (confirmed via Netlify
 * forum reports during Netlify-migration research, 2026-07-25). The
 * service account must be shared as Editor on the target Google Sheet --
 * see SKILL.md for the one-time setup steps.
 */

import { GoogleAuth } from "google-auth-library";

const SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets";
const SCOPES = ["https://www.googleapis.com/auth/spreadsheets"];

let cachedAuth: GoogleAuth | null = null;

function getAuth(): GoogleAuth {
  if (cachedAuth) return cachedAuth;

  const b64Key = process.env.GOOGLE_SERVICE_ACCOUNT_B64;
  if (!b64Key) {
    throw new Error("GOOGLE_SERVICE_ACCOUNT_B64 is not set -- see SKILL.md for service account setup.");
  }
  const credentials = JSON.parse(Buffer.from(b64Key, "base64").toString("utf-8"));
  cachedAuth = new GoogleAuth({ credentials, scopes: SCOPES });
  return cachedAuth;
}

async function authedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const auth = getAuth();
  const client = await auth.getClient();
  const token = await client.getAccessToken();
  const resp = await fetch(url, {
    ...init,
    headers: {
      ...(init.headers || {}),
      Authorization: `Bearer ${token.token}`,
      "Content-Type": "application/json",
    },
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Sheets API ${resp.status}: ${body}`);
  }
  return resp;
}

export function extractSheetId(url: string): string {
  if (url.includes("/d/")) {
    return url.split("/d/")[1].split("/")[0];
  }
  return url;
}

export function requireSheetId(): string {
  const url = process.env.BLOG_IDEAS_SHEET_YOUM_PARIS;
  if (!url) throw new Error("BLOG_IDEAS_SHEET_YOUM_PARIS is not set.");
  return extractSheetId(url);
}

/** Reads every row (including header) of a tab as string[][], same shape
 * gspread's get_all_values() returns. Empty array if the tab is empty. */
export async function getAllValues(sheetId: string, tabName: string): Promise<string[][]> {
  const range = encodeURIComponent(`'${tabName}'`);
  const resp = await authedFetch(`${SHEETS_API_BASE}/${sheetId}/values/${range}`);
  const data = (await resp.json()) as { values?: string[][] };
  return data.values || [];
}

/** Writes a single cell, 1-indexed row/col -- same convention as gspread's
 * update_cell(row, col, value) used by the Python scripts this ports. */
export async function updateCell(sheetId: string, tabName: string, row: number, col: number, value: string): Promise<void> {
  const colLetter = String.fromCharCode(64 + col);
  const range = encodeURIComponent(`'${tabName}'!${colLetter}${row}`);
  await authedFetch(`${SHEETS_API_BASE}/${sheetId}/values/${range}?valueInputOption=USER_ENTERED`, {
    method: "PUT",
    body: JSON.stringify({ values: [[value]] }),
  });
}

/** Ensures a tab exists with the given header row, creating it if missing
 * -- mirrors sheet_client.py's get_or_create_tab(). Does not touch an
 * existing tab's header (the Python build-time scripts own header
 * migration; Functions only need the tab to exist so a write has
 * somewhere to land). */
export async function ensureTabExists(sheetId: string, tabName: string, header: string[]): Promise<void> {
  const rows = await getAllValues(sheetId, tabName).catch(() => null);
  if (rows !== null) return; // tab already exists (even if empty, the range fetch succeeds)

  await authedFetch(`${SHEETS_API_BASE}/${sheetId}:batchUpdate`, {
    method: "POST",
    body: JSON.stringify({ requests: [{ addSheet: { properties: { title: tabName } } }] }),
  });
  const lastCol = String.fromCharCode(64 + header.length);
  const range = encodeURIComponent(`'${tabName}'!A1:${lastCol}1`);
  await authedFetch(`${SHEETS_API_BASE}/${sheetId}/values/${range}?valueInputOption=USER_ENTERED`, {
    method: "PUT",
    body: JSON.stringify({ values: [header] }),
  });
}

export function nowIso(): string {
  return new Date().toISOString();
}

/** Fire-and-forget trigger of the Netlify Build Hook so the site rebuilds
 * (re-scanning blog HTML + re-reading all sheet tabs) after a write --
 * this is what makes a validate/status click propagate to every dashboard
 * view automatically, without Arnaud manually re-running a script.
 * Errors are logged, not thrown -- a failed rebuild trigger shouldn't turn
 * an otherwise-successful Sheet write into a 500 for the client. */
export async function triggerRebuild(): Promise<void> {
  const hookUrl = process.env.NETLIFY_BUILD_HOOK_URL;
  if (!hookUrl) {
    console.warn("NETLIFY_BUILD_HOOK_URL not set -- skipping rebuild trigger. The Sheet was still updated.");
    return;
  }
  try {
    await fetch(hookUrl, { method: "POST" });
  } catch (e) {
    console.error("Failed to trigger Netlify build hook:", e);
  }
}
