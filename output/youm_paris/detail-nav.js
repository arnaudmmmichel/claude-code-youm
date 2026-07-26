// Shared Précédent/Suivant navigation for every content-card detail page
// (ai-model-images, ai-model-videos, pinterest/cloudinary-images,
// pinterest/text-pins, instagram/cloudinary-images). Each detail page
// already defines CARD_ID (its own manifest key) and loads this file next
// to its "back-link" — this script finds CARD_ID's position within its own
// tab's manifest array (same order the dashboard renders) and injects
// Précédent/Suivant links so Arnaud never has to bounce back to the
// control panel just to move to the next card.
//
// Depends on window.__MANIFEST__ already being set (detail pages must load
// manifest.js before this file) and on a global CARD_ID being defined
// before this runs. The back-link's own href (already on every page, e.g.
// "../control-panel.html" or "../../control-panel.html") is read directly
// at init time to work out how many levels to walk up — no second global
// needed per page.

(function () {
  function cardKey(entry, tabKey) {
    return tabKey === 'pinterest_pins' ? entry.id : entry.filename;
  }

  function findCurrentAndNeighbors() {
    const manifest = window.__MANIFEST__;
    if (!manifest || typeof CARD_ID === 'undefined') return null;

    const tabs = ['posts', 'ai_images', 'ai_videos', 'pinterest_pins'];
    for (const tabKey of tabs) {
      const list = manifest[tabKey] || [];
      const index = list.findIndex((e) => cardKey(e, tabKey) === CARD_ID);
      if (index !== -1) {
        return {
          prev: index > 0 ? list[index - 1] : null,
          next: index < list.length - 1 ? list[index + 1] : null,
          tabKey,
        };
      }
    }
    return null;
  }

  function hrefFor(entry, tabKey, upLevels) {
    // Prefer each entry's own detail_page (the .html this same navigation
    // lives on for every neighbor) — falls back to the raw media file only
    // for the rare entry with no detail page generated. Both paths are
    // stored relative to output/youm_paris/ (manifest.js's own location,
    // same folder the back-link's "../.../control-panel.html" points at),
    // so re-rooting them relative to THIS page just needs the same
    // up-levels count the back-link already encodes.
    const path = entry.detail_page || entry.filename;
    return '../'.repeat(upLevels) + path;
  }

  function init() {
    const backLink = document.querySelector('.back-link');
    if (!backLink) return;
    const result = findCurrentAndNeighbors();
    if (!result) return;
    // Count "../" segments in the back-link's own href (e.g.
    // "../control-panel.html" -> 1, "../../control-panel.html" -> 2) to
    // know how deep this detail page sits below output/youm_paris/.
    const upLevels = (backLink.getAttribute('href').match(/\.\.\//g) || []).length;

    const nav = document.createElement('div');
    nav.className = 'detail-nav';
    nav.style.cssText = 'display:flex; gap:10px; align-self:flex-start; margin-bottom:20px;';

    function makeLink(entry, label, upLevels) {
      if (!entry) {
        const span = document.createElement('span');
        span.textContent = label;
        span.style.cssText = 'font-size:13px; font-weight:500; color:var(--muted,#7a6c5c); opacity:0.4; padding:8px 14px; border:1px solid var(--border,#392f26); border-radius:6px;';
        return span;
      }
      const a = document.createElement('a');
      a.href = hrefFor(entry, result.tabKey, upLevels);
      a.textContent = label;
      a.title = entry.title || '';
      a.style.cssText = 'font-size:13px; font-weight:500; color:var(--muted,#b8a999); text-decoration:none; padding:8px 14px; border:1px solid var(--border,#3a332c); border-radius:6px; background:var(--cream,#241f1a);';
      a.addEventListener('mouseenter', () => { a.style.borderColor = 'var(--accent,#f54e00)'; a.style.color = 'var(--accent,#f54e00)'; });
      a.addEventListener('mouseleave', () => { a.style.borderColor = 'var(--border,#3a332c)'; a.style.color = 'var(--muted,#b8a999)'; });
      return a;
    }

    nav.appendChild(makeLink(result.prev, '← Précédent', upLevels));
    nav.appendChild(makeLink(result.next, 'Suivant →', upLevels));

    backLink.insertAdjacentElement('afterend', nav);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
