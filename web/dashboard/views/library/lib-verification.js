/* lib-verification.js — Section 2 : Vérification (cas ambigus) */

import { $, escapeHtml } from "../../core/dom.js";
import { apiPost } from "../../core/api.js";
import { badgeHtml } from "../../components/badge.js";
import { showModal } from "../../components/modal.js";

let _state = null;
let _ambiguousRows = [];

/* --- Point d'entree ------------------------------------------- */

export function initVerification(libState) {
  _state = libState;
  const el = $("libVerificationContent");
  if (!el) return;
  // Le rendu est declenche quand les rows sont chargees (depuis lib-validation.js)
  el.innerHTML = '<p class="text-muted">Chargez les résultats de l\'analyse pour voir les cas ambigus.</p>';
}

/** Appele par lib-validation.js apres chargement des rows. */
export function refreshVerification(rows) {
  _ambiguousRows = _filterAmbiguous(rows);
  const el = $("libVerificationContent");
  if (!el) return;
  _render(el);
}

/* --- Filtrage des cas ambigus --------------------------------- */

const _CRITICAL_FLAGS = ["not_a_movie", "integrity_header_invalid", "nfo_title_mismatch", "year_conflict_folder_file"];
const _THRESHOLD_LOW = 70;

function _filterAmbiguous(rows) {
  return rows.filter(r => {
    const conf = Number(r.confidence || r.confidence_score || 0);
    if (conf < _THRESHOLD_LOW) return true;
    const flags = _parseFlags(r.warning_flags);
    return flags.some(f => _CRITICAL_FLAGS.includes(f));
  });
}

function _parseFlags(v) {
  if (!v) return [];
  if (Array.isArray(v)) return v;
  return String(v).split(",").map(s => s.trim()).filter(Boolean);
}

/* --- Calcul du risque (porte de validation.js desktop) -------- */

function _computeRisk(row) {
  const conf = Number(row.confidence || row.confidence_score || 0);
  const flags = _parseFlags(row.warning_flags);
  const reasons = [];

  if (conf < 40) reasons.push("Confiance très faible");
  else if (conf < 70) reasons.push("Confiance faible");

  if (flags.includes("not_a_movie")) reasons.push("Contenu non-film détecté");
  if (flags.includes("integrity_header_invalid")) reasons.push("Header fichier invalide");
  if (flags.includes("nfo_title_mismatch")) reasons.push("NFO incohérent avec le dossier");
  if (flags.includes("year_conflict_folder_file")) reasons.push("Année contradictoire");
  if (flags.includes("upscale_suspect")) reasons.push("Upscale suspecté");
  if (flags.includes("reencode_degraded")) reasons.push("Ré-encodage dégradé");

  const level = conf < 40 ? "high" : conf < 70 ? "med" : "low";
  return { level, reasons };
}

function _reasonLabel(row) {
  const flags = _parseFlags(row.warning_flags);
  if (flags.includes("not_a_movie")) return "Non-film";
  if (flags.includes("integrity_header_invalid")) return "Intégrité";
  if (flags.includes("nfo_title_mismatch")) return "NFO rejeté";
  if (flags.includes("year_conflict_folder_file")) return "Année incohérente";
  const conf = Number(row.confidence || 0);
  if (conf < 40) return "Confiance très faible";
  if (conf < 70) return "Confiance faible";
  return "À vérifier";
}

/* --- Rendu ---------------------------------------------------- */

function _render(el) {
  if (!_ambiguousRows.length) {
    el.innerHTML = '<div class="card"><p class="text-success">Aucun cas ambigu détecté. Tous les films sont identifiés avec confiance.</p></div>';
    return;
  }

  let html = `<div class="card">`;
  html += `<p><strong>${_ambiguousRows.length}</strong> cas à vérifier</p>`;

  // Filtres
  html += `<div class="flex gap-2 mt-2 mb-4">`;
  html += `<input type="text" class="input" placeholder="Rechercher..." id="libVerifSearch" data-testid="lib-verif-search" style="max-width:200px">`;
  html += `<select class="input" id="libVerifReason" data-testid="lib-verif-filter-raison" style="max-width:180px">
    <option value="">Toutes les raisons</option>
    <option value="nfo">NFO rejeté</option>
    <option value="year">Année incohérente</option>
    <option value="conf">Confiance faible</option>
    <option value="notmovie">Non-film</option>
    <option value="integrity">Intégrité</option>
  </select>`;
  html += `<select class="input" id="libVerifPriority" data-testid="lib-verif-filter-priorite" style="max-width:150px">
    <option value="">Toutes priorités</option>
    <option value="high">Haute (&lt;40)</option>
    <option value="med">Moyenne (40-70)</option>
    <option value="low">Basse (70-85)</option>
  </select>`;
  html += `</div>`;

  // Table
  html += `<div class="table-wrap"><table class="tbl" id="libVerifTable" data-testid="lib-verif-table"><thead><tr>
    <th>Priorité</th><th>Raison</th><th>Titre</th><th>Dossier</th><th>Source</th>
  </tr></thead><tbody id="libVerifTbody">`;
  for (const row of _ambiguousRows) {
    const risk = _computeRisk(row);
    const cls = risk.level === "high" ? "badge-danger" : risk.level === "med" ? "badge-warning" : "badge";
    html += `<tr class="clickable-row" data-rid="${escapeHtml(row.row_id || "")}">`;
    html += `<td><span class="${cls}">${risk.level === "high" ? "Haute" : risk.level === "med" ? "Moyenne" : "Basse"}</span></td>`;
    html += `<td>${escapeHtml(_reasonLabel(row))}</td>`;
    html += `<td>${escapeHtml(row.proposed_title || row.title || "")}</td>`;
    html += `<td class="text-muted" title="${escapeHtml(row.folder || "")}">${escapeHtml(_short(row.folder))}</td>`;
    html += `<td>${escapeHtml(row.proposed_source || row.source || "")}</td>`;
    html += `</tr>`;
  }
  html += `</tbody></table></div>`;

  // Bouton avancer
  html += `<div class="mt-4"><button id="libBtnVerifDone" class="btn btn-primary">Tout vérifié → Validation</button></div>`;
  html += `</div>`;

  el.innerHTML = html;
  _hookVerifEvents();
}

