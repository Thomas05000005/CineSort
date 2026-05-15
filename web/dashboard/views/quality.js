/* views/quality.js — Vue Qualité du dashboard distant (enrichie V4) */

import { apiPost } from "../core/api.js";
import { $, escapeHtml } from "../core/dom.js";
import { showModal } from "../components/modal.js";
import { buildEmptyState, bindEmptyStateCta } from "../components/empty-state.js";
import { openQualitySimulator } from "./quality-simulator.js";
import { openCustomRulesEditor } from "./custom-rules-editor.js";
import { skeletonKpiGridHtml, skeletonLinesHtml } from "../components/skeleton.js";
import { glossaryTooltip } from "../components/glossary-tooltip.js";

let _mounted = false;
let _mode = "global"; // "run" ou "global"
let _globalData = null;
let _runData = null;
let _filters = { state: "", tier: "", score: "" };

export function initQuality(el) {
  const container = document.getElementById("qualityContent");
  if (!container) return;
  if (!_mounted) _mounted = true;
  _loadQuality(container);
}

async function _loadQuality(el) {
  // V2-08 : skeleton uniquement au 1er load (sinon flashe a chaque toggle Run/Global)
  if (!el.innerHTML.trim()) {
    el.innerHTML = `<div aria-busy="true" aria-label="Chargement Qualite">
      ${skeletonKpiGridHtml(4)}
      ${skeletonLinesHtml(5)}
    </div>`;
  }

  // Audit ID-ROB-002 : Promise.allSettled pour qu'un echec sur probe_tools
  // n'empeche pas l'affichage des stats globales (et inversement).
  const labels = ["get_global_stats", "get_probe_tools_status"];
  const results = await Promise.allSettled([
    apiPost("get_global_stats", { limit_runs: 20 }),
    apiPost("get_probe_tools_status"),
  ]);
  const _val = (r) => (r && r.status === "fulfilled" ? r.value : null);
  const [statsRes, probeRes] = results.map(_val);
  const failed = labels.filter((_, i) => results[i].status !== "fulfilled");
  if (failed.length > 0) console.warn("[quality] endpoints en echec:", failed);

  if (!statsRes?.data) { el.innerHTML = '<p class="text-muted">Données indisponibles.</p>'; return; }
  _globalData = statsRes.data;

  const total = _globalData.total_films || 0;
  if (total === 0) {
    const probeOk = probeRes?.data?.tools?.ffprobe?.available || probeRes?.data?.tools?.mediainfo?.available;
    const msg = probeOk
      ? "Aucun film scoré. Lancez un scan pour analyser votre bibliothèque."
      : "Aucun film analysé. Les outils d'analyse vidéo (FFprobe, MediaInfo) ne sont pas installés. Cliquez pour les installer maintenant.";
    // Cf issue #92 quick win #9 : CTA direct install probe (au lieu de
    // rediriger vers /settings). Reduit la friction utilisateur. Le port
    // dashboard suit la meme strategie que web/views/quality.js (legacy).
    const ctaLabel = probeOk ? "Lancer un scan" : "Installer FFprobe + MediaInfo";
    el.innerHTML = buildEmptyState({
      icon: probeOk ? "search" : "alert",
      title: probeOk ? "Aucun film scoré" : "Aucun film analysé",
      message: msg,
      ctaLabel,
      // Si probe OK : navigation classique. Sinon : pas de route, on
      // gere via defaultAction pour declencher l'install directement.
      ctaRoute: probeOk ? "/library#step-analyse" : "",
      testId: "quality-empty-cta",
    });
    bindEmptyStateCta(el, async () => {
      if (probeOk) return;
      const btn = el.querySelector('[data-testid="quality-empty-cta"]');
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Installation en cours...";
      }
      try {
        const res = await apiPost("auto_install_probe_tools");
        if (res?.data?.ok || res?.ok) {
          if (typeof window.toast === "function") {
            window.toast({ type: "success", text: "FFprobe + MediaInfo installes. Lancez un scan." });
          }
          // Recharge la vue pour refleter le nouveau status probe.
          setTimeout(() => _loadQuality(el), 500);
        } else {
          if (btn) {
            btn.disabled = false;
            btn.textContent = ctaLabel;
          }
          const errMsg = res?.data?.message || res?.message || "Echec de l'installation.";
          if (typeof window.toast === "function") {
            window.toast({ type: "error", text: errMsg });
          } else {
            alert(errMsg);
          }
        }
      } catch (err) {
        console.error("[quality] auto_install_probe_tools", err);
        if (btn) {
          btn.disabled = false;
          btn.textContent = ctaLabel;
        }
        if (typeof window.toast === "function") {
          window.toast({ type: "error", text: "Erreur reseau lors de l'installation." });
        }
      }
    });
    return;
  }

  _render(el);
}

