/* views/plex.js — Vue Plex du dashboard distant */

import { $, escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { kpiGridHtml } from "../components/kpi-card.js";
import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";
import { t } from "../core/i18n.js";
// Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplacer alert() natif
// par showToast pour notification de test de connexion (non destructif).
import { showToast } from "../components/toast.js";

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
    const sRes = await apiPost("settings/get_settings");
    const s = sRes.data || {};

    if (!s.plex_enabled) {
      el.innerHTML = `<div class="card"><h3>${escapeHtml(t("plex.not_configured_title"))}</h3>
        <p class="text-muted mt-4">${escapeHtml(t("plex.not_configured_body"))}</p>
        <a href="#/parametres#integrations-plex" class="btn btn-primary mt-4">${escapeHtml(t("plex.open_settings"))}</a></div>`;
      return;
    }

    const connRes = await apiPost("integrations/test_plex_connection", { url: s.plex_url || "", token: s.plex_token || "" });
    const conn = connRes.data || {};
    const ok = !!conn.ok;

    let html = kpiGridHtml([
      { label: t("plex.kpi_status"), value: ok ? t("plex.status_connected") : t("plex.status_disconnected"), color: ok ? "var(--success)" : "var(--danger)" },
      { label: t("plex.kpi_server"), value: conn.server_name || "—", color: "var(--accent)" },
      { label: t("plex.kpi_version"), value: conn.version || "—", color: "var(--info)" },
    ]);

    html += '<div class="card mt-4">';
    html += `<h3>${escapeHtml(t("plex.info_title"))}</h3>`;
    html += `<p class="mt-2 text-secondary">${escapeHtml(t("plex.info_url", { url: s.plex_url || "—" }))}</p>`;
    html += `<p class="text-secondary">${escapeHtml(t("plex.info_refresh", { value: s.plex_refresh_on_apply ? t("common.yes") : t("common.no") }))}</p>`;
    html += `<div class="mt-4"><button class="btn btn--compact" id="btnPlexTest">${escapeHtml(t("plex.btn_test"))}</button>`;
    html += ` <button class="btn btn--compact" id="btnPlexSync">${escapeHtml(t("plex.btn_sync"))}</button></div>`;
    html += '<div id="plexSyncResult" class="mt-4"></div>';
    html += '</div>';

    el.innerHTML = html;

    $("btnPlexTest")?.addEventListener("click", async () => {
      const r = await apiPost("integrations/test_plex_connection", { url: s.plex_url, token: s.plex_token });
      // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
      const ok = !!r.data?.ok;
      const text = ok ? t("plex.test_ok", { name: r.data.server_name }) : (r.data?.error || t("plex.test_fail"));
      showToast({ type: ok ? "success" : "error", text });
    });

    $("btnPlexSync")?.addEventListener("click", async () => {
      const container = $("plexSyncResult");
      if (!container) return;
      container.innerHTML = `<p class="text-muted">${escapeHtml(t("plex.loading"))}</p>`;
      let r;
      try { r = await apiPost("integrations/get_plex_sync_report"); }
      catch { container.innerHTML = `<p class="text-muted">${escapeHtml(t("plex.network_error"))}</p>`; return; }
      const d = r.data || {};
      if (!d.ok && d.message) { container.innerHTML = `<p class="text-muted">${escapeHtml(d.message)}</p>`; return; }
      container.innerHTML = `<div class="kpi-grid mt-2">
        <div class="kpi-card" style="border-left:3px solid var(--success)"><div class="kpi-label">${escapeHtml(t("plex.kpi_matches"))}</div><div class="kpi-value">${d.matched || 0}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--warning)"><div class="kpi-label">${escapeHtml(t("plex.kpi_missing"))}</div><div class="kpi-value">${(d.missing_in_plex || []).length}</div></div>
        <div class="kpi-card" style="border-left:3px solid var(--danger)"><div class="kpi-label">${escapeHtml(t("plex.kpi_ghosts"))}</div><div class="kpi-value">${(d.ghost_in_plex || []).length}</div></div>
      </div>`;
    });

  } catch (err) {
    el.innerHTML = `<p class="text-muted">${escapeHtml(t("errors.generic", { detail: err.message || String(err) }))}</p>`;
  }
}
