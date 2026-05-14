/* views/qij.js — V7-fusion Phase 3 QIJ
 *
 * Vue consolidee Quality + Integrations + Journal en 3 tabs.
 * Base : architecture v5 qij-v5.js (3 tabs + initQ/initI/initJ).
 * Ajouts (21 features portees depuis 5 vues v4) :
 *   Tab Quality :
 *     - KPI 4 cards (films/score/platinum/tendance)
 *     - Boutons quality-simulator + custom-rules-editor (modules autonomes)
 *     - Anomalies frequentes
 *     - Outliers drill-down 2sigma
 *     - Distribution technique (resolutions/HDR/audio)
 *     - Filtres tier+state+score (état pres en local)
 *     - Profil scoring (export/import/reset)
 *     - Batch analysis (analyser tous/filtres)
 *   Tab Integrations :
 *     - Sync reports modaux (Jellyfin/Plex/Radarr) avec missing/ghost/mismatch
 *     - Liste libraries Jellyfin
 *     - Candidats upgrade Radarr
 *   Tab Journal :
 *     - Toggle Live/Historique
 *     - Polling 2s pendant run actif (singleton anti-leak)
 *     - Progress bar live + ETA + bouton annuler
 *     - Export NFO par run
 *     - Table runs sortable
 */

import { apiPost, apiGet } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { glossaryTooltip } from "../components/glossary-tooltip.js";
import { showModal } from "../components/modal.js";
import { fmtDate as _fmtDate, fmtDuration as _fmtDuration } from "../core/format.js";
import { journalPoller } from "../core/journal-polling.js";
import { getNavSignal, isAbortError } from "../core/nav-abort.js";
import { t } from "../core/i18n.js";
// Modules autonomes deja existants (modales).
import { openQualitySimulator } from "./quality-simulator.js";
import { openCustomRulesEditor } from "./custom-rules-editor.js";

const _esc = escapeHtml;

