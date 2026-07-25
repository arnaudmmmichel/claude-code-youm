# Youm Paris — Content Control Panel

Client-facing dashboard for Youm Paris's content pipeline: Overview, Instagram, AI Image, AI Vidéo, Pinterest, and SEO tabs — deployed as a static site with two Netlify Functions handling write-back to Google Sheets (validation clicks, "Validé"/"À refaire" status).

Deployed at: https://youm-control-panel.netlify.app

## Structure
- `output/youm_paris/` — the deployed site (Netlify `publish` directory). `control-panel.html` / `overview.html` are the dashboard pages; everything else is generated content (blog articles, AI images/videos, Pinterest pins) plus `manifest.js` / `seo-manifest.js` (regenerated at build time).
- `netlify/functions/` — `validate.ts` (SEO tab's "Valider") and `update-status.ts` (AI Image/Vidéo "Validé"/"À refaire"), both writing to Google Sheets via a service account and triggering a rebuild afterward so every dashboard view stays in sync automatically.
- `.claude/skills/.../scripts/` — the two Python build-time scripts (`generate_manifest.py`, `generate_seo_manifest.py`) that Netlify's build command runs to regenerate the manifest files from the current state of the Google Sheets + blog HTML.

## Required Netlify environment variables
- `GOOGLE_SERVICE_ACCOUNT_B64` — base64-encoded service account JSON key (Editor access on both target Sheets)
- `BLOG_IDEAS_SHEET_YOUM_PARIS` — Google Sheet URL
- `NETLIFY_BUILD_HOOK_URL` — this site's own build hook, used by the Functions to trigger a rebuild after a write
- `PYTHON_VERSION` — set via `netlify.toml`

## Full architecture notes
See the main project repo's `.claude/skills/youm-seo-control-panel/NETLIFY_DEPLOYMENT.md` for the complete design rationale (why Netlify Functions needed a Node port, service-account auth setup, build-hook-triggered rebuilds, loading-state UX).

This repo is intentionally scoped to only what Netlify needs to build and serve the dashboard — it is a deployment mirror, not the source-of-truth working repo for Youm Paris's broader marketing operations.