/* --- Rendu principal ------------------------------------------ */

function _render(el) {
  const d = _globalData;
  const avgScore = d.avg_score || 0;
  const premiumPct = d.premium_pct || 0;
  const trend = d.trend || "";
  const trendArrow = trend === "up" ? "↑" : trend === "down" ? "↓" : "→";

  // Distribution (U1 audit : 5 tiers + fallback sur anciens pour snapshots pre-migration 011)
  const dist = d.tier_distribution || {};
  const platinum = dist.platinum ?? dist.premium ?? 0;
  const gold = dist.gold ?? dist.bon ?? 0;
  const silver = dist.silver ?? dist.moyen ?? 0;
  const bronze = dist.bronze ?? 0;
  const reject = dist.reject ?? dist.mauvais ?? dist.faible ?? 0;
  const distTotal = platinum + gold + silver + bronze + reject || 1;

  const timeline = d.timeline || [];
  const anomalies = d.top_anomalies || [];
  const activity = d.runs_summary || [];

  let html = "";

  // --- Toggle Run/Global + Simuler ---
  html += `<div class="flex gap-2 mb-4 items-center">
    <button class="btn btn--compact${_mode === "global" ? " active" : ""}" id="qModeGlobal">Bibliothèque</button>
    <button class="btn btn--compact${_mode === "run" ? " active" : ""}" id="qModeRun">Run courant</button>
    <div class="flex-1"></div>
    <button class="btn btn--compact" id="btnQualitySimulate" data-testid="quality-btn-simulate" title="Simuler un preset qualité (G5)">🎛 Simuler un preset</button>
    <button class="btn btn--compact" id="btnCustomRulesEditor" data-testid="quality-btn-custom-rules" title="Éditer les règles personnalisées (G6)">⚙ Règles custom</button>
  </div>`;

  // --- Contexte run (si mode run) ---
  const lastRun = activity.length > 0 ? activity[0] : null;
  if (lastRun) {
    html += `<div class="text-muted mb-4">Dernier run : <strong>${escapeHtml(String(lastRun.run_id || "").slice(0, 20))}</strong> — ${lastRun.total_rows || 0} films — score ${lastRun.avg_score ? Math.round(lastRun.avg_score) : "—"}</div>`;
  }

  // --- KPIs ---
  html += `<div class="kpi-grid mb-6">
    ${_kpi("Films analysés", d.total_films || 0, "var(--accent)")}
    ${_kpi("Score moyen", Math.round(avgScore) + "/100", "var(--gold)")}
    ${_kpi("Platinum", Math.round(premiumPct) + "%", "var(--success)")}
    ${_kpi("Tendance", trendArrow, "var(--info)")}
  </div>`;

  // --- Bento grid V6 ---
  html += `<div class="bento">`;

  // --- Distribution ---
  html += `<div class="card bento-card bento-card--half"><div class="card__eyebrow">Distribution qualité</div><div class="mt-2">
    ${_bar("Platinum (≥85)", platinum, distTotal, "var(--success)")}
    ${_bar("Gold (68-84)", gold, distTotal, "var(--accent)")}
    ${_bar("Silver (54-67)", silver, distTotal, "var(--info)")}
    ${_bar("Bronze (30-53)", bronze, distTotal, "var(--warning)")}
    ${_bar("Reject (<30)", reject, distTotal, "var(--danger)")}
  </div></div>`;

  // --- Distribution technique ---
  const tech = d.technical_distribution || {};
  if (tech.resolutions || tech.hdr || tech.audio) {
    html += `<div class="card bento-card bento-card--half"><div class="card__eyebrow">Distribution technique</div><div class="mt-2" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--sp-4)">`;
    if (tech.resolutions) html += _statGrid("Résolutions", tech.resolutions);
    if (tech.hdr) html += _statGrid("HDR", tech.hdr);
    if (tech.audio) html += _statGrid("Audio", tech.audio);
    html += `</div></div>`;
  }

  // --- Filtres qualité ---
  html += `<div class="flex gap-2 mb-4 flex-wrap">
    <select class="input" id="qFilterState" style="max-width:140px">
      <option value="">État : Tous</option><option value="scored">Scoré</option><option value="unscored">Non scoré</option></select>
    <select class="input" id="qFilterTier" style="max-width:140px">
      <option value="">Tier : Tous</option><option value="premium">Premium</option><option value="bon">Bon</option><option value="moyen">Moyen</option><option value="mauvais">Mauvais</option></select>
    <select class="input" id="qFilterScore" style="max-width:140px">
      <option value="">Score : Tous</option><option value="80">≥80</option><option value="60-80">60-80</option><option value="40-60">40-60</option><option value="40">&lt;40</option></select>
  </div>`;

  // --- Actions batch ---
  html += `<div class="flex gap-2 mb-4">
    <button class="btn btn--compact" id="qBtnAnalyzeAll">Analyser tous les validés</button>
    <button class="btn btn--compact" id="qBtnAnalyzeFiltered">Analyser les filtrés</button>
  </div>`;
  html += `<div id="qBatchMsg" class="status-msg mb-4"></div>`;

  // --- Profil scoring ---
  html += `<div class="card bento-card bento-card--third"><div class="card__eyebrow">Profil de scoring</div>
    <div class="flex gap-2 mt-2">
      <button class="btn btn--compact" id="qBtnExportProfile">Exporter</button>
      <button class="btn btn--compact" id="qBtnImportProfile">Importer</button>
      <button class="btn btn--compact" id="qBtnResetProfile">Réinitialiser</button>
    </div>
  </div>`;

  // --- Timeline ---
  if (timeline.length > 1) {
    html += `<div class="card bento-card bento-card--wide"><div class="card__eyebrow">Évolution du score</div>
      <div class="mt-2" style="overflow-x:auto">${_buildTimelineSvg(timeline)}</div></div>`;
  }

  // --- Anomalies ---
  if (anomalies.length > 0) {
    html += `<div class="card bento-card bento-card--third"><div class="card__eyebrow">Anomalies fréquentes</div>
      <table class="tbl mt-2"><thead><tr><th>Code</th><th>Nombre</th></tr></thead><tbody>
      ${anomalies.map(a => `<tr><td>${escapeHtml(a.code || "")}</td><td>${a.count || 0}</td></tr>`).join("")}
      </tbody></table></div>`;
  }

  // --- Outliers ---
  const allRows = d.all_scored_rows || [];
  if (allRows.length > 5) {
    const scores = allRows.map(r => Number(r.score || 0)).filter(s => s > 0);
    if (scores.length > 0) {
    const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
    const std = Math.sqrt(scores.reduce((a, b) => a + (b - mean) ** 2, 0) / scores.length);
    const threshold = Math.max(30, mean - 2 * std);
    const outliers = allRows.filter(r => Number(r.score || 0) > 0 && Number(r.score) < threshold);
    if (outliers.length > 0) {
      html += `<div class="card bento-card bento-card--third"><div class="card__eyebrow">Outliers (score &lt; ${Math.round(threshold)})</div>
        <table class="tbl mt-2"><thead><tr><th>Titre</th><th>${glossaryTooltip("Score perceptuel", "Score")}</th><th>${glossaryTooltip("Tier")}</th></tr></thead><tbody>
        ${outliers.slice(0, 15).map(r => `<tr class="clickable-row" data-outlier-rid="${escapeHtml(r.row_id || "")}">
          <td>${escapeHtml(r.proposed_title || r.title || "")}</td>
          <td>${Math.round(Number(r.score || 0))}</td>
          <td>${escapeHtml(r.tier || "—")}</td>
        </tr>`).join("")}
        </tbody></table></div>`;
    }
    } // scores.length > 0
  }

  // --- Activité ---
  if (activity.length > 0) {
    html += `<div class="card bento-card bento-card--wide"><div class="card__eyebrow">Derniers runs</div>
      <table class="tbl mt-2"><thead><tr><th>${glossaryTooltip("Run")}</th><th>Films</th><th>${glossaryTooltip("Score perceptuel", "Score")}</th><th>Statut</th></tr></thead><tbody>
      ${activity.slice(0, 10).map(r => `<tr>
        <td class="text-mono">${escapeHtml(String(r.run_id || "").slice(0, 15))}</td>
        <td>${r.total_rows || 0}</td>
        <td>${r.avg_score ? Math.round(r.avg_score) : "—"}</td>
        <td>${escapeHtml(r.status || "")}</td>
      </tr>`).join("")}
      </tbody></table></div>`;
  }

  // --- Fermeture du bento grid V6 ---
  html += `</div>`;

  el.innerHTML = html;
  _hookEvents(el);
}