function _short(p) {
  const s = String(p || "");
  return s.length <= 40 ? s : s.slice(0, 18) + "..." + s.slice(-18);
}

/* --- Evenements ----------------------------------------------- */

function _hookVerifEvents() {
  // Clic sur une ligne → modale "Pourquoi ce cas ?"
  const tbody = $("libVerifTbody");
  if (tbody) {
    tbody.addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-rid]");
      if (!tr) return;
      const rid = tr.dataset.rid;
      const row = _ambiguousRows.find(r => String(r.row_id) === rid);
      if (row) _showWhyModal(row);
    });
  }

  // Bouton "Tout verifie"
  const btn = $("libBtnVerifDone");
  if (btn) {
    btn.addEventListener("click", () => {
      const target = document.querySelector('[data-lib-section="validation"]');
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  // Filtres dynamiques
  const searchInput = $("libVerifSearch");
  const reasonSelect = $("libVerifReason");
  const prioritySelect = $("libVerifPriority");

  function _applyFilters() {
    const q = (searchInput?.value || "").toLowerCase();
    const reason = reasonSelect?.value || "";
    const priority = prioritySelect?.value || "";
    const tbody = $("libVerifTbody");
    if (!tbody) return;
    for (const tr of tbody.querySelectorAll("tr[data-rid]")) {
      const text = tr.textContent.toLowerCase();
      const reasonCell = (tr.children[1]?.textContent || "").toLowerCase();
      const prioVal = parseInt(tr.children[0]?.textContent || "100", 10);
      let show = true;
      if (q && !text.includes(q)) show = false;
      if (reason && !reasonCell.includes(reason)) show = false;
      if (priority === "high" && prioVal >= 40) show = false;
      if (priority === "med" && (prioVal < 40 || prioVal >= 70)) show = false;
      if (priority === "low" && prioVal < 70) show = false;
      tr.style.display = show ? "" : "none";
    }
  }

  searchInput?.addEventListener("input", _applyFilters);
  reasonSelect?.addEventListener("change", _applyFilters);
  prioritySelect?.addEventListener("change", _applyFilters);
}

/* --- Modale "Pourquoi ce cas ?" ------------------------------- */

function _showWhyModal(row) {
  const risk = _computeRisk(row);
  let body = `<div class="detail-grid">`;
  body += `<div class="detail-row"><span class="detail-label">Titre proposé</span><span>${escapeHtml(row.proposed_title || "")}</span></div>`;
  body += `<div class="detail-row"><span class="detail-label">Dossier</span><span class="text-muted">${escapeHtml(row.folder || "")}</span></div>`;
  body += `<div class="detail-row"><span class="detail-label">Source</span><span>${escapeHtml(row.proposed_source || row.source || "")}</span></div>`;
  body += `<div class="detail-row"><span class="detail-label">Confiance</span><span>${Number(row.confidence || 0)}%</span></div>`;
  body += `</div>`;

  if (risk.reasons.length) {
    body += `<h4 class="mt-4">Raisons du signalement</h4><ul>`;
    for (const r of risk.reasons) body += `<li>${escapeHtml(r)}</li>`;
    body += `</ul>`;
  }

  // Candidats TMDb si disponibles
  const candidates = row.candidates || [];
  if (candidates.length > 1) {
    body += `<h4 class="mt-4">Candidats TMDb considérés</h4><ul>`;
    for (const c of candidates.slice(0, 5)) {
      const sel = c.selected ? ' <span class="badge badge-success">Retenu</span>' : "";
      body += `<li>${escapeHtml(c.title || "")} (${c.year || "?"}) — ${Math.round((c.score || 0) * 100)}%${sel}</li>`;
    }
    body += `</ul>`;
  }

  showModal({ title: "Pourquoi ce cas ?", body, testid: "lib-verif-why-panel" });
}
