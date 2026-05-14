/* views/qij-v5.js — v7.6.0 Vague 7 (V5bis-03 ES module port)
 * Regroupe les 3 vues refondues Qualite / Integrations / Journal.
 *
 * Chaque vue est montee via overlay plein-ecran (pattern Vague 4/5/6).
 *
 * API publique (ES module exports) :
 *   initQuality(container, opts?)
 *   initIntegrations(container, opts?)
 *   initJournal(container, opts?)
 *   initQij(container, opts?) — vue parent consolidee avec tabs
 *
 * V5bis-03 : conversion 3 IIFE -> ES module + apiPost wrapper REST.
 * Preserve V5A : V1-05 EmptyState CTA + V3-03 Glossary + V2-08 Skeleton.
 */

import { apiPost, escapeHtml } from "./_v5_helpers.js";
import { glossaryTooltip } from "../dashboard/components/glossary-tooltip.js";
import { buildEmptyState, bindEmptyStateCta } from "../dashboard/components/empty-state.js";

/* ============================================================
 * Helpers prives
 * ============================================================ */

async function _call(method, params) {
  const res = await apiPost(method, params);
  return res?.data ?? null;
}

function _svg(pathContent, size) {
  const s = size || 18;
  return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
}

function _fmtDate(ts) {
  // V6-04 : datetime locale-aware via core/format.js (window.formatDateTime).
  const n = Number(ts) || 0;
  if (n <= 0) return "—";
  if (typeof window.formatDateTime === "function") return window.formatDateTime(ts);
  return new Date(n * 1000).toLocaleString();
}

/* ============================================================
 * VUE QUALITE V5
 * ============================================================ */

// V-4 audit visuel 20260429 : helpers pour detecter empty states.
function _hasDataInDistribution(dist) {
  if (!dist || typeof dist !== "object") return false;
  const counts = dist.counts || dist;
  if (!counts || typeof counts !== "object") return false;
  return Object.values(counts).some((v) => Number(v) > 0);
}

function _hasDataInTrend(trend) {
  if (!trend) return false;
  const points = Array.isArray(trend) ? trend : (trend.points || trend.values || []);
  return Array.isArray(points) && points.length >= 2;
}

const _qState = {
  containerRef: null,
  globalStats: null,
  rollupBy: "franchise",
  rollupData: null,
};