function _svg(p, s) {
  const sz = s || 18;
  return `<svg viewBox="0 0 24 24" width="${sz}" height="${sz}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
}

// V2-C R4-MEM-6 : _call accepte un signal optionnel pour les fetchs annulables.
async function _call(method, params, opts) {
  const res = await apiPost(method, params, opts || {});
  return (res && res.data) || null;
}

/* ============================================================
 * TAB QUALITY (enrichi avec 11 features v4)
 * ============================================================ */

const _qState = {
  containerRef: null,
  globalStats: null,
  rollupBy: "franchise",
  rollupData: null,
};

function _hasDataInDistribution(d) {
  if (!d || typeof d !== "object") return false;
  const c = d.counts || d;
  if (!c || typeof c !== "object") return false;
  return Object.values(c).some((v) => Number(v) > 0);
}

function _hasDataInTrend(t) {
  if (!t) return false;
  const p = Array.isArray(t) ? t : (t.points || t.values || []);
  return Array.isArray(p) && p.length >= 2;
}

export async function initQuality(container, _opts = {}) {
  if (!container) return;
  _qState.containerRef = container;
  container.innerHTML = `<div class="v5-qij-skeleton" aria-busy="true">
    <div class="v5-skeleton-section"><div class="v5-skeleton-grid">${"<div class='v5-skeleton-card'></div>".repeat(4)}</div></div>
    <div class="v5-skeleton-section"><div class="v5-skeleton-table">${"<div class='v5-skeleton-row'></div>".repeat(6)}</div></div>
  </div>`;
  await _qualityFetchAll();
  _qualityRender();
}

export function unmountQuality() {
  if (_qState.containerRef) _qState.containerRef.innerHTML = "";
  _qState.containerRef = null;
}

async function _qualityFetchAll() {
  // V2-C R4-MEM-6 : signal de nav pour abort si l'utilisateur switche tab/route.
  const navSig = getNavSignal();
  const labels = ["get_global_stats", "get_scoring_rollup"];
  const results = await Promise.allSettled([
    _call("get_global_stats", { limit_runs: 20 }, { signal: navSig }),
    _call("library/get_scoring_rollup", { by: _qState.rollupBy, limit: 20, run_id: null }, { signal: navSig }),
  ]);
  const _val = (r) => (r && r.status === "fulfilled" ? r.value : null);
  const [stats, rollup] = results.map(_val);
  const failed = labels.filter((_, i) => results[i].status !== "fulfilled" && !isAbortError(results[i].reason));
  if (failed.length > 0) console.warn("[qij-quality] endpoints en echec:", failed);
  _qState.globalStats = stats;
  _qState.rollupData = rollup;
}

function _qualityRender() {
  const root = _qState.containerRef;
  if (!root) return;
  const stats = _qState.globalStats || {};
  const dist = stats.v2_tier_distribution;
  const trend = stats.trend_30days;
  const totalFilms = Number(stats.total_films || 0);
  const hasData = _hasDataInDistribution(dist) || _hasDataInTrend(trend) || totalFilms > 0;

  if (!hasData) {
    root.innerHTML = `<div class="v5-qij-shell"><div class="v5-library-empty" style="padding:var(--sp-6);text-align:center">
      <h3>${_esc(t("qij.quality.no_data_title"))}</h3>
      <p class="v5u-text-muted">${_esc(t("qij.quality.no_data_hint"))}</p>
      <button type="button" class="v5-btn v5-btn--primary" onclick="window.location.hash='#/processing?step=scan'">${_esc(t("qij.quality.btn_scan"))}</button>
    </div></div>`;
    return;
  }

  // KPIs (port v4)
  const avgScore = stats.avg_score || 0;
  const premiumPct = stats.premium_pct || 0;
  const trendArrow = stats.trend === "up" ? "↑" : stats.trend === "down" ? "↓" : "→";
  const trendColor = stats.trend === "up" ? "var(--success)" : stats.trend === "down" ? "var(--danger)" : "var(--text-muted)";
  const anomalies = stats.top_anomalies || [];
  const tech = stats.technical_distribution || {};

  // Outliers (calc 2σ port v4)
  const allRows = stats.all_scored_rows || [];
  let outliers = [], outlierThreshold = 0;
  if (allRows.length > 5) {
    const scores = allRows.map((r) => Number(r.score || 0)).filter((s) => s > 0);
    if (scores.length > 0) {
      const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
      const std = Math.sqrt(scores.reduce((a, b) => a + (b - mean) ** 2, 0) / scores.length);
      outlierThreshold = Math.max(30, mean - 2 * std);
      outliers = allRows.filter((r) => Number(r.score || 0) > 0 && Number(r.score) < outlierThreshold);
    }
  }

  root.innerHTML = `
    <div class="v5-qij-shell">
      <header class="v5-qij-header">
        <h1 class="v5-qij-title">${_esc(t("qij.quality.tab_title"))}</h1>
        <p class="v5u-text-muted">${_esc(t("qij.quality.subtitle"))}</p>
      </header>

      <!-- V7-port : Boutons d'action (simulator + custom rules + batch) -->
      <div class="v5-qij-actions" style="display:flex;gap:var(--sp-2);flex-wrap:wrap;margin-bottom:var(--sp-4)">
        <button type="button" class="v5-btn v5-btn--sm" id="btnQualitySimulate" title="${_esc(t("qij.quality.btn_simulate_title"))}">${_esc(t("qij.quality.btn_simulate"))}</button>
        <button type="button" class="v5-btn v5-btn--sm" id="btnCustomRulesEditor" title="${_esc(t("qij.quality.btn_custom_rules_title"))}">${_esc(t("qij.quality.btn_custom_rules"))}</button>
        <button type="button" class="v5-btn v5-btn--sm" id="qBtnAnalyzeAll">${_esc(t("qij.quality.btn_analyze_all"))}</button>
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" id="qBtnExportProfile">${_esc(t("qij.quality.btn_export_profile"))}</button>
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" id="qBtnImportProfile">${_esc(t("qij.quality.btn_import_profile"))}</button>
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" id="qBtnResetProfile">${_esc(t("qij.quality.btn_reset_profile"))}</button>
        <span id="qBatchMsg" style="margin-left:var(--sp-3);font-size:var(--fs-xs);color:var(--text-muted)"></span>
      </div>

      <!-- V7-port : KPI 4 cards -->
      <div class="v5-kpi-grid" style="margin-bottom:var(--sp-4)">
        <article class="v5-kpi-card"><header class="v5-kpi-header"><span class="v5-kpi-label">${_esc(t("qij.quality.kpi_films"))}</span></header><div class="v5-kpi-body"><span class="v5-kpi-value">${Number(stats.total_films || 0)}</span></div></article>
        <article class="v5-kpi-card v5-kpi-card--tier-gold"><header class="v5-kpi-header"><span class="v5-kpi-label">${_esc(t("qij.quality.kpi_avg_score"))}</span></header><div class="v5-kpi-body"><span class="v5-kpi-value">${Math.round(avgScore)}</span><span class="v5-kpi-suffix">/100</span></div></article>
        <article class="v5-kpi-card"><header class="v5-kpi-header"><span class="v5-kpi-label">${_esc(t("qij.quality.kpi_platinum"))}</span></header><div class="v5-kpi-body"><span class="v5-kpi-value">${Math.round(premiumPct)}</span><span class="v5-kpi-suffix">%</span></div></article>
        <article class="v5-kpi-card"><header class="v5-kpi-header"><span class="v5-kpi-label">${_esc(t("qij.quality.kpi_trend"))}</span></header><div class="v5-kpi-body"><span class="v5-kpi-value" style="color:${trendColor}">${trendArrow}</span></div></article>
      </div>

      <section class="v5-qij-charts" id="quality-charts" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:var(--sp-4);margin-bottom:var(--sp-4)">
        <div class="v5-qij-chart-wrap card">
          <h2 class="v5-qij-section-title">Distribution ${glossaryTooltip("Tier", "tiers")}</h2>
          <div id="quality-donut"></div>
        </div>
        <div class="v5-qij-chart-wrap card">
          <h2 class="v5-qij-section-title">Tendance ${glossaryTooltip("Score perceptuel")} 30j</h2>
          <div id="quality-line"></div>
        </div>
      </section>

      <!-- V7-port : Distribution technique (résolutions/HDR/audio) -->
      ${(tech.resolutions || tech.hdr || tech.audio) ? `
        <div class="card" style="margin-bottom:var(--sp-4)">
          <h2 class="v5-qij-section-title">${_esc(t("qij.quality.section_technical"))}</h2>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:var(--sp-4);margin-top:var(--sp-3)">
            ${tech.resolutions ? _statGrid(t("qij.quality.section_resolutions"), tech.resolutions) : ""}
            ${tech.hdr ? _statGrid(t("qij.quality.section_hdr"), tech.hdr) : ""}
            ${tech.audio ? _statGrid(t("qij.quality.section_audio"), tech.audio) : ""}
          </div>
        </div>
      ` : ""}

      <section class="v5-qij-rollup card" style="margin-bottom:var(--sp-4)">
        <header class="v5-qij-rollup-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--sp-3)">
          <h2 class="v5-qij-section-title">${_esc(t("qij.quality.section_rollup"))}</h2>
          <div class="v5-qij-rollup-controls" role="tablist" aria-label="Dimension" style="display:flex;gap:var(--sp-2)">
            ${["franchise", "decade", "codec", "era_grain", "resolution"].map((d) => `
              <button type="button" class="v5-btn v5-btn--sm ${d === _qState.rollupBy ? 'v5-btn--primary' : 'v5-btn--ghost'}"
                      data-rollup-by="${_esc(d)}">${_esc(_rollupLabel(d))}</button>
            `).join("")}
          </div>
        </header>
        <div id="quality-rollup-table" style="margin-top:var(--sp-3)"></div>
      </section>

      <!-- V7-port : Anomalies + Outliers -->
      ${(anomalies.length > 0 || outliers.length > 0) ? `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:var(--sp-4);margin-bottom:var(--sp-4)">
          ${anomalies.length > 0 ? `
            <div class="card">
              <h2 class="v5-qij-section-title">${_esc(t("qij.quality.section_anomalies"))}</h2>
              <table class="v5-table" style="margin-top:var(--sp-3)"><thead><tr><th>${_esc(t("common.code"))}</th><th>${_esc(t("common.count"))}</th></tr></thead><tbody>
                ${anomalies.map((a) => `<tr><td>${_esc(a.code || "")}</td><td class="v5u-tabular-nums">${a.count || 0}</td></tr>`).join("")}
              </tbody></table>
            </div>
          ` : ""}
          ${outliers.length > 0 ? `
            <div class="card">
              <h2 class="v5-qij-section-title">${_esc(t("qij.quality.section_outliers", { threshold: Math.round(outlierThreshold) }))}</h2>
              <p class="v5u-text-muted" style="font-size:var(--fs-xs);margin-bottom:var(--sp-3)">${_esc(t("qij.quality.outliers_hint"))}</p>
              <table class="v5-table"><thead><tr><th>${_esc(t("common.title"))}</th><th>${_esc(t("common.score"))}</th><th>${_esc(t("common.tier"))}</th></tr></thead><tbody>
                ${outliers.slice(0, 15).map((r) => `<tr class="clickable-row" data-outlier-rid="${_esc(r.row_id || "")}" style="cursor:pointer">
                  <td>${_esc(r.proposed_title || r.title || "")}</td>
                  <td class="v5u-tabular-nums">${Math.round(Number(r.score || 0))}</td>
                  <td>${_esc(r.tier || "—")}</td>
                </tr>`).join("")}
              </tbody></table>
            </div>
          ` : ""}
        </div>
      ` : ""}
    </div>
  `;

  // Mount donut + line via composants partages (Vague 2)
  _mountQualityCharts(dist, trend);
  // Rollup table
  _qualityRenderRollup();
  // Bind events
  _qualityBindEvents(root);
}

function _mountQualityCharts(dist, trend) {
  // Import dynamique ici pour eviter de charger les charts si Quality jamais visite.
  import("../components/home-charts.js").then(({ renderDonut, renderLine }) => {
    const donutHost = document.getElementById("quality-donut");
    const lineHost = document.getElementById("quality-line");
    if (donutHost) {
      if (dist && _hasDataInDistribution(dist)) renderDonut(donutHost, dist);
      else donutHost.innerHTML = `<div class="v5-chart-empty">${_esc(t("qij.quality.chart_no_quality"))}</div>`;
    }
    if (lineHost) {
      if (trend && _hasDataInTrend(trend)) renderLine(lineHost, trend);
      else lineHost.innerHTML = `<div class="v5-chart-empty">${_esc(t("qij.quality.chart_no_trend"))}</div>`;
    }
  });
}

function _qualityRenderRollup() {
  const host = document.getElementById("quality-rollup-table");
  if (!host) return;
  const groups = (_qState.rollupData && _qState.rollupData.groups) || [];
  if (groups.length === 0) {
    host.innerHTML = `<div class="v5-library-empty">${_esc(t("qij.quality.no_dim_data"))}</div>`;
    return;
  }
  const rows = groups.map((g) => {
    const avg = g.avg_score != null ? Math.round(Number(g.avg_score)) : "—";
    const d = g.tier_distribution || {};
    const bars = ["platinum", "gold", "silver", "bronze", "reject"].map((t) => {
      const c = Number(d[t] || 0);
      if (c === 0) return "";
      const pct = g.count > 0 ? (c / g.count) * 100 : 0;
      return `<span class="v5-qij-dist-seg v5-qij-dist-seg--${_esc(t)}" style="width:${pct.toFixed(1)}%" title="${_esc(t)}: ${c}"></span>`;
    }).join("");
    return `<tr>
      <td class="v5-qij-rollup-name v5u-truncate">${_esc(g.group_name)}</td>
      <td class="v5u-tabular-nums">${g.count}</td>
      <td class="v5u-tabular-nums"><strong>${avg}</strong></td>
      <td><div class="v5-qij-dist-bar">${bars}</div></td>
    </tr>`;
  }).join("");
  host.innerHTML = `<table class="v5-table">
    <thead><tr><th>${_esc(_rollupLabel(_qState.rollupBy))}</th><th>${_esc(t("qij.quality.table_films"))}</th><th>${glossaryTooltip("Score perceptuel", t("qij.quality.table_avg_score"))}</th><th>Distribution ${glossaryTooltip("Tier", "tiers")}</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function _qualityBindEvents(root) {
  // Rollup dimension toggle
  root.querySelectorAll("[data-rollup-by]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      _qState.rollupBy = btn.dataset.rollupBy;
      try {
        _qState.rollupData = await _call("library/get_scoring_rollup", { by: _qState.rollupBy, limit: 20, run_id: null });
      } catch (e) { console.error("[qij-quality] rollup:", e); }
      _qualityRender();
    });
  });

  // V7-port : Quality simulator
  root.querySelector("#btnQualitySimulate")?.addEventListener("click", () => {
    const lastRun = (_qState.globalStats?.runs_summary || [])[0];
    openQualitySimulator(lastRun?.run_id || "latest");
  });

  // V7-port : Custom rules editor
  root.querySelector("#btnCustomRulesEditor")?.addEventListener("click", () => openCustomRulesEditor());

  // V7-port : Batch analysis
  root.querySelector("#qBtnAnalyzeAll")?.addEventListener("click", async () => {
    const msg = root.querySelector("#qBatchMsg");
    if (msg) { msg.textContent = t("qij.quality.batch_in_progress"); msg.style.color = "var(--text-muted)"; }
    try {
      const lastRun = (_qState.globalStats?.runs_summary || [])[0];
      if (!lastRun?.run_id) { if (msg) { msg.textContent = t("qij.quality.batch_no_run"); msg.style.color = "var(--danger)"; } return; }
      const res = await _call("quality/analyze_quality_batch", { run_id: lastRun.run_id, row_ids: [], options: { scope: "validated" } });
      if (msg) { msg.textContent = res?.message || t("qij.quality.batch_success"); msg.style.color = "var(--success)"; }
    } catch { if (msg) { msg.textContent = t("common.error_network"); msg.style.color = "var(--danger)"; } }
  });

  // V7-port : Profil scoring (export/import/reset)
  root.querySelector("#qBtnExportProfile")?.addEventListener("click", async () => {
    try {
      const res = await _call("quality/export_quality_profile");
      const blob = new Blob([JSON.stringify(res, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "quality_profile.json"; a.click();
      URL.revokeObjectURL(url);
    } catch { window.alert(t("qij.quality.export_error")); }
  });
  root.querySelector("#qBtnImportProfile")?.addEventListener("click", () => {
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".json";
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const profile = JSON.parse(text);
        await _call("quality/import_quality_profile", { profile_json: profile });
        window.alert(t("qij.quality.import_success"));
      } catch { window.alert(t("qij.quality.import_error")); }
    });
    input.click();
  });
  root.querySelector("#qBtnResetProfile")?.addEventListener("click", async () => {
    if (!window.confirm(t("qij.quality.reset_profile_confirm"))) return;
    try { await _call("quality/reset_quality_profile"); window.alert(t("qij.quality.reset_profile_success")); }
    catch { window.alert(t("common.error")); }
  });

  // V7-port : Outliers drill-down
  root.querySelectorAll("[data-outlier-rid]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const rid = tr.dataset.outlierRid;
      showModal({
        title: t("qij.quality.outlier_modal_title"),
        body: t("qij.quality.outlier_modal_body", { rid: _esc(rid) }),
      });
    });
  });
}

