/* views/jellyfin-view.js — Vue dédiée Jellyfin (desktop) */

async function refreshJellyfinView() {
  const container = $("jellyfinViewContent");
  if (!container) return;

  const s = state.settings || {};
  if (!s.jellyfin_enabled) {
    container.innerHTML = '<div class="card">'
      + '<p class="text-muted">Jellyfin n\'est pas activé. Configurez-le dans les Paramètres.</p>'
      + '<button class="btn btn--primary mt-2" id="btnJellyfinOpenSettings">Ouvrir les réglages Jellyfin</button>'
      + '</div>';
    const openBtn = $("btnJellyfinOpenSettings");
    if (openBtn) openBtn.addEventListener("click", () => {
      navigateTo("settings", { v5: true, category: "integrations" });
      setTimeout(() => {
        document.querySelector('[data-section-id="jellyfin"]')?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 200);
    });
    return;
  }

  container.innerHTML = '<p class="text-muted">Chargement...</p>';

  try {
    const r = await apiCall("test_jellyfin_connection", () => window.pywebview.api.test_jellyfin_connection(
      s.jellyfin_url || "", s.jellyfin_api_key || "", s.jellyfin_timeout_s || 10
    ));

    let html = '<div class="kpi-grid mb-4">';
    html += `<div class="kpi"><div class="kpi__label">Statut</div><div class="kpi__value">${r.ok ? '<span class="text-success">Connecté</span>' : '<span class="text-danger">Déconnecté</span>'}</div></div>`;
    if (r.server_name) html += `<div class="kpi"><div class="kpi__label">Serveur</div><div class="kpi__value">${escapeHtml(r.server_name)}</div></div>`;
    if (r.version) html += `<div class="kpi"><div class="kpi__label">Version</div><div class="kpi__value">${escapeHtml(r.version)}</div></div>`;
    if (r.movies_count) html += `<div class="kpi"><div class="kpi__label">Films</div><div class="kpi__value">${r.movies_count}</div></div>`;
    html += '</div>';

    if (r.libraries?.length) {
      html += '<div class="card mb-4"><div class="card__eyebrow">Bibliothèques</div><ul class="mt-2">';
      for (const lib of r.libraries) {
        html += `<li>${escapeHtml(lib.name)} <span class="text-muted">(${escapeHtml(lib.collection_type || "")})</span></li>`;
      }
      html += '</ul></div>';
    }

    html += '<div class="flex gap-2 mt-4">';
    html += '<button class="btn btn--compact" id="btnJellyfinTest">Tester la connexion</button>';
    html += '<button class="btn btn--compact" id="btnJellyfinSyncReport">Vérifier la cohérence</button>';
    html += '</div>';
    html += '<div id="jellyfinViewMsg" class="status-msg mt-2"></div>';
    html += '<div id="jellyfinSyncResults" class="mt-4"></div>';

    container.innerHTML = html;

    // M5 : event delegation attache une seule fois sur le container parent
    if (!container.dataset.delegated) {
      container.dataset.delegated = "1";
      container.addEventListener("click", async (e) => {
        const target = e.target;
        if (target.closest("#btnJellyfinTest")) {
          const msg = $("jellyfinViewMsg");
          if (msg) msg.textContent = "Test en cours...";
          const sNow = state.settings || {};
          const tr = await apiCall("test_jellyfin_connection", () => window.pywebview.api.test_jellyfin_connection(
            sNow.jellyfin_url || "", sNow.jellyfin_api_key || "", sNow.jellyfin_timeout_s || 10
          ));
          if (msg) msg.textContent = tr.ok ? `Connecté — ${tr.server_name || ""}` : (tr.message || "Échec");
          return;
        }
        if (target.closest("#btnJellyfinSyncReport")) {
          const results = $("jellyfinSyncResults");
          if (!results) return;
          results.innerHTML = '<p class="text-muted">Vérification en cours...</p>';
          try {
            const sr = await apiCall("get_jellyfin_sync_report", () => window.pywebview.api.get_jellyfin_sync_report());
            if (!sr.ok) { results.innerHTML = `<p class="status-msg error">${escapeHtml(sr.message || "Erreur")}</p>`; return; }
            let h = `<div class="kpi-grid mb-4">`;
            h += `<div class="kpi"><div class="kpi__label">Synchronisés</div><div class="kpi__value text-success">${sr.matched || 0}</div></div>`;
            h += `<div class="kpi"><div class="kpi__label">Manquants</div><div class="kpi__value text-warning">${sr.missing_in_jellyfin?.length || 0}</div></div>`;
            h += `<div class="kpi"><div class="kpi__label">Fantômes</div><div class="kpi__value text-danger">${sr.ghost_in_jellyfin?.length || 0}</div></div>`;
            h += `</div>`;
            results.innerHTML = h;
          } catch (err) { results.innerHTML = `<p class="status-msg error">${escapeHtml(String(err))}</p>`; }
        }
      });
    }
  } catch (err) {
    container.innerHTML = `<p class="status-msg error">${escapeHtml(String(err))}</p>`;
  }
}

function hookJellyfinViewEvents() {
  // Les events sont hookés dans refreshJellyfinView
}