/* --- Evenements ----------------------------------------------- */

function _hookEvents(el) {
  $("qModeGlobal")?.addEventListener("click", () => { _mode = "global"; _render(el); });
  $("qModeRun")?.addEventListener("click", () => { _mode = "run"; _render(el); });
  $("btnQualitySimulate")?.addEventListener("click", () => {
    const lastRun = (_globalData?.runs_summary || [])[0];
    openQualitySimulator(lastRun?.run_id || "latest");
  });
  $("btnCustomRulesEditor")?.addEventListener("click", () => { openCustomRulesEditor(); });

  // Batch actions
  $("qBtnAnalyzeAll")?.addEventListener("click", () => _analyzeBatch("validated"));
  $("qBtnAnalyzeFiltered")?.addEventListener("click", () => _analyzeBatch("filtered"));

  // Profil scoring
  $("qBtnExportProfile")?.addEventListener("click", _exportProfile);
  $("qBtnImportProfile")?.addEventListener("click", _importProfile);
  $("qBtnResetProfile")?.addEventListener("click", _resetProfile);

  // Outlier drill-down
  el.querySelectorAll("[data-outlier-rid]").forEach(tr => {
    tr.addEventListener("click", () => {
      const rid = tr.dataset.outlierRid;
      showModal({ title: "Film détaillé", body: `<p>Row ID : ${escapeHtml(rid)}</p><p class="text-muted">Ouvrez la Bibliothèque pour l'inspecteur complet.</p>` });
    });
  });
}