function _statGrid(title, data) {
  if (!data || typeof data !== "object") return "";
  let html = `<div><strong style="color:var(--text-muted);font-size:var(--fs-xs);text-transform:uppercase;letter-spacing:0.05em">${_esc(title)}</strong>`;
  for (const [k, v] of Object.entries(data)) {
    html += `<div style="display:flex;justify-content:space-between;font-size:var(--fs-sm);padding:2px 0"><span>${_esc(k)}</span><span class="v5u-tabular-nums">${v}</span></div>`;
  }
  return html + "</div>";
}

function _rollupLabel(dim) {
  // V6-02 : labels via i18n.
  const map = {
    franchise: t("qij.quality.rollup.franchise"),
    decade: t("qij.quality.rollup.decade"),
    codec: t("qij.quality.rollup.codec"),
    era_grain: t("qij.quality.rollup.era_grain"),
    resolution: t("qij.quality.rollup.resolution"),
  };
  return map[dim] || dim;
}

/* ============================================================
 * TAB INTEGRATIONS (enrichi avec sync reports + libraries + Radarr upgrade)
 * ============================================================ */

const _iState = { containerRef: null, settings: null, statuses: {}, syncReports: {}, libraries: {} };

const INTEGRATIONS = [
  { id: "jellyfin", label: "Jellyfin", iconPath: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    enabledKey: "jellyfin_enabled", urlKey: "jellyfin_url", apiKeyKey: "jellyfin_api_key",
    testMethod: "integrations/test_jellyfin_connection", syncMethod: "get_jellyfin_sync_report", librariesMethod: "get_jellyfin_libraries" },
  { id: "plex", label: "Plex", iconPath: '<polygon points="5 3 19 12 5 21 5 3"/>',
    enabledKey: "plex_enabled", urlKey: "plex_url", apiKeyKey: "plex_token",
    testMethod: "integrations/test_plex_connection", syncMethod: "get_plex_sync_report", librariesMethod: null },
  { id: "radarr", label: "Radarr", iconPath: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    enabledKey: "radarr_enabled", urlKey: "radarr_url", apiKeyKey: "radarr_api_key",
    testMethod: "integrations/test_radarr_connection", syncMethod: "get_radarr_status", upgradeMethod: "request_radarr_upgrade" },
  { id: "tmdb", label: "TMDb", iconPath: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    enabledKey: null, urlKey: null, apiKeyKey: "tmdb_api_key", testMethod: "integrations/test_tmdb_key" },
];

export async function initIntegrations(container, _opts = {}) {
  if (!container) return;
  _iState.containerRef = container;
  container.innerHTML = `<div class="v5-qij-loading">${_esc(t("qij.loading_integrations"))}</div>`;
  try { _iState.settings = await _call("settings/get_settings"); }
  catch (e) { console.error("[qij-integ] settings:", e); }
  _integrationsRender();
}

export function unmountIntegrations() {
  if (_iState.containerRef) _iState.containerRef.innerHTML = "";
  _iState.containerRef = null;
}

