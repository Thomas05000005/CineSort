/* views/radarr.js — Vue Radarr du dashboard distant */

import { $, escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { kpiGridHtml } from "../components/kpi-card.js";
import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";
import { t } from "../core/i18n.js";
// Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplacer alert() natif
// par showToast pour notification de test de connexion (non destructif).
import { showToast } from "../components/toast.js";

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
      el.innerHTML = `<div class="card"><h3>${escapeHtml(t("radarr.not_configured_title"))}</h3>
        <p class="text-muted mt-4">${escapeHtml(t("radarr.not_configured_body"))}</p>
        <a href="#/parametres#integrations-radarr" class="btn btn-primary mt-4">${escapeHtml(t("radarr.open_settings"))}</a></div>`;
      return;
    }

    const connRes = await apiPost("integrations/test_radarr_connection", { url: s.radarr_url || "", api_key: s.radarr_api_key || "" });
    const conn = connRes.data || {};
    const ok = !!conn.ok;

    let html = kpiGridHtml([
      { label: t("radarr.kpi_status"), value: ok ? t("radarr.status_connected") : t("radarr.status_disconnected"), color: ok ? "var(--success)" : "var(--danger)" },
      { label: t("radarr.kpi_server"), value: conn.server_name || "—", color: "var(--accent)" },
      { label: t("radarr.kpi_version"), value: conn.version || "—", color: "var(--info)" },
    ]);

    html += '<div class="card mt-4">';
    html += `<h3>${escapeHtml(t("radarr.actions_title"))}</h3>`;
    html += `<div class="mt-4"><button class="btn btn--compact" id="btnRadarrTest">${escapeHtml(t("radarr.btn_test"))}</button>`;
    html += ` <button class="btn btn--compact" id="btnRadarrStatus">${escapeHtml(t("radarr.btn_status"))}</button></div>`;
    html += '<div id="radarrStatusResult" class="mt-4"></div>';
    html += '</div>';

    el.innerHTML = html;

    $("btnRadarrTest")?.addEventListener("click", async () => {
      const r = await apiPost("integrations/test_radarr_connection", { url: s.radarr_url, api_key: s.radarr_api_key });
      // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
      const ok = !!r.data?.ok;
      const text = ok ? t("radarr.test_ok", { name: r.data.server_name }) : (r.data?.error || t("radarr.test_fail"));
      showToast({ type: ok ? "success" : "error", text });
    });

    $("btnRadarrStatus")?.addEventListener("click", async () => {
      const container = $("radarrStatusResult");
      if (!container) return;
      container.innerHTML = `<p class="text-muted">${escapeHtml(t("radarr.loading"))}</p>`;
      let r;
      try { r = await apiPost("integrations/get_radarr_status"); }
      catch { container.innerHTML = `<p class="text-muted">${escapeHtml(t("radarr.network_error"))}</p>`; return; }
      const d = r.data || {};
      if (!d.ok && d.message) { container.innerHTML = `<p class="text-muted">${escapeHtml(d.message)}</p>`; return; }
      const candidates = d.upgrade_candidates || [];
      let h = `<div class="kpi-grid mt-2">
        <div class="kpi-card" style="border-left:3px solid var(--success)"><div class="kpi-label">${escapeHtml(t("radarr.kpi_matches"))}</div><div class="kpi-value">${d.matched_count || 0}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--warning)"><div class="kpi-label">${escapeHtml(t("radarr.kpi_not_in_radarr"))}</div><div class="kpi-value">${(d.not_in_radarr || []).length}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--info)"><div class="kpi-label">${escapeHtml(t("radarr.kpi_upgrades"))}</div><div class="kpi-value">${candidates.length}</div></div>
      </div>`;
      if (candidates.length) {
        h += `<h4 class="mt-4">${escapeHtml(t("radarr.upgrade_candidates_title"))}</h4><table class="tbl mt-2"><thead><tr><th>${escapeHtml(t("radarr.col_title"))}</th><th>${escapeHtml(t("radarr.col_score"))}</th><th>${escapeHtml(t("radarr.col_action"))}</th></tr></thead><tbody>`;
        for (const c of candidates.slice(0, 20)) {
          h += `<tr><td>${escapeHtml(c.title || "")}</td><td>${c.score || "?"}</td>`;
          h += `<td><button class="btn btn--compact btn-radarr-upgrade" data-rid="${c.radarr_id || 0}">${escapeHtml(t("radarr.btn_upgrade"))}</button></td></tr>`;
        }
        h += '</tbody></table>';
      }
      container.innerHTML = h;

      // Hook upgrade buttons
      container.querySelectorAll(".btn-radarr-upgrade").forEach(btn => {
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = t("radarr.btn_upgrade_running");
          const rid = parseInt(btn.dataset.rid, 10);
          const res = await apiPost("integrations/request_radarr_upgrade", { movie_id: rid });
          btn.textContent = res.data?.ok ? t("radarr.btn_upgrade_ok") : t("radarr.btn_upgrade_fail");
        });
      });
    });

  } catch (err) {
    el.innerHTML = `<p class="text-muted">${escapeHtml(t("errors.generic", { detail: err.message || String(err) }))}</p>`;
  }
}
