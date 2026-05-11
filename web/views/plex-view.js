/* views/plex-view.js — Vue dédiée Plex (desktop) */

async function refreshPlexView() {
  const container = $("plexViewContent");
  if (!container) return;

  const s = state.settings || {};
  if (!s.plex_enabled) {
    container.innerHTML = '<div class="card">'
      + '<p class="text-muted">Plex n\'est pas activé. Configurez-le dans les Paramètres.</p>'
      + '<button class="btn btn--primary mt-2" id="btnPlexOpenSettings">Ouvrir les réglages Plex</button>'
      + '</div>';
    const openBtn = $("btnPlexOpenSettings");
    if (openBtn) openBtn.addEventListener("click", () => {
      navigateTo("settings", { v5: true, category: "integrations" });
      setTimeout(() => {
        document.querySelector('[data-section-id="plex"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 200);
    });
    return;
  }

  container.innerHTML = '<p class="text-muted">Chargement...</p>';

  try {
    const r = await apiCall("test_plex_connection", () => window.pywebview.api.test_plex_connection(
      s.plex_url || "", s.plex_token || ""
    ));

    let html = '<div class="kpi-grid mb-4">';
    html += `<div class="kpi"><div class="kpi__label">Statut</div><div class="kpi__value">${r.ok ? '<span class="text-success">Connecté</span>' : '<span class="text-danger">Déconnecté</span>'}</div></div>`;
    if (r.server_name) html += `<div class="kpi"><div class="kpi__label">Serveur</div><div class="kpi__value">${escapeHtml(r.server_name)}</div></div>`;
    html += '</div>';

    html += '<div class="flex gap-2 mt-4">';
    html += '<button class="btn btn--compact" id="btnPlexTest">Tester</button>';
    html += '<button class="btn btn--compact" id="btnPlexSync">Validation croisée</button>';
    html += '</div>';
    html += '<div id="plexViewMsg" class="status-msg mt-2"></div>';
    html += '<div id="plexSyncResults" class="mt-4"></div>';

    container.innerHTML = html;

    $("btnPlexTest")?.addEventListener("click", async () => {
      const msg = $("plexViewMsg");
      if (msg) msg.textContent = "Test...";
      const tr = await apiCall("test_plex_connection", () => window.pywebview.api.test_plex_connection(s.plex_url || "", s.plex_token || ""));
      if (msg) msg.textContent = tr.ok ? `Connecté — ${tr.server_name || ""}` : "Échec";
    });

    $("btnPlexSync")?.addEventListener("click", async () => {
      const results = $("plexSyncResults");
      if (!results) return;
      results.innerHTML = '<p class="text-muted">Vérification...</p>';
      try {
        const sr = await apiCall("get_plex_sync_report", () => window.pywebview.api.get_plex_sync_report());
        results.innerHTML = `<p>Synchronisés : ${sr.matched || 0} | Manquants : ${sr.missing?.length || 0} | Fantômes : ${sr.ghosts?.length || 0}</p>`;
      } catch (err) { results.innerHTML = `<p class="status-msg error">${escapeHtml(String(err))}</p>`; }
    });
  } catch (err) {
    container.innerHTML = `<p class="status-msg error">${escapeHtml(String(err))}</p>`;
  }
}