function _integrationsRender() {
  const root = _iState.containerRef;
  if (!root) return;
  const s = _iState.settings || {};

  const cards = INTEGRATIONS.map((integ) => {
    const enabled = integ.enabledKey ? Boolean(s[integ.enabledKey]) : true;
    const url = integ.urlKey ? s[integ.urlKey] : null;
    const hasKey = integ.apiKeyKey ? Boolean(s[integ.apiKeyKey]) : true;
    const status = _iState.statuses[integ.id];
    const statusClass = status ? (status.ok ? "is-connected" : "is-error") : (enabled && hasKey ? "is-ready" : "is-disabled");
    const statusLabel = status
      ? (status.ok ? t("qij.integrations.status_connected") : t("qij.integrations.status_error"))
      : (enabled && hasKey ? t("qij.integrations.status_ready") : (enabled ? t("qij.integrations.status_not_configured") : t("qij.integrations.status_disabled")));
    const libraries = _iState.libraries[integ.id];
    const libCount = libraries ? (Array.isArray(libraries.libraries) ? libraries.libraries.length : libraries.length || 0) : null;

    return `<article class="v5-integ-card ${statusClass}" data-integ-id="${_esc(integ.id)}">
      <header class="v5-integ-card-header">
        <span class="v5-integ-card-icon">${_svg(integ.iconPath, 24)}</span>
        <h3 class="v5-integ-card-title">${_esc(integ.label)}</h3>
        <span class="v5-integ-card-status">${_esc(statusLabel)}</span>
      </header>
      <dl class="v5-film-data-list">
        ${url ? `<dt>${_esc(t("qij.integrations.url_label"))}</dt><dd class="v5u-truncate">${_esc(url)}</dd>` : ""}
        ${integ.apiKeyKey ? `<dt>${glossaryTooltip("API Key", "API Key")}</dt><dd>${hasKey ? "••••••••" : _esc(t("qij.integrations.key_undefined"))}</dd>` : ""}
        ${libCount != null ? `<dt>${_esc(t("qij.integrations.libraries_label"))}</dt><dd class="v5u-tabular-nums">${libCount}</dd>` : ""}
      </dl>
      ${status && status.message ? `<div class="v5-integ-card-message ${status.ok ? 'is-ok' : 'is-error'}" style="font-size:var(--fs-xs);padding:var(--sp-2);background:var(--surface-2);border-radius:var(--radius-sm);margin:var(--sp-2) 0;color:${status.ok ? 'var(--success)' : 'var(--danger)'}">${_esc(status.message)}</div>` : ""}
      <footer class="v5-integ-card-footer" style="display:flex;gap:var(--sp-2);flex-wrap:wrap">
        ${integ.testMethod ? `<button type="button" class="v5-btn v5-btn--sm" data-integ-test="${_esc(integ.id)}" ${!enabled && integ.enabledKey ? "disabled" : ""}>${_esc(t("qij.integrations.btn_test"))}</button>` : ""}
        ${integ.syncMethod && enabled ? `<button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-integ-sync="${_esc(integ.id)}">${_esc(t("qij.integrations.btn_check_sync"))}</button>` : ""}
        ${integ.librariesMethod && enabled ? `<button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-integ-libraries="${_esc(integ.id)}">${_esc(t("qij.integrations.btn_libraries"))}</button>` : ""}
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-integ-settings="${_esc(integ.id)}">${_esc(t("qij.integrations.btn_settings"))}</button>
      </footer>
    </article>`;
  }).join("");

  root.innerHTML = `<div class="v5-qij-shell">
    <header class="v5-qij-header">
      <h1 class="v5-qij-title">${_esc(t("qij.integrations.tab_title"))}</h1>
      <p class="v5u-text-muted">${_esc(t("qij.integrations.subtitle"))}</p>
    </header>
    <div class="v5-integ-grid">${cards}</div>
  </div>`;

  // Hooks : test connexion
  root.querySelectorAll("[data-integ-test]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.integTest;
      const integ = INTEGRATIONS.find((i) => i.id === id);
      if (!integ?.testMethod) return;
      btn.disabled = true; btn.textContent = t("qij.integrations.btn_testing");
      try {
        // Construire les params selon integ
        let params = {};
        if (id === "jellyfin") params = { url: s[integ.urlKey], api_key: s[integ.apiKeyKey], timeout_s: s.jellyfin_timeout_s || 10 };
        else if (id === "plex") params = { url: s[integ.urlKey], token: s[integ.apiKeyKey] };
        else if (id === "radarr") params = { url: s[integ.urlKey], api_key: s[integ.apiKeyKey] };
        else if (id === "tmdb") params = { api_key: s[integ.apiKeyKey], state_dir: "" };
        const result = await _call(integ.testMethod, params);
        // V2-02 : server_name/version proviennent du serveur tiers (Jellyfin/Plex/Radarr) → user-controlled.
        // Stockage en clair OK ici car _esc() est applique au render (ligne 436 : ${_esc(status.message)}).
        _iState.statuses[id] = { ok: !!(result && result.ok), message: result?.server_name ? `${result.server_name} v${result.version || "?"}` : (result?.message || (result?.ok ? "OK" : "Échec")) };
      } catch (e) { _iState.statuses[id] = { ok: false, message: String(e) }; }
      _integrationsRender();
    });
  });

  // V7-port : sync report (modale)
  root.querySelectorAll("[data-integ-sync]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.integSync;
      const integ = INTEGRATIONS.find((i) => i.id === id);
      if (!integ?.syncMethod) return;
      btn.disabled = true; btn.textContent = t("qij.integrations.btn_checking");
      try {
        // V7-fix CRIT-3 : passer run_id du dernier run dispo. Sans run_id le backend
        // utilise le dernier run "done" auto, qui peut etre absent (tout RUNNING/FAILED).
        // On lit d'abord global stats pour recuperer le run_id le plus recent.
        let lastRunId = null;
        try {
          const globalStats = await _call("get_global_stats", { limit_runs: 5 });
          const runs = (globalStats && globalStats.runs_summary) || [];
          lastRunId = runs.length > 0 ? runs[0].run_id : null;
        } catch (e) { /* fallback no run_id, backend cherchera */ }
        const params = lastRunId ? { run_id: lastRunId } : {};
        const result = await _call(integ.syncMethod, params);
        _showSyncReportModal(integ, result);
      } catch (e) {
        showModal({ title: t("qij.integrations.sync_error_title"), body: t("qij.integrations.sync_error_body", { detail: _esc(String(e)) }) });
      } finally {
        btn.disabled = false; btn.textContent = t("qij.integrations.btn_check_sync");
      }
    });
  });

  // V7-port : liste bibliothèques (Jellyfin)
  root.querySelectorAll("[data-integ-libraries]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.integLibraries;
      const integ = INTEGRATIONS.find((i) => i.id === id);
      if (!integ?.librariesMethod) return;
      btn.disabled = true; btn.textContent = t("qij.integrations.btn_loading");
      try {
        const result = await _call(integ.librariesMethod);
        _iState.libraries[id] = result;
        _showLibrariesModal(integ, result);
      } catch (e) {
        showModal({ title: t("qij.integrations.modal_error_title"), body: `<p>${_esc(String(e))}</p>` });
      } finally {
        btn.disabled = false; btn.textContent = t("qij.integrations.btn_libraries");
        _integrationsRender();
      }
    });
  });

  // Paramètres → settings
  root.querySelectorAll("[data-integ-settings]").forEach((btn) => {
    btn.addEventListener("click", () => { window.location.hash = "#/settings"; });
  });
}