/* --- Batch analysis ------------------------------------------- */

async function _analyzeBatch(scope) {
  const msg = $("qBatchMsg");
  if (msg) { msg.textContent = "Analyse en cours..."; msg.className = "status-msg"; }
  try {
    const lastRun = (_globalData.runs_summary || [])[0];
    if (!lastRun?.run_id) { if (msg) { msg.textContent = "Aucun run disponible."; msg.className = "status-msg error"; } return; }
    const res = await apiPost("quality/analyze_quality_batch", { run_id: lastRun.run_id, row_ids: [], options: { scope } });
    if (msg) { msg.textContent = res.data?.message || "Analyse lancée."; msg.className = "status-msg success"; }
  } catch { if (msg) { msg.textContent = "Erreur réseau."; msg.className = "status-msg error"; } }
}

/* --- Profil scoring ------------------------------------------- */

async function _exportProfile() {
  try {
    const res = await apiPost("quality/export_quality_profile");
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "quality_profile.json"; a.click();
    URL.revokeObjectURL(url);
  } catch { alert("Erreur export profil."); }
}

async function _importProfile() {
  const input = document.createElement("input");
  input.type = "file"; input.accept = ".json";
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const profile = JSON.parse(text);
      await apiPost("quality/import_quality_profile", { profile_json: profile });
      alert("Profil importé avec succès.");
    } catch { alert("Erreur import profil."); }
  });
  input.click();
}

async function _resetProfile() {
  if (!confirm("Réinitialiser le profil de scoring aux valeurs par défaut ?")) return;
  try {
    await apiPost("quality/reset_quality_profile");
    alert("Profil réinitialisé.");
  } catch { alert("Erreur réinitialisation."); }
}

/* --- Helpers -------------------------------------------------- */

function _kpi(label, value, color) {
  return `<div class="kpi-card" style="border-left:3px solid ${color}">
    <div class="kpi-label">${escapeHtml(label)}</div>
    <div class="kpi-value">${value}</div>
  </div>`;
}

function _bar(label, count, total, color) {
  const pct = Math.round(count / total * 100);
  return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
    <span style="width:100px;font-size:var(--fs-sm);color:var(--text-secondary)">${escapeHtml(label)}</span>
    <div style="flex:1;height:6px;background:var(--bg-raised);border-radius:999px;overflow:hidden">
      <div style="width:${pct}%;height:100%;background:${color};border-radius:999px;transition:width 0.3s"></div>
    </div>
    <span style="width:40px;text-align:right;font-size:var(--fs-xs);color:var(--text-muted)">${count}</span>
  </div>`;
}

function _statGrid(title, data) {
  if (!data || typeof data !== "object") return "";
  let html = `<div><strong class="text-muted font-sm">${escapeHtml(title)}</strong>`;
  for (const [k, v] of Object.entries(data)) {
    html += `<div class="flex justify-between font-sm"><span>${escapeHtml(k)}</span><span>${v}</span></div>`;
  }
  return html + "</div>";
}

function _buildTimelineSvg(points) {
  if (points.length < 2) return "";
  const w = Math.max(300, points.length * 40), h = 100;
  const coords = points.map((p, i) => {
    const x = 20 + (i / (points.length - 1)) * (w - 40);
    const y = h - 10 - ((p.avg_score || 0) / 100) * (h - 20);
    return `${x},${y}`;
  });
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="width:100%;max-width:${w}px">
    <polyline points="${coords.join(" ")}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round"/>
    ${coords.map(c => `<circle cx="${c.split(",")[0]}" cy="${c.split(",")[1]}" r="3" fill="var(--accent)"/>`).join("")}
  </svg>`;
}
