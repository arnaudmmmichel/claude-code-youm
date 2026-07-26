// Shared Validé/À refaire review widget for AI Image/Vidéo detail pages
// (ai-model-images/*.html, ai-model-videos/*.html) — mirrors the same
// pending-then-Save pattern the dashboard (control-panel.html) uses:
// clicking Validé/À refaire only stages the change locally (button state
// updates instantly) and reveals a small Enregistrer/Annuler bar; nothing
// hits the "images IA" Google Sheet (or, for À refaire, the archive/
// delete-asset call) until Enregistrer is clicked. This keeps a single
// card's review action consistent with the dashboard's batched-save
// model, and means the SAME localStorage keys
// (youm_social_control_state_v1's pendingValide/pendingRefaire/posted/
// deleted) are shared between a detail page and the dashboard grid — a
// pending mark made on one is visible on the other without a reload.
//
// Depends on globals already defined by each detail page's own inline
// <script>, before this file loads: STATE_KEY, CARD_ID, PRODUCT_URL (may be
// "" for cards with no matched sheet row), YOUM_SERVER_BASE, ASSET_TYPE
// ("image" | "video"), and a DETAIL_PAGE_PATH + SOURCE_JSON_PATH (used only
// if this card ever gets committed as "à refaire" — same fields
// delete-asset.ts expects).

(function () {
  function loadState() {
    try {
      const s = JSON.parse(localStorage.getItem(STATE_KEY)) || {};
      return {
        posted: s.posted || {}, deleted: s.deleted || {},
        pendingValide: s.pendingValide || {}, pendingRefaire: s.pendingRefaire || {},
      };
    } catch (e) {
      return { posted: {}, deleted: {}, pendingValide: {}, pendingRefaire: {} };
    }
  }
  function saveState(s) { localStorage.setItem(STATE_KEY, JSON.stringify(s)); }

  function refreshButtons() {
    const s = loadState();
    const isValide = !!(s.posted[CARD_ID] || s.pendingValide[CARD_ID]);
    const isRefaire = !!s.pendingRefaire[CARD_ID];
    document.getElementById('valideBtn').classList.toggle('active', isValide);
    document.getElementById('refaireBtn').classList.toggle('active', isRefaire);
    const hasPending = !!(s.pendingValide[CARD_ID] || s.pendingRefaire[CARD_ID]);
    document.getElementById('reviewPendingBar').classList.toggle('visible', hasPending);
  }

  function toggleValide() {
    const s = loadState();
    if (s.posted[CARD_ID] || s.pendingValide[CARD_ID]) {
      delete s.posted[CARD_ID];
      delete s.pendingValide[CARD_ID];
    } else {
      s.pendingValide[CARD_ID] = true;
      delete s.pendingRefaire[CARD_ID];
    }
    saveState(s);
    refreshButtons();
  }

  function toggleRefaire() {
    const s = loadState();
    if (s.pendingRefaire[CARD_ID]) {
      delete s.pendingRefaire[CARD_ID];
    } else {
      s.pendingRefaire[CARD_ID] = true;
      delete s.pendingValide[CARD_ID];
    }
    saveState(s);
    refreshButtons();
  }

  function discardReview() {
    const s = loadState();
    delete s.pendingValide[CARD_ID];
    delete s.pendingRefaire[CARD_ID];
    saveState(s);
    refreshButtons();
  }

  // Commits this single card's pending Validé/À refaire — same two
  // endpoints the dashboard's savePendingChanges() batches over, just for
  // one CARD_ID. Reloads on success so refreshButtons() reflects the
  // now-committed state (and, for à refaire, the archived media/detail
  // page redirect the reload would otherwise 404 on is handled by the
  // dashboard's own manifest scan next time it's opened).
  function saveReview() {
    const s = loadState();
    const isPendingValide = !!s.pendingValide[CARD_ID];
    const isPendingRefaire = !!s.pendingRefaire[CARD_ID];
    if (!isPendingValide && !isPendingRefaire) return;

    const btn = document.getElementById('reviewSaveBtn');
    btn.disabled = true;
    btn.textContent = 'Enregistrement…';

    let request;
    if (isPendingValide) {
      request = PRODUCT_URL
        ? fetch(`${YOUM_SERVER_BASE}/api/update-status`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ product_url: PRODUCT_URL, status: 'valide', asset_type: ASSET_TYPE }),
          }).catch(() => {})
        : Promise.resolve();
    } else {
      request = fetch(`${YOUM_SERVER_BASE}/api/delete-asset`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          media_path: CARD_ID,
          source_json_path: SOURCE_JSON_PATH,
          html_path: DETAIL_PAGE_PATH,
          product_url: PRODUCT_URL || null,
        }),
      }).catch(() => {});
    }

    request.then(() => {
      const fresh = loadState();
      if (isPendingValide) fresh.posted[CARD_ID] = new Date().toISOString();
      if (isPendingRefaire) fresh.deleted[CARD_ID] = true;
      delete fresh.pendingValide[CARD_ID];
      delete fresh.pendingRefaire[CARD_ID];
      saveState(fresh);
      if (isPendingRefaire) {
        // This card's own media/detail page is archived/deleted server-side
        // once this commits — nothing left to show here, back to the
        // dashboard instead of reloading a page that will 404.
        window.location.href = document.querySelector('.back-link').getAttribute('href');
      } else {
        btn.textContent = 'Enregistré';
        setTimeout(refreshButtons, 800);
      }
    });
  }

  window.toggleValide = toggleValide;
  window.markARefaire = toggleRefaire;
  window.discardReview = discardReview;
  window.saveReview = saveReview;
  refreshButtons();
})();