function _showSyncReportModal(integ, data) {
  if (!data || !data.ok) {
    showModal({ title: `${_esc(integ.label)} — Sync`, body: `<p class="v5u-text-muted">${_esc(data?.message || "Données non disponibles.")}</p>` });
    return;
  }

  // V2-02 XSS hardening : tous les ${...} de valeurs user-controlled doivent passer par _esc(String(...)).
  // Les nombres (matched, length) sont safes mais on garde String() systematique par defense en profondeur.
  // Format selon integ
  let body = "";
  if (integ.id === "jellyfin" || integ.id === "plex") {
    const missing = data.missing_in_jellyfin || data.missing_in_plex || [];
    const ghosts = data.ghost_in_jellyfin || data.ghost_in_plex || [];
    const mismatches = data.metadata_mismatch || [];
    const matched = Number(data.matched || 0);
    const total = missing.length + ghosts.length + mismatches.length;
    const cls = total === 0 ? "var(--success)" : "var(--warning)";
    body = `<div style="padding:var(--sp-3);background:var(--surface-2);border-radius:var(--radius-md);margin-bottom:var(--sp-3);color:${cls}">
      <strong>${matched}</strong> films cohérents — <strong>${missing.length}</strong> manquants — <strong>${ghosts.length}</strong> fantômes — <strong>${mismatches.length}</strong> divergences
    </div>`;
    if (missing.length) {
      body += `<h4>Manquants dans ${_esc(integ.label)} (${missing.length})</h4><table class="v5-table"><thead><tr><th>Titre</th><th>Année</th><th>Chemin local</th></tr></thead><tbody>`;
      for (const m of missing.slice(0, 50)) {
        // V2-02 H3 : year peut etre une string user-controlled cote backend Jellyfin/Plex.
        body += `<tr><td>${_esc(String(m.title || ""))}</td><td>${_esc(String(m.year || ""))}</td><td class="v5u-text-muted v5u-truncate">${_esc(String(m.local_path || ""))}</td></tr>`;
      }
      body += `</tbody></table>`;
    }
    if (ghosts.length) {
      body += `<h4 style="margin-top:var(--sp-4)">Fantômes dans ${_esc(integ.label)} (${ghosts.length})</h4><table class="v5-table"><thead><tr><th>Titre</th><th>Année</th></tr></thead><tbody>`;
      for (const g of ghosts.slice(0, 50)) {
        body += `<tr><td>${_esc(String(g.title || ""))}</td><td>${_esc(String(g.year || ""))}</td></tr>`;
      }
      body += `</tbody></table>`;
    }
    if (mismatches.length) {
      body += `<h4 style="margin-top:var(--sp-4)">Divergences (${mismatches.length})</h4><table class="v5-table"><thead><tr><th>Champ</th><th>Local</th><th>${_esc(integ.label)}</th></tr></thead><tbody>`;
      for (const mm of mismatches.slice(0, 50)) {
        const localVal = mm.field === "title" ? mm.local_title : String(mm.local_year || "");
        const remoteVal = mm.field === "title" ? (mm.jellyfin_title || mm.plex_title) : String(mm.jellyfin_year || mm.plex_year || "");
        body += `<tr><td>${_esc(String(mm.field || ""))}</td><td>${_esc(String(localVal || ""))}</td><td>${_esc(String(remoteVal || ""))}</td></tr>`;
      }
      body += `</tbody></table>`;
    }
  } else if (integ.id === "radarr") {
    const matched = Number(data.matched_count || 0);
    const notInRadarr = data.not_in_radarr || [];
    const upgradeCandidates = data.upgrade_candidates || [];
    body = `<div style="padding:var(--sp-3);background:var(--surface-2);border-radius:var(--radius-md);margin-bottom:var(--sp-3)">
      <strong>${matched}</strong> films matchés — <strong>${notInRadarr.length}</strong> absents Radarr — <strong>${upgradeCandidates.length}</strong> upgrade possibles
    </div>`;
    if (upgradeCandidates.length) {
      body += `<h4>Candidats upgrade Radarr</h4><table class="v5-table"><thead><tr><th>Titre</th><th>Score actuel</th><th>Action</th></tr></thead><tbody>`;
      for (const c of upgradeCandidates.slice(0, 50)) {
        // V2-02 : c.score peut etre any depuis Radarr API → escape defensif
        body += `<tr><td>${_esc(String(c.title || ""))}</td><td class="v5u-tabular-nums">${_esc(String(c.score ?? "—"))}</td><td><button type="button" class="v5-btn v5-btn--sm" data-radarr-upgrade="${_esc(String(c.movie_id || c.tmdb_id || ""))}">Demander upgrade</button></td></tr>`;
      }
      body += `</tbody></table>`;
    }
    if (notInRadarr.length) {
      body += `<h4 style="margin-top:var(--sp-4)">Films absents de Radarr (${notInRadarr.length})</h4><ul>`;
      for (const f of notInRadarr.slice(0, 30)) body += `<li>${_esc(String(f.title || ""))} (${_esc(String(f.year || "?"))})</li>`;
      body += `</ul>`;
    }
  }

  showModal({ title: `${_esc(integ.label)} — Rapport de synchronisation`, body });

  // V2-01a : remplace setTimeout(100ms) par binding direct. showModal() appelle
  // document.body.appendChild() qui est synchrone : le DOM des boutons
  // [data-radarr-upgrade] est immediatement accessible. Le setTimeout etait un
  // workaround fragile (race avec le rendering du navigateur dans certains cas).
  document.querySelectorAll("[data-radarr-upgrade]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const movieId = btn.dataset.radarrUpgrade;
      btn.disabled = true; btn.textContent = "Demande...";
      try {
        const r = await _call("integrations/request_radarr_upgrade", { movie_id: movieId });
        btn.textContent = r?.ok ? "✓ Demandé" : "✗ Échec";
      } catch { btn.textContent = "✗ Erreur"; }
    });
  });
}

function _showLibrariesModal(integ, data) {
  if (!data || !data.ok) {
    showModal({ title: `${_esc(integ.label)} — Bibliothèques`, body: `<p class="v5u-text-muted">${_esc(data?.message || "Non disponibles.")}</p>` });
    return;
  }
  const libs = Array.isArray(data.libraries) ? data.libraries : [];
  let body = `<p class="v5u-text-muted">${libs.length} bibliothèque(s).</p>`;
  if (libs.length) {
    body += `<table class="v5-table"><thead><tr><th>Nom</th><th>Type</th><th>Items</th></tr></thead><tbody>`;
    for (const l of libs) {
      // V2-02 : ItemCount provient de Jellyfin API → potentiellement user-controlled (str).
      body += `<tr><td>${_esc(String(l.Name || l.name || "—"))}</td><td>${_esc(String(l.CollectionType || l.type || "—"))}</td><td class="v5u-tabular-nums">${_esc(String(l.ItemCount ?? l.item_count ?? "—"))}</td></tr>`;
    }
    body += `</tbody></table>`;
  }
  showModal({ title: `${_esc(integ.label)} — Bibliothèques`, body });
}

/* ============================================================
 * TAB JOURNAL (enrichi avec live polling, toggle, NFO export)
 * ============================================================ */

const _jState = {
  containerRef: null,
  runs: [],
  mode: "history", // "live" ou "history"
  activeRunId: null,
  selectedRunId: null,
  // V2-03 H6 : tri configurable des cards Journal (regression v4 -> v5 : table.js
  // sortable par date/score/statut perdue lors de la migration vers cards).
  // Cle : "date" | "score" | "status" — Direction : "desc" | "asc".
  sortKey: "date",
  sortDir: "desc",
};