// V5A-06 V2-08 : skeleton complet au boot pour eviter le flash blanc
// pendant Promise.allSettled sur 2 endpoints.
function _renderQualitySkeleton(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="v5-qij-skeleton" aria-busy="true" aria-label="Chargement Qualite">
      <div class="v5-skeleton-section">
        <div class="v5-skeleton-title"></div>
        <div class="v5-skeleton-grid">
          ${"<div class='v5-skeleton-card'></div>".repeat(6)}
        </div>
      </div>
      <div class="v5-skeleton-section">
        <div class="v5-skeleton-table">
          ${"<div class='v5-skeleton-row'></div>".repeat(8)}
        </div>
      </div>
    </div>
  `;
}

// V5A-06 V1-05 : empty state actionnable quand aucun film n'est analyse.
function _renderQualityEmpty(container) {
  if (!container) return;
  container.innerHTML = buildEmptyState({
    icon: "search",
    title: "Aucune analyse qualite disponible",
    message: "Lancez un scan + une analyse pour voir le score perceptuel des films.",
    ctaLabel: "Lancer un scan",
    ctaRoute: "home",
    testId: "qij-v5-quality-empty-cta",
  });
  bindEmptyStateCta(container, () => {
    if (typeof window !== "undefined" && typeof window.navigateTo === "function") {
      window.navigateTo("home");
    } else if (typeof window !== "undefined") {
      window.location.hash = "#/processing?step=scan";
    }
  });
}

export async function initQuality(container, _opts = {}) {
  if (!container) return;
  _qState.containerRef = container;
  _renderQualitySkeleton(container);
  await _qualityFetchAll();
  _qualityRender();
}

export function unmountQuality() {
  if (_qState.containerRef) _qState.containerRef.innerHTML = "";
  _qState.containerRef = null;
}

async function _qualityFetchAll() {
  // Audit ID-ROB-002 : Promise.allSettled pour qu'un endpoint en echec
  // (rollup par exemple) ne masque pas les stats globales (et inversement).
  const labels = ["get_global_stats", "get_scoring_rollup"];
  const results = await Promise.allSettled([
    _call("get_global_stats"),
    _call("library/get_scoring_rollup", { by: _qState.rollupBy, limit: 20, run_id: null }),
  ]);
  const _val = (r) => (r && r.status === "fulfilled" ? r.value : null);
  const [stats, rollup] = results.map(_val);
  const failed = labels.filter((_, i) => results[i].status !== "fulfilled");
  if (failed.length > 0) console.warn("[quality-v5] endpoints en echec:", failed);
  _qState.globalStats = stats;
  _qState.rollupData = rollup;
}

function _qualityRender() {
  const root = _qState.containerRef;
  if (!root) return;
  const stats = _qState.globalStats || {};
  const dist = stats.v2_tier_distribution;
  const trend = stats.trend_30days;

  // V5A-06 V1-05 : si aucun film analyse, afficher l'empty state CTA.
  const totalFilms = Number(stats.total_films || 0);
  const hasData = _hasDataInDistribution(dist) || _hasDataInTrend(trend) || totalFilms > 0;
  if (!hasData) {
    _renderQualityEmpty(root);
    return;
  }

  root.innerHTML = `
    <div class="v5-qij-shell">
      <header class="v5-qij-header">
        <h1 class="v5-qij-title">Qualite</h1>
        <p class="v5u-text-muted">Distribution V2, tendance 30 jours, regroupement par dimension.</p>
      </header>

      <section class="v5-qij-charts" id="quality-charts">
        <div class="v5-qij-chart-wrap">
          <h2 class="v5-qij-section-title">Distribution ${glossaryTooltip("Tier", "tiers")}</h2>
          <div id="quality-donut"></div>
        </div>
        <div class="v5-qij-chart-wrap">
          <h2 class="v5-qij-section-title">Tendance ${glossaryTooltip("Score perceptuel")} 30 jours</h2>
          <div id="quality-line"></div>
        </div>
      </section>

      <section class="v5-qij-rollup">
        <header class="v5-qij-rollup-header">
          <h2 class="v5-qij-section-title">Scoring par dimension</h2>
          <div class="v5-qij-rollup-controls" role="tablist" aria-label="Dimension">
            ${["franchise", "decade", "codec", "era_grain", "resolution"].map((d) => `
              <button type="button" class="v5-btn v5-btn--sm ${d === _qState.rollupBy ? 'v5-btn--primary' : 'v5-btn--ghost'}"
                      data-rollup-by="${escapeHtml(d)}">
                ${escapeHtml(_rollupLabel(d))}
              </button>
            `).join("")}
          </div>
        </header>
        <div id="quality-rollup-table"></div>
      </section>
    </div>
  `;

  // Mount charts (composants Vague 2)
  // V-4 audit visuel 20260429 : afficher un empty state si pas de donnees
  // au lieu de laisser les divs vides (sentiment d'incompletude visuelle).
  const donutHost = document.getElementById("quality-donut");
  const lineHost = document.getElementById("quality-line");
  if (typeof window !== "undefined" && window.HomeCharts && dist && _hasDataInDistribution(dist)) {
    window.HomeCharts.renderDonut(donutHost, dist);
  } else if (donutHost) {
    donutHost.innerHTML = `<div class="v5-chart-empty">Aucune analyse de qualite disponible. Lancez un scan pour voir la distribution.</div>`;
  }
  if (typeof window !== "undefined" && window.HomeCharts && trend && _hasDataInTrend(trend)) {
    window.HomeCharts.renderLine(lineHost, trend);
  } else if (lineHost) {
    lineHost.innerHTML = `<div class="v5-chart-empty">Aucune tendance sur 30 jours. Plusieurs runs sont necessaires pour afficher l'evolution.</div>`;
  }

  // Rollup
  _qualityRenderRollup();

  // Bind dimension toggle
  root.querySelectorAll("[data-rollup-by]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      _qState.rollupBy = btn.dataset.rollupBy;
      try {
        _qState.rollupData = await _call("library/get_scoring_rollup", {
          by: _qState.rollupBy,
          limit: 20,
          run_id: null,
        });
      } catch (e) {
        console.error("[quality-v5] rollup:", e);
      }
      _qualityRender();
    });
  });
}

