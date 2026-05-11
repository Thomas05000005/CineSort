/* lib-duplicates.js — Section 4 : Doublons (groupes, comparaison) */

import { $, escapeHtml } from "../../core/dom.js";
import { apiPost } from "../../core/api.js";
import { showModal } from "../../components/modal.js";
import { libState } from "./library.js";
import { buildDecisionsPayload } from "./lib-validation.js";
import { renderScoreV2CompareHtml } from "../../components/score-v2.js";
import { fmtBytes as _fmtBytesShared } from "../../core/format.js";

/* --- Point d'entree ------------------------------------------- */

export function initDuplicates(state) {
  const el = $("libDuplicatesContent");
  if (!el) return;
  _render(el);
}

/* --- Rendu ---------------------------------------------------- */

function _render(el) {
  el.innerHTML = `
    <div class="card">
      <div class="flex gap-2 items-center">
        <button id="libBtnCheckDups" class="btn btn--compact" data-testid="lib-dup-btn-check">Actualiser la vue doublons</button>
        <span id="libDupsCount" class="text-muted" data-testid="lib-dup-count"></span>
      </div>
      <div id="libDupsGroups" class="mt-4" data-testid="lib-dup-groups"></div>
    </div>
  `;
  _hookEvents();
  // Chargement automatique si un run est disponible
  if (libState.runId) _loadDuplicates();
}

/* --- Chargement ----------------------------------------------- */

async function _loadDuplicates() {
  const groupsEl = $("libDupsGroups");
  const countEl = $("libDupsCount");
  if (!groupsEl) return;
  groupsEl.innerHTML = '<p class="text-muted">Chargement...</p>';

  try {
    const res = await apiPost("check_duplicates", {
      run_id: libState.runId,
      decisions: buildDecisionsPayload(),
    });
    const groups = res.data?.groups || [];

    if (countEl) countEl.textContent = `${groups.length} groupe(s) de doublons`;

    if (!groups.length) {
      groupsEl.innerHTML = '<p class="text-success">Aucun doublon détecté.</p>';
      return;
    }

    let html = "";
    for (const g of groups) {
      html += `<div class="card mt-2" style="padding:var(--sp-3)">`;
      html += `<h4>${escapeHtml(g.title || "?")} ${g.year ? `(${g.year})` : ""}</h4>`;
      if (g.comparison) {
        html += _buildComparisonHtml(g.comparison);
      } else {
        html += `<p class="text-muted">${escapeHtml(g.plan_conflict ? "Conflit de plan (même destination)" : "Doublon détecté")}</p>`;
      }
      // Bouton comparaison perceptuelle (si 2 fichiers)
      if (g.files && g.files.length === 2) {
        html += `<button class="btn btn--compact mt-2" data-compare-a="${escapeHtml(g.files[0]?.row_id || "")}" data-compare-b="${escapeHtml(g.files[1]?.row_id || "")}">Comparaison perceptuelle</button>`;
      }
      html += `</div>`;
    }
    groupsEl.innerHTML = html;

    // Hook boutons comparaison perceptuelle
    groupsEl.querySelectorAll("[data-compare-a]").forEach(btn => {
      btn.addEventListener("click", () => _comparePerceptual(btn.dataset.compareA, btn.dataset.compareB));
    });
  } catch (err) {
    groupsEl.innerHTML = `<p class="status-msg error">Erreur : ${escapeHtml(String(err))}</p>`;
  }
}

/* --- Comparaison HTML ----------------------------------------- */

function _buildComparisonHtml(cmp) {
  let html = `<p class="compare-score"><strong>Score :</strong> ${cmp.total_score_a || 0} vs ${cmp.total_score_b || 0}</p>`;
  html += `<p>${escapeHtml(cmp.recommendation || "")}</p>`;
  if (cmp.size_savings > 0) {
    html += `<p class="text-muted">Économie potentielle : ${_fmtSize(cmp.size_savings)}</p>`;
  }
  html += '<div class="table-wrap"><table class="compare-table"><thead><tr><th>Critère</th><th>A</th><th>B</th></tr></thead><tbody>';
  for (const c of (cmp.criteria || [])) {
    const markA = c.winner === "a" ? ' <span class="badge badge-success">✓</span>' : "";
    const markB = c.winner === "b" ? ' <span class="badge badge-success">✓</span>' : "";
    html += `<tr><td>${escapeHtml(c.label || c.name || "")}</td><td>${escapeHtml(c.value_a || "?")}${markA}</td><td>${escapeHtml(c.value_b || "?")}${markB}</td></tr>`;
  }
  html += '</tbody></table></div>';
  return html;
}

/* --- Comparaison perceptuelle --------------------------------- */

async function _comparePerceptual(rowIdA, rowIdB) {
  try {
    const res = await apiPost("compare_perceptual", {
      run_id: libState.runId,
      row_id_a: rowIdA,
      row_id_b: rowIdB,
    });
    const d = res.data || {};
    const cmp = d.comparison || d;
    let body = `<p>Score A : <strong>${cmp.score_a ?? "—"}</strong> | Score B : <strong>${cmp.score_b ?? "—"}</strong></p>`;

    // §16b v7.5.0 — Score composite V2 cote-a-cote si dispo
    const gsvA = cmp.global_score_v2_a;
    const gsvB = cmp.global_score_v2_b;
    if (gsvA || gsvB) {
      body += renderScoreV2CompareHtml(gsvA, gsvB);
    }

    body += `<p style="margin-top:10px">${escapeHtml(cmp.winner_label || cmp.recommendation || d.summary || "Pas de recommandation.")}</p>`;
    showModal({ title: "Comparaison perceptuelle", body });
  } catch (err) {
    showModal({ title: "Erreur", body: `<p class="status-msg error">${escapeHtml(String(err))}</p>` });
  }
}

/* --- Helpers -------------------------------------------------- */

function _fmtSize(bytes) {
  // V6-04 : delegue a fmtBytes locale-aware (core/format.js).
  return _fmtBytesShared(bytes);
}

function _hookEvents() {
  $("libBtnCheckDups")?.addEventListener("click", () => _loadDuplicates());
}