// V6-02 : labels via i18n. labelKey vise "qij.journal.sort_options.*".
const _JOURNAL_SORT_OPTIONS = [
  { key: "date", dir: "desc", labelKey: "qij.journal.sort_options.date_desc" },
  { key: "date", dir: "asc", labelKey: "qij.journal.sort_options.date_asc" },
  { key: "score", dir: "desc", labelKey: "qij.journal.sort_options.score_desc" },
  { key: "score", dir: "asc", labelKey: "qij.journal.sort_options.score_asc" },
  { key: "status", dir: "asc", labelKey: "qij.journal.sort_options.status_asc" },
  { key: "status", dir: "desc", labelKey: "qij.journal.sort_options.status_desc" },
];

/**
 * Trie une liste de runs selon la cle/direction courante. Renvoie un nouvel array.
 * V2-03 : reintroduit la fonctionnalite de tri perdue lors de la migration table -> cards.
 */
function _sortRuns(runs, key, dir) {
  const arr = Array.isArray(runs) ? runs.slice() : [];
  const mul = dir === "asc" ? 1 : -1;
  const _ts = (r) => {
    const v = r.started_at || r.start_ts || r.started_ts || 0;
    const n = typeof v === "number" ? v : Date.parse(v);
    return Number.isFinite(n) ? n : 0;
  };
  arr.sort((a, b) => {
    if (key === "score") {
      const va = Number(a.avg_score ?? -Infinity);
      const vb = Number(b.avg_score ?? -Infinity);
      return (va - vb) * mul;
    }
    if (key === "status") {
      return String(a.status || "").localeCompare(String(b.status || ""), "fr") * mul;
    }
    // Defaut : date
    return (_ts(a) - _ts(b)) * mul;
  });
  return arr;
}

export async function initJournal(container, _opts = {}) {
  if (!container) return;
  _jState.containerRef = container;
  container.innerHTML = `<div class="v5-qij-loading">${_esc(t("qij.loading_journal"))}</div>`;

  // Detection run actif + chargement historique en parallele
  // V2-C R4-MEM-6 : signal de nav pour abort si l'utilisateur navigate ailleurs.
  const navSig = getNavSignal();
  const labels = ["/api/health", "get_global_stats"];
  const results = await Promise.allSettled([
    apiGet("/api/health"),
    _call("get_global_stats", { limit_runs: 50 }, { signal: navSig }),
  ]);
  const _val = (r) => (r && r.status === "fulfilled" && r.value ? (r.value.data || r.value) : null);
  const [health, stats] = results.map(_val);
  const failed = labels.filter((_, i) => results[i].status !== "fulfilled" && !isAbortError(results[i].reason));
  if (failed.length > 0) console.warn("[qij-journal] endpoints en echec:", failed);

  _jState.activeRunId = health?.active_run_id || null;
  _jState.runs = (stats && stats.runs_summary) || [];
  if (!_jState.selectedRunId && _jState.runs.length > 0) _jState.selectedRunId = _jState.runs[0].run_id;
  // Si run actif, basculer auto sur live
  if (_jState.activeRunId) _jState.mode = "live";

  _journalRender();
}

export function unmountJournal() {
  // V7-port : cleanup polling au unmount
  journalPoller.stop();
  if (_jState.containerRef) _jState.containerRef.innerHTML = "";
  _jState.containerRef = null;
}

function _journalRender() {
  const root = _jState.containerRef;
  if (!root) return;
  const runs = _jState.runs || [];

  // V6-02 : header subtitle adapte au pluriel via cles separees.
  const runWord = glossaryTooltip("Run", runs.length > 1 ? "runs" : "run");
  const subtitle = runs.length > 1
    ? t("qij.journal.header_subtitle_many", { count: runs.length, run: runWord })
    : t("qij.journal.header_subtitle_one", { count: runs.length, run: runWord });
  let html = `<div class="v5-qij-shell">
    <header class="v5-qij-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:var(--sp-3)">
      <div>
        <h1 class="v5-qij-title">${_esc(t("qij.journal.tab_title"))}</h1>
        <p class="v5u-text-muted">${subtitle}</p>
      </div>
      <!-- V7-port : toggle Live/Historique -->
      <div class="v5-qij-mode-toggle" role="tablist" style="display:flex;gap:var(--sp-2)">
        <button type="button" class="v5-btn v5-btn--sm ${_jState.mode === "live" ? "v5-btn--primary" : "v5-btn--ghost"}" data-journal-mode="live">
          ${_jState.activeRunId ? "<span style=\"display:inline-block;width:8px;height:8px;background:var(--success);border-radius:50%;margin-right:4px;animation:pulse 1.2s infinite\"></span>" : ""}${_esc(t("qij.journal.btn_live"))}
        </button>
        <button type="button" class="v5-btn v5-btn--sm ${_jState.mode === "history" ? "v5-btn--primary" : "v5-btn--ghost"}" data-journal-mode="history">${_esc(t("qij.journal.btn_history"))}</button>
      </div>
    </header>`;

  if (_jState.mode === "live") {
    html += _renderLiveSection();
  } else {
    html += _renderHistorySection();
  }

  html += `</div>`;
  root.innerHTML = html;
  _journalBindEvents(root);

  // Demarrer polling si live + run actif
  if (_jState.mode === "live" && _jState.activeRunId) {
    // V2-01c : guard isConnected sur chaque tick pour eviter d'ecrire dans un
    // container detache du DOM (vue unmount entre 2 ticks). Si root.isConnected
    // devient false, on stoppe le polling.
    const _isMounted = () => root && root.isConnected && _jState.containerRef === root;
    journalPoller.start(_jState.activeRunId, {
      onProgress: (idx, total, etaS, current) => {
        if (!_isMounted()) { journalPoller.stop(); return; }
        const txt = root.querySelector("#journal-progress-text");
        const fill = root.querySelector("#journal-progress-fill");
        if (txt) {
          if (total > 0) {
            const pct = Math.round((idx / total) * 100);
            const base = t("qij.journal.progress_pct", { idx, total, pct });
            const eta = etaS > 0 ? t("qij.journal.progress_eta", { eta: _fmtDuration(etaS) }) : "";
            txt.textContent = `${base}${eta}${current ? ` — ${current}` : ""}`;
            if (fill) fill.style.width = `${pct}%`;
          } else {
            txt.textContent = t("qij.journal.found_films", { count: idx });
          }
        }
      },
      onLogsAppend: (entries) => {
        if (!_isMounted()) { journalPoller.stop(); return; }
        const box = root.querySelector("#journal-logs-box");
        if (!box) return;
        for (const entry of entries) {
          const line = document.createElement("div");
          line.className = "log-line";
          const level = String(entry.level || "INFO").toUpperCase();
          if (level === "ERROR") line.classList.add("log-error");
          else if (level === "WARN" || level === "WARNING") line.classList.add("log-warn");
          line.textContent = `[${entry.ts || ""}] ${level}: ${entry.msg || ""}`;
          box.appendChild(line);
        }
        box.scrollTop = box.scrollHeight;
      },
      onDone: () => {
        if (!_isMounted()) { journalPoller.stop(); return; }
        const box = root.querySelector("#journal-logs-box");
        if (box) {
          const end = document.createElement("div");
          end.className = "log-line log-end";
          end.textContent = t("qij.journal.run_finished");
          box.appendChild(end);
          box.scrollTop = box.scrollHeight;
        }
        _jState.activeRunId = null;
      },
    });
  } else {
    journalPoller.stop();
  }
}

