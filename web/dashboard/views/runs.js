/* views/runs.js — Historique des runs du dashboard distant */

import { $, escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { tableHtml, attachSort } from "../components/table.js";
import { badgeHtml } from "../components/badge.js";
import { fmtDate as _fmtDate, fmtDuration as _fmtDuration } from "../core/format.js";
import { skeletonLinesHtml } from "../components/skeleton.js";
import { sparklineSvg } from "../components/sparkline.js";
import { groupRunsByDate } from "../core/time-groups.js";

/* --- Etat local -------------------------------------------- */

let _runs = [];
let _collapsed = new Set();

/* --- Colonnes ---------------------------------------------- */

const _COLUMNS = [
  { key: "started_at", label: "Date", sortable: true, render: (v) => _fmtDate(v) },
  { key: "run_id", label: "Run ID", sortable: true, render: (v) => `<span class="text-accent">${escapeHtml(v || "")}</span>` },
  { key: "total_rows", label: "Films", sortable: true },
  { key: "avg_score", label: "Score", sortable: true, render: (v) => v != null ? `${Math.round(v)} pts` : "—" },
  { key: "trend", label: "Tendance", sortable: false, render: (_v, row) => row._spark || "" },
  { key: "status", label: "Statut", sortable: true, render: (v) => badgeHtml("status", v) },
  { key: "duration_s", label: "Duree", sortable: true, render: (v) => _fmtDuration(v) },
];

/* --- Enrichissement sparkline (I12) -------------------------- */

function _enrichWithSparklines(runs) {
  /* runs supposes tries par date DESC (plus recent en premier). */
  const sorted = [...runs].sort((a, b) => Number(b.started_at || 0) - Number(a.started_at || 0));
  sorted.forEach((run, i) => {
    /* Prend le run courant + les 4 plus anciens suivants (window de 5). */
    const window = sorted.slice(i, i + 5)
      .map((r) => Number(r.avg_score || 0))
      .filter((v) => v > 0)
      .reverse(); // ordre chronologique dans la sparkline
    run._spark = window.length >= 2 ? sparklineSvg(window, { w: 72, h: 22 }) : '<span class="text-muted">—</span>';
  });
  return sorted;
}

/* --- Chargement -------------------------------------------- */

async function _load() {
  const container = $("runsContent");
  if (!container) return;

  container.innerHTML = skeletonLinesHtml(5);

  try {
    const res = await apiPost("get_global_stats", { limit_runs: 50 });
    const d = res.data || {};
    _runs = Array.isArray(d.runs_summary) ? d.runs_summary : [];

    _renderFull(container);
  } catch (err) {
    container.innerHTML = `<p class="status-msg error">Erreur : ${escapeHtml(String(err))}</p>`;
  }
}

/* --- Rendu complet ----------------------------------------- */

function _renderFull(container) {
  let html = "";

  // Timeline SVG
  html += '<div id="runsTimeline" class="mt-4"></div>';

  // Table
  html += '<div id="runsTable" class="mt-4"></div>';

  // Boutons export
  html += '<div class="flex gap-2 mt-4">';
  html += '<button class="btn" data-export-fmt="json">Exporter JSON</button>';
  html += '<button class="btn" data-export-fmt="csv">Exporter CSV</button>';
  html += '<button class="btn" data-export-fmt="html">Exporter HTML</button>';
  html += '<button class="btn" id="btnExportNfo">Exporter .nfo</button>';
  html += "</div>";
  html += '<div id="runsExportMsg" class="status-msg mt-4"></div>';

  container.innerHTML = html;

  _renderTimeline();
  _renderGroupedTable();
  _hookExportBtns();
  _hookNfoExport();
}

/* --- Table groupee par date (I13) -------------------------- */

function _renderGroupedTable() {
  const host = $("runsTable");
  if (!host) return;

  const enriched = _enrichWithSparklines(_runs);
  const groups = groupRunsByDate(enriched);

  if (groups.length === 0) {
    host.innerHTML = '<p class="text-muted">Aucun run.</p>';
    return;
  }

  let html = "";
  for (const g of groups) {
    const collapsed = _collapsed.has(g.id);
    html += `<div class="runs-group${collapsed ? " is-collapsed" : ""}" data-group-id="${g.id}">`;
    html += `<div class="runs-group__header" tabindex="0">
      <svg class="runs-group__chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      <span>${escapeHtml(g.label)}</span>
      <span class="runs-group__count">${g.runs.length} run${g.runs.length > 1 ? "s" : ""}</span>
    </div>`;
    html += `<div class="runs-group__body">`;
    html += tableHtml({ columns: _COLUMNS, rows: g.runs, id: `runs-table-${g.id}`, emptyText: "Aucun run." });
    html += `</div></div>`;
  }
  host.innerHTML = html;

  /* Sort + collapse handlers */
  groups.forEach((g) => {
    attachSort(`runs-table-${g.id}`, g.runs, () => {
      const inner = host.querySelector(`[data-group-id="${g.id}"] .runs-group__body`);
      if (inner) inner.innerHTML = tableHtml({ columns: _COLUMNS, rows: g.runs, id: `runs-table-${g.id}`, emptyText: "Aucun run." });
    });
  });

  host.querySelectorAll(".runs-group__header").forEach((header) => {
    const toggle = () => {
      const group = header.parentElement;
      const gid = group.dataset.groupId;
      group.classList.toggle("is-collapsed");
      if (group.classList.contains("is-collapsed")) _collapsed.add(gid);
      else _collapsed.delete(gid);
    };
    header.addEventListener("click", toggle);
    header.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
  });
}

/* --- Timeline SVG ------------------------------------------ */

function _renderTimeline() {
  const el = $("runsTimeline");
  if (!el || _runs.length === 0) { if (el) el.innerHTML = ""; return; }

  const barW = Math.max(12, Math.min(40, Math.floor(380 / _runs.length)));
  const svgW = _runs.length * (barW + 4) + 20;
  const svgH = 80;

  const tierColor = { premium: "var(--success)", bon: "var(--info)", moyen: "var(--warning)", mauvais: "var(--danger)" };

  let svg = `<svg class="runs-timeline" viewBox="0 0 ${svgW} ${svgH}" xmlns="http://www.w3.org/2000/svg">`;

  for (let i = 0; i < _runs.length; i++) {
    const run = _runs[i];
    const x = 10 + i * (barW + 4);
    const score = Number(run.avg_score) || 0;
    let tier;
    if (score >= 85) tier = "premium";
    else if (score >= 68) tier = "bon";
    else if (score >= 54) tier = "moyen";
    else tier = "mauvais";
    const h = Math.max(4, (score / 100) * (svgH - 20));
    const y = svgH - 10 - h;
    const color = tierColor[tier] || "var(--text-muted)";
    svg += `<rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="2" fill="${color}" opacity="0.8">`;
    svg += `<title>${escapeHtml(run.run_id || "")} — ${Math.round(score)} pts</title>`;
    svg += "</rect>";
  }

  svg += "</svg>";
  el.innerHTML = svg;
}

/* --- Table ------------------------------------------------- */

/* --- Export ------------------------------------------------ */

function _hookExportBtns() {
  const container = $("runsContent");
  if (!container) return;

  container.querySelectorAll("[data-export-fmt]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const fmt = btn.dataset.exportFmt;
      const runId = _runs.length > 0 ? _runs[0].run_id : null;
      if (!runId) {
        _showMsg("runsExportMsg", "Aucun run a exporter.", true);
        return;
      }

      btn.disabled = true;
      _showMsg("runsExportMsg", `Export ${fmt} en cours...`);

      try {
        const res = await apiPost("export_run_report", { run_id: runId, fmt });
        const d = res.data || {};

        if (!d.ok) {
          _showMsg("runsExportMsg", escapeHtml(d.message || "Echec export."), true);
          return;
        }

        // Telecharger le contenu
        const content = d.content || d.csv || d.html || JSON.stringify(d, null, 2);
        const mimeMap = { json: "application/json", csv: "text/csv", html: "text/html" };
        const blob = new Blob([content], { type: mimeMap[fmt] || "text/plain" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `cinesort_${runId}.${fmt}`;
        a.click();
        URL.revokeObjectURL(url);

        _showMsg("runsExportMsg", `Export ${fmt} telecharge.`);
      } catch (err) {
        _showMsg("runsExportMsg", "Erreur reseau.", true);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function _hookNfoExport() {
  const btn = $("btnExportNfo");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const runId = _runs.length > 0 ? _runs[0].run_id : null;
    if (!runId) { _showMsg("runsExportMsg", "Aucun run.", true); return; }
    btn.disabled = true;
    _showMsg("runsExportMsg", "Export .nfo en cours...");
    try {
      const res = await apiPost("export_run_nfo", { run_id: runId, overwrite: false, dry_run: false });
      if (res.data?.ok) {
        _showMsg("runsExportMsg", `${res.data.created || 0} fichier(s) .nfo crees.`);
      } else {
        _showMsg("runsExportMsg", res.data?.message || "Echec.", true);
      }
    } catch { _showMsg("runsExportMsg", "Erreur reseau.", true); }
    btn.disabled = false;
  });
}

function _showMsg(id, text, isError = false) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.className = "status-msg" + (isError ? " error" : " success");
}

/* --- Point d'entree ---------------------------------------- */

export function initRuns() {
  _runs = [];
  _load();
}
