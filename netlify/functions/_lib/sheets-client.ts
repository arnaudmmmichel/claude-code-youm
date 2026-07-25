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
/** Converts a 1-indexed column number to its spreadsheet letter(s) --
 * A=1 ... Z=26, AA=27, AB=28, etc. Confirmed broken for col>26 2026-07-25:
 * the previous single-letter-only formula (String.fromCharCode(64+col))
 * produced a non-letter character for column 27 ("[") when the "Video
 * validé date" column was added at that position, causing every write to
 * it to fail with a range-parse error from the Sheets API. */
function columnLetter(col: number): string {
  let result = "";
  let n = col;
  while (n > 0) {
    const remainder = (n - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
}

export async function updateCell(sheetId: string, tabName: string, row: number, col: number, value: string): Promise<void> {
  const colLetter = columnLetter(col);
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
  const lastCol = columnLetter(header.length);
  const range = encodeURIComponent(`'${tabName}'!A1:${lastCol}1`);
  await authedFetch(`${SHEETS_API_BASE}/${sheetId}/values/${range}?valueInputOption=USER_ENTERED`, {
    method: "PUT",
    body: JSON.stringify({ values: [header] }),
  });
}

export function nowIso(): string {
  return new Date().toISOString();
}

// ── GITHUB CONTENTS API ──
// Used by delete-asset.ts to archive/delete files in the deploy repo --
// Netlify's published output isn't a writable filesystem, so the only way
// to make a file disappear from (or reappear in) the site is to change it
// in the GitHub repo and let the existing build-hook-triggered rebuild
// pick that up. Uses a fine-grained PAT (GITHUB_PAT env var) scoped to
// ONLY this repo with Contents: Read and write -- see NETLIFY_DEPLOYMENT.md
// for the one-time token setup. Plain REST, no npm dependency needed.

const GITHUB_API_BASE = "https://api.github.com";
const GITHUB_REPO = "arnaudmmmichel/claude-code-youm";

function requireGithubToken(): string {
  const token = process.env.GITHUB_PAT;
  if (!token) throw new Error("GITHUB_PAT is not set -- see NETLIFY_DEPLOYMENT.md for setup.");
  return token;
}

async function githubFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = requireGithubToken();
  return fetch(`${GITHUB_API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.headers || {}),
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
}

export interface GithubFile {
  sha: string;
  contentBase64: string;
}

/** Fetches a file's current content + blob sha, both required to update or
 * delete it via the Contents API. Returns null (not an error) if the file
 * doesn't exist -- callers should treat a missing file as "nothing to do"
 * rather than fail the whole operation over an already-absent sidecar.
 *
 * CRITICAL: the Contents API's GET /contents/{path} endpoint only returns
 * file content inline for files <=1MB -- for larger files `content` is
 * absent/empty (GitHub's docs call this out, and it was confirmed the hard
 * way 2026-07-25: every video and most images in this repo are >1MB, and
 * an earlier version of this function silently wrote an empty string as
 * "content", corrupting the archived file to 0 bytes with no error at any
 * step). The Git Data API's GET /git/blobs/{sha} endpoint has no such
 * limit, so this always fetches the sha via Contents API (cheap, metadata
 * only) then the actual bytes via the Blobs API. */
export async function getRepoFile(path: string): Promise<GithubFile | null> {
  const metaResp = await githubFetch(`/repos/${GITHUB_REPO}/contents/${path}`);
  if (metaResp.status === 404) return null;
  if (!metaResp.ok) throw new Error(`GitHub GET contents ${metaResp.status}: ${await metaResp.text()}`);
  const meta = (await metaResp.json()) as { sha: string };

  const blobResp = await githubFetch(`/repos/${GITHUB_REPO}/git/blobs/${meta.sha}`);
  if (!blobResp.ok) throw new Error(`GitHub GET blob ${blobResp.status}: ${await blobResp.text()}`);
  const blob = (await blobResp.json()) as { sha: string; content: string; encoding: string };
  if (blob.encoding !== "base64") {
    throw new Error(`Unexpected blob encoding for ${path}: ${blob.encoding}`);
  }
  // GitHub returns content base64-encoded with embedded newlines -- strip
  // them so callers get a clean base64 string usable directly in a PUT body.
  return { sha: blob.sha, contentBase64: blob.content.replace(/\n/g, "") };
}

/** Creates or updates a file at `path` with the given base64 content.
 * Pass the sha from getRepoFile() when overwriting an existing file (the
 * Contents API requires it as a conflict guard); omit it when creating a
 * new file (e.g. the archive copy, which shouldn't already exist). */
export async function putRepoFile(path: string, contentBase64: string, message: string, sha?: string): Promise<void> {
  const resp = await githubFetch(`/repos/${GITHUB_REPO}/contents/${path}`, {
    method: "PUT",
    body: JSON.stringify({ message, content: contentBase64, ...(sha ? { sha } : {}) }),
  });
  if (!resp.ok) throw new Error(`GitHub PUT contents ${resp.status}: ${await resp.text()}`);
}

/** Deletes a file at `path`. Requires its current sha (from getRepoFile()). */
export async function deleteRepoFile(path: string, sha: string, message: string): Promise<void> {
  const resp = await githubFetch(`/repos/${GITHUB_REPO}/contents/${path}`, {
    method: "DELETE",
    body: JSON.stringify({ message, sha }),
  });
  if (!resp.ok) throw new Error(`GitHub DELETE contents ${resp.status}: ${await resp.text()}`);
}

/** Moves a file by copying its content to `destPath` (create, no sha) then
 * deleting the original -- GitHub's Contents API has no native "move".
 * Two sequential commits; acceptable for a low-frequency, single-user
 * action like this. No-ops (returns false) if the source file doesn't
 * exist. Returns true if the move completed. */
export async function moveRepoFile(sourcePath: string, destPath: string, message: string): Promise<boolean> {
  const file = await getRepoFile(sourcePath);
  if (!file) return false;
  await putRepoFile(destPath, file.contentBase64, message);
  await deleteRepoFile(sourcePath, file.sha, message);
  return true;
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