function _renderLiveSection() {
  if (!_jState.activeRunId) {
    return `<div class="card" style="margin-top:var(--sp-3)">
      <p class="v5u-text-muted">${_esc(t("qij.journal.no_active_run"))}</p>
      <button type="button" class="v5-btn v5-btn--primary" onclick="window.location.hash='#/processing?step=scan'">${_esc(t("qij.journal.btn_scan"))}</button>
    </div>`;
  }
  return `<div class="card" style="margin-top:var(--sp-3)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--sp-3)">
      <h3>${_esc(t("qij.journal.run_in_progress"))} <code style="color:var(--accent)">${_esc(_jState.activeRunId)}</code></h3>
      <button type="button" class="v5-btn v5-btn--sm" id="btnJournalCancel" style="background:var(--danger);color:#fff">${_esc(t("qij.journal.btn_cancel"))}</button>
    </div>
    <div class="progress-bar" style="background:var(--surface-2);height:8px;border-radius:4px;overflow:hidden;margin-bottom:var(--sp-2)">
      <div id="journal-progress-fill" style="width:0%;height:100%;background:var(--accent);transition:width 0.3s"></div>
    </div>
    <p id="journal-progress-text" class="v5u-text-muted" style="font-size:var(--fs-sm);margin-bottom:var(--sp-3)">${_esc(t("qij.journal.init"))}</p>
    <div id="journal-logs-box" class="logs-box" style="max-height:400px;overflow-y:auto;background:var(--bg);padding:var(--sp-3);border-radius:var(--radius-md);font-family:monospace;font-size:var(--fs-xs);border:1px solid var(--border-1)"></div>
  </div>`;
}

function _renderHistorySection() {
  const runs = _jState.runs || [];
  if (runs.length === 0) {
    return `<div class="v5-library-empty" style="margin-top:var(--sp-3)">${_esc(t("qij.journal.no_runs"))}</div>`;
  }

  // Card actions exports pour run sélectionné
  let html = `<div class="card" style="margin-top:var(--sp-3);margin-bottom:var(--sp-3)">
    <div style="display:flex;gap:var(--sp-2);align-items:center;flex-wrap:wrap">
      <span>${_esc(t("qij.journal.selected_run_label"))} <strong><code id="journal-selected-label">${_jState.selectedRunId ? _esc(String(_jState.selectedRunId).slice(0, 20)) : _esc(t("qij.journal.selected_none"))}</code></strong></span>
      <button type="button" class="v5-btn v5-btn--sm" data-export-fmt="json">JSON</button>
      <button type="button" class="v5-btn v5-btn--sm" data-export-fmt="csv">CSV</button>
      <button type="button" class="v5-btn v5-btn--sm" data-export-fmt="html">HTML</button>
      <button type="button" class="v5-btn v5-btn--sm" id="btnJournalExportNfo">${_esc(t("qij.journal.btn_export_nfo"))}</button>
      <span id="journal-export-msg" style="margin-left:var(--sp-2);font-size:var(--fs-xs);color:var(--text-muted)"></span>
    </div>
  </div>`;

  // V2-03 H6 : selecteur "Trier par" pour cards Journal (regression tri table v4).
  const currentSortValue = `${_jState.sortKey}:${_jState.sortDir}`;
  const sortOptions = _JOURNAL_SORT_OPTIONS.map((opt) => {
    const val = `${opt.key}:${opt.dir}`;
    const sel = val === currentSortValue ? " selected" : "";
    const lbl = opt.labelKey ? t(opt.labelKey) : (opt.label || val);
    return `<option value="${_esc(val)}"${sel}>${_esc(lbl)}</option>`;
  }).join("");
  html += `<div style="display:flex;gap:var(--sp-2);align-items:center;margin-bottom:var(--sp-3)">
    <label for="journal-sort-select" style="font-size:var(--fs-sm);color:var(--text-muted)">${_esc(t("qij.journal.sort_label"))}</label>
    <select id="journal-sort-select" class="v5-select" aria-label="${_esc(t("qij.journal.sort_aria"))}">${sortOptions}</select>
  </div>`;

  const sortedRuns = _sortRuns(runs, _jState.sortKey, _jState.sortDir);
  // V7-port : table cards (style v5 des journal cards)
  html += `<div class="v5-qij-journal-list">`;
  html += sortedRuns.map((r) => _journalRunCard(r)).join("");
  html += `</div>`;

  return html;
}

function _journalRunCard(r) {
  const rid = r.run_id || "—";
  const status = String(r.status || "");
  const scoreAvg = r.avg_score != null ? Math.round(Number(r.avg_score)) : "—";
  const started = r.started_at || r.start_ts || r.started_ts;
  const total = r.total_rows || 0;
  const err = r.errors || 0;
  const isSelected = rid === _jState.selectedRunId;
  const statusClass = status === "done" ? "is-done" : status === "error" ? "is-error" : status === "cancelled" ? "is-cancelled" : "is-running";
  return `<article class="v5-qij-journal-card ${statusClass}" data-run-card="${_esc(rid)}" style="cursor:pointer;${isSelected ? 'border:2px solid var(--accent)' : ''}">
    <header class="v5-qij-journal-header">
      <div>
        <code class="v5-qij-journal-id">${_esc(rid)}</code>
        <div class="v5-qij-journal-meta">${_esc(_fmtDate(started))}</div>
      </div>
      <span class="v5-qij-journal-status">${_esc(status || "—")}</span>
    </header>
    <dl class="v5-qij-journal-kpis">
      <div><dt>${_esc(t("qij.journal.kpi_films"))}</dt><dd class="v5u-tabular-nums">${total}</dd></div>
      <div><dt>${glossaryTooltip("Score perceptuel", t("qij.journal.kpi_avg_score"))}</dt><dd class="v5u-tabular-nums">${scoreAvg}</dd></div>
      ${err > 0 ? `<div><dt>${_esc(t("qij.journal.kpi_errors"))}</dt><dd class="v5u-tabular-nums" style="color:var(--warning)">${err}</dd></div>` : ""}
    </dl>
  </article>`;
}

function _journalBindEvents(root) {
  // Toggle mode live/history
  root.querySelectorAll("[data-journal-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.journalMode;
      if (mode === _jState.mode) return;
      _jState.mode = mode;
      _journalRender();
    });
  });

  // Bouton annuler run live
  const btnCancel = root.querySelector("#btnJournalCancel");
  if (btnCancel) {
    btnCancel.addEventListener("click", async () => {
      btnCancel.disabled = true;
      try { await _call("run/cancel_run", { run_id: _jState.activeRunId }); }
      catch { btnCancel.disabled = false; }
    });
  }

  // Selection card run (history mode)
  root.querySelectorAll("[data-run-card]").forEach((card) => {
    card.addEventListener("click", () => {
      _jState.selectedRunId = card.dataset.runCard;
      const lbl = root.querySelector("#journal-selected-label");
      if (lbl) lbl.textContent = String(_jState.selectedRunId).slice(0, 20);
      // Re-render cards pour mettre à jour le visuel sélectionné
      root.querySelectorAll("[data-run-card]").forEach((c) => {
        c.style.border = c.dataset.runCard === _jState.selectedRunId ? "2px solid var(--accent)" : "";
      });
    });
  });

  // Export buttons
  root.querySelectorAll("[data-export-fmt]").forEach((btn) => {
    btn.addEventListener("click", () => _journalExportRun(btn.dataset.exportFmt));
  });

  // V7-port : Export NFO
  root.querySelector("#btnJournalExportNfo")?.addEventListener("click", _journalExportNfo);

  // V2-03 H6 : selecteur "Trier par" pour cards Journal.
  const sortSelect = root.querySelector("#journal-sort-select");
  if (sortSelect) {
    sortSelect.addEventListener("change", () => {
      const [key, dir] = String(sortSelect.value || "date:desc").split(":");
      _jState.sortKey = key || "date";
      _jState.sortDir = dir === "asc" ? "asc" : "desc";
      _journalRender();
    });
  }
}

