/* views/radarr-view.js — Vue dédiée Radarr (desktop) */

async function refreshRadarrView() {
  const container = $("radarrViewContent");
  if (!container) return;

  const s = state.settings || {};
  if (!s.radarr_enabled) {
    container.innerHTML = '<div class="card">'
      + '<p class="text-muted">Radarr n\'est pas activé. Configurez-le dans les Paramètres.</p>'
      + '<button class="btn btn--primary mt-2" id="btnRadarrOpenSettings">Ouvrir les réglages Radarr</button>'
      + '</div>';
    const openBtn = $("btnRadarrOpenSettings");
    if (openBtn) openBtn.addEventListener("click", () => {
      navigateTo("settings", { v5: true, category: "integrations" });
      setTimeout(() => {
        document.querySelector('[data-section-id="radarr"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 200);
    });
    return;
  }

  container.innerHTML = '<p class="text-muted">Chargement...</p>';

  try {
    const r = await apiCall("test_radarr_connection", () => window.pywebview.api.test_radarr_connection(
      s.radarr_url || "", s.radarr_api_key || ""
    ));

    let html = '<div class="kpi-grid mb-4">';
    html += `<div class="kpi"><div class="kpi__label">Statut</div><div class="kpi__value">${r.ok ? '<span class="text-success">Connecté</span>' : '<span class="text-danger">Déconnecté</span>'}</div></div>`;
    if (r.server_name) html += `<div class="kpi"><div class="kpi__label">Serveur</div><div class="kpi__value">${escapeHtml(r.server_name)}</div></div>`;
    html += '</div>';

    html += '<div class="flex gap-2 mt-4">';
    html += '<button class="btn btn--compact" id="btnRadarrTest">Tester</button>';
    html += '<button class="btn btn--compact" id="btnRadarrStatus">Rapport / Upgrades</button>';
    html += '</div>';
    html += '<div id="radarrViewMsg" class="status-msg mt-2"></div>';
    html += '<div id="radarrStatusResults" class="mt-4"></div>';

    container.innerHTML = html;

    $("btnRadarrTest")?.addEventListener("click", async () => {
      const msg = $("radarrViewMsg");
      if (msg) msg.textContent = "Test...";
      const tr = await apiCall("test_radarr_connection", () => window.pywebview.api.test_radarr_connection(s.radarr_url || "", s.radarr_api_key || ""));
      if (msg) msg.textContent = tr.ok ? `Connecté — ${tr.server_name || ""}` : "Échec";
    });

    $("btnRadarrStatus")?.addEventListener("click", async () => {
      const results = $("radarrStatusResults");
      if (!results) return;
      results.innerHTML = '<p class="text-muted">Chargement...</p>';
      try {
        const sr = await apiCall("get_radarr_status", () => window.pywebview.api.get_radarr_status());
        let h = `<p>Films Radarr : ${sr.total || 0} | Synchronisés : ${sr.matched || 0} | Upgrades : ${sr.upgrade_candidates?.length || 0}</p>`;
        if (sr.upgrade_candidates?.length) {
          h += '<div class="table-wrap mt-4"><table class="tbl"><thead><tr><th>Film</th><th>Score</th><th>Action</th></tr></thead><tbody>';
          for (const c of sr.upgrade_candidates.slice(0, 20)) {
            h += `<tr><td>${escapeHtml(c.title || "")}</td><td>${c.score || "—"}</td>`;
            h += `<td><button class="btn btn--compact" data-action="radarr-upgrade" data-movie-id="${c.radarr_movie_id || 0}">Upgrade</button></td></tr>`;
          }
          h += '</tbody></table></div>';
        }
        results.innerHTML = h;
        // Event delegation pour les boutons upgrade Radarr
        results.addEventListener("click", async (e) => {
          const btn = e.target.closest("[data-action='radarr-upgrade']");
          if (!btn) return;
          const movieId = parseInt(btn.dataset.movieId, 10) || 0;
          await apiCall("request_radarr_upgrade", () => window.pywebview.api.request_radarr_upgrade(movieId));
          alert("Upgrade demandé.");
        });
      } catch (err) { results.innerHTML = `<p class="status-msg error">${escapeHtml(String(err))}</p>`; }
    });
  } catch (err) {
    container.innerHTML = `<p class="status-msg error">${escapeHtml(String(err))}</p>`;
  }
}
