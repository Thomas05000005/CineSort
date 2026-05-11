/* views/plex.js — Vue Plex du dashboard distant */

import { $, escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { kpiGridHtml } from "../components/kpi-card.js";
import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";

export function initPlex() { _load(); }

async function _load() {
  const el = $("plexContent");
  if (!el) return;
  // V2-08 : skeleton uniquement au 1er load (ne flashe pas sur re-render)
  if (!el.innerHTML.trim()) {
    el.innerHTML = `<div aria-busy="true" aria-label="Chargement Plex">
      ${skeletonKpiGridHtml(3)}
      ${skeletonLinesHtml(3)}
    </div>`;
  }

  try {
    const sRes = await apiPost("get_settings");
    const s = sRes.data || {};

    if (!s.plex_enabled) {
      el.innerHTML = `<div class="card"><h3>Plex non configure</h3>
        <p class="text-muted mt-4">L'integration Plex est desactivee. Pour l'activer, ouvrez les reglages et configurez la section Plex (URL, token, refresh automatique).</p>
        <a href="#/settings" class="btn btn-primary mt-4">Ouvrir les réglages Plex</a></div>`;
      return;
    }

    const connRes = await apiPost("test_plex_connection", { url: s.plex_url || "", token: s.plex_token || "" });
    const conn = connRes.data || {};
    const ok = !!conn.ok;

    let html = kpiGridHtml([
      { label: "Statut", value: ok ? "Connecte" : "Deconnecte", color: ok ? "var(--success)" : "var(--danger)" },
      { label: "Serveur", value: conn.server_name || "—", color: "var(--accent)" },
      { label: "Version", value: conn.version || "—", color: "var(--info)" },
    ]);

    html += '<div class="card mt-4">';
    html += '<h3>Informations</h3>';
    html += `<p class="mt-2 text-secondary">URL : ${escapeHtml(s.plex_url || "—")}</p>`;
    html += `<p class="text-secondary">Refresh auto : ${s.plex_refresh_on_apply ? "Oui" : "Non"}</p>`;
    html += `<div class="mt-4"><button class="btn btn--compact" id="btnPlexTest">Tester la connexion</button>`;
    html += ` <button class="btn btn--compact" id="btnPlexSync">Validation croisee</button></div>`;
    html += '<div id="plexSyncResult" class="mt-4"></div>';
    html += '</div>';

    el.innerHTML = html;

    $("btnPlexTest")?.addEventListener("click", async () => {
      const r = await apiPost("test_plex_connection", { url: s.plex_url, token: s.plex_token });
      alert(r.data?.ok ? `OK — ${r.data.server_name}` : (r.data?.error || "Echec"));
    });

    $("btnPlexSync")?.addEventListener("click", async () => {
      const container = $("plexSyncResult");
      if (!container) return;
      container.innerHTML = '<p class="text-muted">Chargement...</p>';
      let r;
      try { r = await apiPost("get_plex_sync_report"); }
      catch { container.innerHTML = '<p class="text-muted">Erreur reseau.</p>'; return; }
      const d = r.data || {};
      if (!d.ok && d.message) { container.innerHTML = `<p class="text-muted">${escapeHtml(d.message)}</p>`; return; }
      container.innerHTML = `<div class="kpi-grid mt-2">
        <div class="kpi-card" style="border-left:3px solid var(--success)"><div class="kpi-label">Matches</div><div class="kpi-value">${d.matched || 0}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--warning)"><div class="kpi-label">Manquants</div><div class="kpi-value">${(d.missing_in_plex || []).length}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--danger)"><div class="kpi-label">Fantomes</div><div class="kpi-value">${(d.ghost_in_plex || []).length}</div></div>
      </div>`;
    });

  } catch (err) {
    el.innerHTML = `<p class="text-muted">Erreur : ${escapeHtml(err.message || String(err))}</p>`;
  }
}