function _qualityRenderRollup() {
  const host = document.getElementById("quality-rollup-table");
  if (!host) return;
  const groups = (_qState.rollupData && _qState.rollupData.groups) || [];
  if (groups.length === 0) {
    host.innerHTML = `<div class="v5-library-empty">Aucune donnee pour cette dimension.</div>`;
    return;
  }
  const rows = groups.map((g) => {
    const avg = g.avg_score != null ? Math.round(Number(g.avg_score)) : "—";
    const d = g.tier_distribution || {};
    const bars = ["platinum", "gold", "silver", "bronze", "reject"].map((t) => {
      const c = Number(d[t] || 0);
      if (c === 0) return "";
      const pct = g.count > 0 ? (c / g.count) * 100 : 0;
      return `<span class="v5-qij-dist-seg v5-qij-dist-seg--${escapeHtml(t)}" style="width:${pct.toFixed(1)}%" title="${escapeHtml(t)}: ${c}"></span>`;
    }).join("");
    return `
      <tr>
        <td class="v5-qij-rollup-name v5u-truncate">${escapeHtml(g.group_name)}</td>
        <td class="v5u-tabular-nums">${g.count}</td>
        <td class="v5u-tabular-nums"><strong>${avg}</strong></td>
        <td>
          <div class="v5-qij-dist-bar" aria-label="Distribution tiers">${bars}</div>
        </td>
      </tr>
    `;
  }).join("");

  host.innerHTML = `
    <div class="v5-qij-rollup-wrap">
      <table class="v5-table">
        <thead><tr>
          <th>${escapeHtml(_rollupLabel(_qState.rollupBy))}</th>
          <th>Films</th>
          <th>${glossaryTooltip("Score perceptuel", "Score moyen")}</th>
          <th>Distribution ${glossaryTooltip("Tier", "tiers")}</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function _rollupLabel(dim) {
  return {
    franchise: "Franchise",
    decade: "Decennie",
    codec: "Codec",
    era_grain: "Ere grain",
    resolution: "Resolution",
    director: "Realisateur",
  }[dim] || dim;
}

/* ============================================================
 * VUE INTEGRATIONS V5
 * ============================================================ */

const _iState = {
  containerRef: null,
  settings: null,
  statuses: {},
};

const INTEGRATIONS = [
  {
    id: "jellyfin",
    label: "Jellyfin",
    iconPath: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    enabledKey: "jellyfin_enabled",
    urlKey: "jellyfin_url",
    apiKeyKey: "jellyfin_api_key",
    testMethod: "integrations/test_jellyfin_connection",
  },
  {
    id: "plex",
    label: "Plex",
    iconPath: '<polygon points="5 3 19 12 5 21 5 3"/>',
    enabledKey: "plex_enabled",
    urlKey: "plex_url",
    apiKeyKey: "plex_token",
    testMethod: "integrations/test_plex_connection",
  },
  {
    id: "radarr",
    label: "Radarr",
    iconPath: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    enabledKey: "radarr_enabled",
    urlKey: "radarr_url",
    apiKeyKey: "radarr_api_key",
    testMethod: "integrations/test_radarr_connection",
  },
  {
    id: "tmdb",
    label: "TMDb",
    iconPath: '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    enabledKey: null,  // toujours active
    urlKey: null,
    apiKeyKey: "tmdb_api_key",
    testMethod: null,
  },
];

export async function initIntegrations(container, _opts = {}) {
  if (!container) return;
  _iState.containerRef = container;
  container.innerHTML = `<div class="v5-qij-loading">Chargement Integrations...</div>`;
  try {
    _iState.settings = await _call("settings/get_settings");
  } catch (e) {
    console.error("[integrations-v5] settings:", e);
  }
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
    const statusClass = status
      ? (status.ok ? "is-connected" : "is-error")
      : (enabled && hasKey ? "is-ready" : "is-disabled");
    const statusLabel = status
      ? (status.ok ? "Connecte" : "Erreur")
      : (enabled && hasKey ? "Pret" : (enabled ? "Non configure" : "Desactive"));

    return `
      <article class="v5-integ-card ${statusClass}">
        <header class="v5-integ-card-header">
          <span class="v5-integ-card-icon">${_svg(integ.iconPath, 24)}</span>
          <h3 class="v5-integ-card-title">${escapeHtml(integ.label)}</h3>
          <span class="v5-integ-card-status">${escapeHtml(statusLabel)}</span>
        </header>
        <dl class="v5-film-data-list">
          ${url ? `<dt>URL</dt><dd class="v5u-truncate">${escapeHtml(url)}</dd>` : ""}
          ${integ.apiKeyKey ? `<dt>${glossaryTooltip("API Key", "API Key")}</dt><dd>${hasKey ? "****" : "(non definie)"}</dd>` : ""}
        </dl>
        ${status && status.message ? `<div class="v5-integ-card-message ${status.ok ? 'is-ok' : 'is-error'}">${escapeHtml(status.message)}</div>` : ""}
        <footer class="v5-integ-card-footer">
          ${integ.testMethod ? `
            <button type="button" class="v5-btn v5-btn--sm v5-btn--secondary"
                    data-integ-test="${escapeHtml(integ.id)}" ${!enabled ? "disabled" : ""}>
              Tester la connexion
            </button>
          ` : ""}
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-integ-settings="${escapeHtml(integ.id)}">
            Parametres
          </button>
        </footer>
      </article>
    `;
  }).join("");

  root.innerHTML = `
    <div class="v5-qij-shell">
      <header class="v5-qij-header">
        <h1 class="v5-qij-title">Integrations</h1>
        <p class="v5u-text-muted">Connexions aux services externes (Jellyfin, Plex, Radarr, TMDb).</p>
      </header>
      <div class="v5-integ-grid">${cards}</div>
    </div>
  `;

  root.querySelectorAll("[data-integ-test]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.integTest;
      const integ = INTEGRATIONS.find((i) => i.id === id);
      if (!integ || !integ.testMethod) return;
      btn.disabled = true;
      btn.textContent = "Test en cours...";
      try {
        const result = await _call(integ.testMethod);
        _iState.statuses[id] = {
          ok: Boolean(result && result.ok),
          message: result?.message || (result?.ok ? "Connexion OK" : "Erreur"),
        };
      } catch (e) {
        _iState.statuses[id] = { ok: false, message: String(e) };
      }
      _integrationsRender();
    });
  });

  root.querySelectorAll("[data-integ-settings]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (typeof window !== "undefined" && typeof window.navigateTo === "function") {
        window.navigateTo("settings-v5/integrations");
      }
    });
  });
}

/* ============================================================
 * VUE JOURNAL V5 (ex-history)
 * ============================================================ */

const _jState = {
  containerRef: null,
  runs: [],
};

export async function initJournal(container, _opts = {}) {
  if (!container) return;
  _jState.containerRef = container;
  container.innerHTML = `<div class="v5-qij-loading">Chargement Journal...</div>`;
  try {
    const result = await _call("get_global_stats");
    _jState.runs = (result && result.runs_summary) || [];
  } catch (e) {
    console.error("[journal-v5] fetch:", e);
  }
  _journalRender();
}

export function unmountJournal() {
  if (_jState.containerRef) _jState.containerRef.innerHTML = "";
  _jState.containerRef = null;
}

function _journalRender() {
  const root = _jState.containerRef;
  if (!root) return;
  const runs = _jState.runs || [];
  const total = runs.length;

  root.innerHTML = `
    <div class="v5-qij-shell">
      <header class="v5-qij-header">
        <h1 class="v5-qij-title">Journal</h1>
        <p class="v5u-text-muted">${total} ${glossaryTooltip("Run", total > 1 ? "runs" : "run")} enregistre${total > 1 ? "s" : ""}. Exports CSV / HTML / NFO disponibles par run.</p>
      </header>
      ${runs.length === 0 ? `
        <div class="v5-library-empty">Aucun run enregistre.</div>
      ` : `
        <div class="v5-qij-journal-list">
          ${runs.map((r) => _journalRunCard(r)).join("")}
        </div>
      `}
    </div>
  `;

  root.querySelectorAll("[data-export-run]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const runId = btn.dataset.exportRun;
      const fmt = btn.dataset.exportFmt || "json";
      btn.disabled = true;
      btn.textContent = "Export...";
      try {
        const result = await _call("run/export_run_report", { run_id: runId, fmt });
        btn.textContent = result?.ok ? "OK" : "Erreur";
      } catch (_e) {
        btn.textContent = "Erreur";
      }
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = fmt.toUpperCase();
      }, 1500);
    });
  });
}

function _journalRunCard(r) {
  const rid = r.run_id || "—";
  const status = String(r.status || "");
  const scoreAvg = r.score_avg != null ? Math.round(Number(r.score_avg)) : "—";
  const started = r.start_ts || r.started_ts;
  const total = r.total_rows || 0;
  const err = r.errors || 0;
  const statusClass = status === "done" ? "is-done"
                    : status === "error" ? "is-error"
                    : status === "cancelled" ? "is-cancelled"
                    : "is-running";

  return `
    <article class="v5-qij-journal-card ${statusClass}">
      <header class="v5-qij-journal-header">
        <div>
          <code class="v5-qij-journal-id">${escapeHtml(rid)}</code>
          <div class="v5-qij-journal-meta">${escapeHtml(_fmtDate(started))}</div>
        </div>
        <span class="v5-qij-journal-status">${escapeHtml(status || "—")}</span>
      </header>
      <dl class="v5-qij-journal-kpis">
        <div><dt>Films</dt><dd class="v5u-tabular-nums">${total}</dd></div>
        <div><dt>${glossaryTooltip("Score perceptuel", "Score moyen")}</dt><dd class="v5u-tabular-nums">${scoreAvg}</dd></div>
        ${err > 0 ? `<div><dt>Erreurs</dt><dd class="v5u-tabular-nums v5u-text-warn">${err}</dd></div>` : ""}
      </dl>
      <footer class="v5-qij-journal-actions">
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-export-run="${escapeHtml(rid)}" data-export-fmt="csv">CSV</button>
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-export-run="${escapeHtml(rid)}" data-export-fmt="html">HTML</button>
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-export-run="${escapeHtml(rid)}" data-export-fmt="json">JSON</button>
      </footer>
    </article>
  `;
}

/* ============================================================
 * VUE QIJ CONSOLIDEE (parent avec tabs)
 * ============================================================ */

const _qijState = {
  containerRef: null,
  activeTab: "quality",
};

export async function initQij(container, opts = {}) {
  if (!container) return;
  _qijState.containerRef = container;
  _qijState.activeTab = opts.tab || "quality";

  container.innerHTML = `
    <div class="v5-qij-tabs-wrap">
      <div class="v5-qij-tabs" role="tablist" aria-label="Sections QIJ">
        <button type="button" role="tab" data-qij-tab="quality" class="v5-btn v5-btn--sm ${_qijState.activeTab === "quality" ? "v5-btn--primary is-active" : "v5-btn--ghost"}">Qualite</button>
        <button type="button" role="tab" data-qij-tab="integrations" class="v5-btn v5-btn--sm ${_qijState.activeTab === "integrations" ? "v5-btn--primary is-active" : "v5-btn--ghost"}">Integrations</button>
        <button type="button" role="tab" data-qij-tab="journal" class="v5-btn v5-btn--sm ${_qijState.activeTab === "journal" ? "v5-btn--primary is-active" : "v5-btn--ghost"}">Journal</button>
      </div>
      <div id="v5QijQualityPanel" role="tabpanel" ${_qijState.activeTab !== "quality" ? "hidden" : ""}></div>
      <div id="v5QijIntegrationsPanel" role="tabpanel" ${_qijState.activeTab !== "integrations" ? "hidden" : ""}></div>
      <div id="v5QijJournalPanel" role="tabpanel" ${_qijState.activeTab !== "journal" ? "hidden" : ""}></div>
    </div>
  `;

  await _qijMountActive(opts);

  container.querySelectorAll("[data-qij-tab]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const tab = btn.dataset.qijTab;
      if (tab === _qijState.activeTab) return;
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
  if (_qijState.activeTab === "quality") {
    await initQuality(container.querySelector("#v5QijQualityPanel"), opts);
  } else if (_qijState.activeTab === "integrations") {
    await initIntegrations(container.querySelector("#v5QijIntegrationsPanel"), opts);
  } else if (_qijState.activeTab === "journal") {
    await initJournal(container.querySelector("#v5QijJournalPanel"), opts);
  }
}

export function unmountQij() {
  unmountQuality();
  unmountIntegrations();
  unmountJournal();
  if (_qijState.containerRef) _qijState.containerRef.innerHTML = "";
  _qijState.containerRef = null;
}