async function _journalExportRun(fmt) {
  if (!_jState.selectedRunId) return;
  const msg = document.getElementById("journal-export-msg");
  if (msg) { msg.textContent = t("qij.journal.exporting"); msg.style.color = "var(--text-muted)"; }
  try {
    const res = await _call("run/export_run_report", { run_id: _jState.selectedRunId, fmt });
    if (res?.content) {
      const content = typeof res.content === "string" ? res.content : JSON.stringify(res.content, null, 2);
      const mime = fmt === "json" ? "application/json" : fmt === "csv" ? "text/csv" : "text/html";
      const blob = new Blob([content], { type: mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `${_jState.selectedRunId}.${fmt}`; a.click();
      URL.revokeObjectURL(url);
      if (msg) { msg.textContent = t("qij.journal.export_success"); msg.style.color = "var(--success)"; }
    } else {
      if (msg) { msg.textContent = res?.message || t("qij.journal.export_no_data"); msg.style.color = "var(--danger)"; }
    }
  } catch { if (msg) { msg.textContent = t("qij.journal.export_error_network"); msg.style.color = "var(--danger)"; } }
}

async function _journalExportNfo() {
  if (!_jState.selectedRunId) return;
  const msg = document.getElementById("journal-export-msg");
  if (msg) { msg.textContent = t("qij.journal.export_nfo_in_progress"); msg.style.color = "var(--text-muted)"; }
  try {
    const res = await _call("export_run_nfo", { run_id: _jState.selectedRunId, overwrite: false, dry_run: false });
    if (msg) {
      msg.textContent = res?.message || t("qij.journal.export_nfo_success", { count: res?.created || 0 });
      msg.style.color = "var(--success)";
    }
  } catch { if (msg) { msg.textContent = t("common.error_network").replace(/^✗\s*/, "✗ "); msg.style.color = "var(--danger)"; } }
}

/* ============================================================
 * VUE QIJ CONSOLIDEE (parent avec tabs)
 * ============================================================ */

const _qijState = {
  containerRef: null,
  activeTab: "quality",
  // V2-01b : compteur de "generation" pour annuler les mounts obsoletes lors de
  // tab switching rapide. Si user clique tab1 -> tab2 -> tab1 vite, le fetch
  // tab1 (lent) revient APRES tab2 -> render incorrect. La generation incremente
  // a chaque switch et chaque mount verifie qu'il est toujours la generation courante.
  mountGen: 0,
};

export async function initQij(container, opts = {}) {
  if (!container) return;
  _qijState.containerRef = container;
  // V2-D (a11y) : conteneur ARIA-live -> annonce "chargement" puis "termine".
  container.setAttribute("aria-busy", "true");
  // Lecture du tab depuis hash query param "?tab=xxx" si fourni
  let tabFromHash = "";
  try {
    const m = window.location.hash.match(/[?&]tab=([^&]+)/);
    if (m) tabFromHash = decodeURIComponent(m[1]);
  } catch { /* noop */ }
  // V7-fix CRIT-2 : prioriser tabFromHash sur opts.tab. Cas concret :
  // /quality?tab=journal → router passe opts.tab="quality" (alias) et hash dit
  // tab=journal → AVANT le fix: opts.tab gagnait → user voyait Quality au lieu
  // de Journal. APRES : tabFromHash gagne quand present.
  _qijState.activeTab = tabFromHash || opts.tab || "quality";
  if (!["quality", "integrations", "journal"].includes(_qijState.activeTab)) _qijState.activeTab = "quality";

  container.innerHTML = `<div class="v5-qij-tabs-wrap">
    <div class="v5-qij-tabs" role="tablist" aria-label="${_esc(t("qij.tabs.aria_label"))}" style="display:flex;gap:var(--sp-2);margin-bottom:var(--sp-4);border-bottom:1px solid var(--border-1);padding-bottom:var(--sp-3)">
      <button type="button" role="tab" data-qij-tab="quality" class="v5-btn v5-btn--sm ${_qijState.activeTab === "quality" ? "v5-btn--primary is-active" : "v5-btn--ghost"}">${_esc(t("qij.tabs.quality"))}</button>
      <button type="button" role="tab" data-qij-tab="integrations" class="v5-btn v5-btn--sm ${_qijState.activeTab === "integrations" ? "v5-btn--primary is-active" : "v5-btn--ghost"}">${_esc(t("qij.tabs.integrations"))}</button>
      <button type="button" role="tab" data-qij-tab="journal" class="v5-btn v5-btn--sm ${_qijState.activeTab === "journal" ? "v5-btn--primary is-active" : "v5-btn--ghost"}">${_esc(t("qij.tabs.journal"))}</button>
    </div>
    <div id="v5QijQualityPanel" role="tabpanel" ${_qijState.activeTab !== "quality" ? "hidden" : ""}></div>
    <div id="v5QijIntegrationsPanel" role="tabpanel" ${_qijState.activeTab !== "integrations" ? "hidden" : ""}></div>
    <div id="v5QijJournalPanel" role="tabpanel" ${_qijState.activeTab !== "journal" ? "hidden" : ""}></div>
  </div>`;

  await _qijMountActive(opts);
  // V2-D (a11y) : aria-busy revient a false apres le mount initial.
  container.setAttribute("aria-busy", "false");

  container.querySelectorAll("[data-qij-tab]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const tab = btn.dataset.qijTab;
      if (tab === _qijState.activeTab) return;
      // Cleanup unmount du tab actuel pour eviter memory leaks (surtout journal polling)
      if (_qijState.activeTab === "journal") unmountJournal();
      else if (_qijState.activeTab === "quality") unmountQuality();
      else if (_qijState.activeTab === "integrations") unmountIntegrations();

      _qijState.activeTab = tab;
      container.querySelectorAll("[data-qij-tab]").forEach((b) => {
        const isActive = b.dataset.qijTab === tab;
        b.classList.toggle("is-active", isActive);
        b.classList.toggle("v5-btn--primary", isActive);
        b.classList.toggle("v5-btn--ghost", !isActive);
      });
      ["quality", "integrations", "journal"].forEach((t) => {
        const panel = container.querySelector(`#v5Qij${t.charAt(0).toUpperCase() + t.slice(1)}Panel`);
        if (panel) panel.hidden = (t !== tab);
      });
      await _qijMountActive(opts);
    });
  });
}

async function _qijMountActive(opts) {
  const container = _qijState.containerRef;
  if (!container) return;
  // V2-01b : capture la generation au debut. Si une nouvelle generation a demarre
  // pendant l'await (tab switching rapide), on annule ce mount obsolete.
  const gen = ++_qijState.mountGen;
  const targetTab = _qijState.activeTab;
  const stillCurrent = () => gen === _qijState.mountGen && _qijState.activeTab === targetTab && _qijState.containerRef === container;
  if (targetTab === "quality") {
    const panel = container.querySelector("#v5QijQualityPanel");
    await initQuality(panel, opts);
    if (!stillCurrent()) {
      // Le tab a change pendant le fetch : on cleanup le panel obsolete pour eviter
      // que son render ecrase le tab desormais actif.
      unmountQuality();
    }
  } else if (targetTab === "integrations") {
    const panel = container.querySelector("#v5QijIntegrationsPanel");
    await initIntegrations(panel, opts);
    if (!stillCurrent()) unmountIntegrations();
  } else if (targetTab === "journal") {
    const panel = container.querySelector("#v5QijJournalPanel");
    await initJournal(panel, opts);
    if (!stillCurrent()) unmountJournal();
  }
}

export function unmountQij() {
  unmountQuality();
  unmountIntegrations();
  unmountJournal();
  if (_qijState.containerRef) _qijState.containerRef.innerHTML = "";
  _qijState.containerRef = null;
}
