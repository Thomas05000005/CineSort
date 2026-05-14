/* views/radarr.js — Vue Radarr du dashboard distant */

import { $, escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { kpiGridHtml } from "../components/kpi-card.js";
import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";

export function initRadarr() { _load(); }

async function _load() {
  const el = $("radarrContent");
  if (!el) return;
  // V2-08 : skeleton uniquement au 1er load (ne flashe pas sur re-render)
  if (!el.innerHTML.trim()) {
    el.innerHTML = `<div aria-busy="true" aria-label="Chargement Radarr">
      ${skeletonKpiGridHtml(3)}
      ${skeletonLinesHtml(3)}
    </div>`;
  }

  try {
    const sRes = await apiPost("settings/get_settings");
    const s = sRes.data || {};

    if (!s.radarr_enabled) {
      el.innerHTML = `<div class="card"><h3>Radarr non configure</h3>
        <p class="text-muted mt-4">L'integration Radarr est desactivee. Pour l'activer, ouvrez les reglages et configurez la section Radarr (URL, cle API, candidats d'upgrade).</p>
        <a href="#/settings" class="btn btn-primary mt-4">Ouvrir les réglages Radarr</a></div>`;
      return;
    }

    const connRes = await apiPost("integrations/test_radarr_connection", { url: s.radarr_url || "", api_key: s.radarr_api_key || "" });
    const conn = connRes.data || {};
    const ok = !!conn.ok;

    let html = kpiGridHtml([
      { label: "Statut", value: ok ? "Connecte" : "Deconnecte", color: ok ? "var(--success)" : "var(--danger)" },
      { label: "Serveur", value: conn.server_name || "—", color: "var(--accent)" },
      { label: "Version", value: conn.version || "—", color: "var(--info)" },
    ]);

    html += '<div class="card mt-4">';
    html += '<h3>Actions</h3>';
    html += `<div class="mt-4"><button class="btn btn--compact" id="btnRadarrTest">Tester la connexion</button>`;
    html += ` <button class="btn btn--compact" id="btnRadarrStatus">Voir le rapport</button></div>`;
    html += '<div id="radarrStatusResult" class="mt-4"></div>';
    html += '</div>';

    el.innerHTML = html;

    $("btnRadarrTest")?.addEventListener("click", async () => {
      const r = await apiPost("integrations/test_radarr_connection", { url: s.radarr_url, api_key: s.radarr_api_key });
      alert(r.data?.ok ? `OK — ${r.data.server_name}` : (r.data?.error || "Echec"));
    });

    $("btnRadarrStatus")?.addEventListener("click", async () => {
      const container = $("radarrStatusResult");
      if (!container) return;
      container.innerHTML = '<p class="text-muted">Chargement...</p>';
      let r;
      try { r = await apiPost("integrations/get_radarr_status"); }
      catch { container.innerHTML = '<p class="text-muted">Erreur reseau.</p>'; return; }
      const d = r.data || {};
      if (!d.ok && d.message) { container.innerHTML = `<p class="text-muted">${escapeHtml(d.message)}</p>`; return; }
      const candidates = d.upgrade_candidates || [];
      let h = `<div class="kpi-grid mt-2">
        <div class="kpi-card" style="border-left:3px solid var(--success)"><div class="kpi-label">Matches</div><div class="kpi-value">${d.matched_count || 0}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--warning)"><div class="kpi-label">Pas dans Radarr</div><div class="kpi-value">${(d.not_in_radarr || []).length}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--info)"><div class="kpi-label">Upgrades</div><div class="kpi-value">${candidates.length}</div></div>
      </div>`;
      if (candidates.length) {
        h += '<h4 class="mt-4">Candidats upgrade</h4><table class="tbl mt-2"><thead><tr><th>Titre</th><th>Score</th><th>Action</th></tr></thead><tbody>';
        for (const c of candidates.slice(0, 20)) {
          h += `<tr><td>${escapeHtml(c.title || "")}</td><td>${c.score || "?"}</td>`;
          h += `<td><button class="btn btn--compact btn-radarr-upgrade" data-rid="${c.radarr_id || 0}">Upgrade</button></td></tr>`;
        }
        h += '</tbody></table>';
      }
      container.innerHTML = h;

      // Hook upgrade buttons
      container.querySelectorAll(".btn-radarr-upgrade").forEach(btn => {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = "...";
          const rid = parseInt(btn.dataset.rid, 10);
          const res = await apiPost("integrations/request_radarr_upgrade", { movie_id: rid });
          btn.textContent = res.data?.ok ? "Lance !" : "Echec";
        });
      });
    });

  } catch (err) {
    el.innerHTML = `<p class="text-muted">Erreur : ${escapeHtml(err.message || String(err))}</p>`;
  }
}
