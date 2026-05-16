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
    const res = await apiPost("quality/compare_perceptual", {
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
    // Cf #94 : bouton pour charger les frames cote-a-cote (lazy : evite le
    // cout d'extraction PNG base64 si l'utilisateur n'en a pas besoin).
    body += `<hr><div data-frames-container>
      <button type="button" class="btn btn--compact" data-load-frames="1"
              data-row-a="${escapeHtml(rowIdA)}" data-row-b="${escapeHtml(rowIdB)}">
        Voir les frames cote-a-cote
      </button>
      <span class="text-muted" data-frames-msg style="margin-left:0.5em"></span>
    </div>`;
    showModal({ title: "Comparaison perceptuelle", body });
    _bindCompareFramesButton(rowIdA, rowIdB);
  } catch (err) {
    showModal({ title: "Erreur", body: `<p class="status-msg error">${escapeHtml(String(err))}</p>` });
  }
}

/* Cf #94 : binding du bouton "Voir les frames" dans la modale comparaison.
 * Lazy load : ne charge les frames que si l'utilisateur clique. PNG base64
 * peut etre lourd (~500KB par frame 1080p luminance), inutile de payer le
 * cout extract+encode quand l'utilisateur ne consulte que les scores.
 */
function _bindCompareFramesButton(rowIdA, rowIdB) {
  // Le bind est fait dans un setTimeout pour laisser le modal monter le DOM.
  setTimeout(() => {
    const overlay = document.querySelector(".modal-overlay");
    if (!overlay) return;
    const btn = overlay.querySelector("[data-load-frames]");
    const msgEl = overlay.querySelector("[data-frames-msg]");
    const container = overlay.querySelector("[data-frames-container]");
    if (!btn || !container) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      if (msgEl) msgEl.textContent = "Extraction en cours (~10-30s)...";
      try {
        const res = await apiPost("quality/get_perceptual_compare_frames", {
          run_id: libState.runId,
          row_id_a: rowIdA,
          row_id_b: rowIdB,
          options: { max_frames: 3 },
        });
        const d = res.data || {};
        if (!d.ok) {
          if (msgEl) {
            msgEl.textContent = d.message || "Echec de l'extraction.";
            msgEl.style.color = "var(--danger, #f87171)";
          }
          btn.disabled = false;
          return;
        }
        const frames = Array.isArray(d.frames) ? d.frames : [];
        if (!frames.length) {
          if (msgEl) msgEl.textContent = "Aucune frame extraite.";
          btn.disabled = false;
          return;
        }
        // Render : pour chaque frame, 2 img cote-a-cote avec timestamp + delta.
        let html = `<p class="text-muted" style="margin-top:0.5em">${frames.length} frame(s) classees par difference visuelle (greyscale luminance).</p>`;
        html += `<div data-frames-grid style="display:grid; grid-template-columns:1fr 1fr; gap:0.5em; margin-top:0.5em">`;
        html += `<div style="text-align:center; font-weight:600">Fichier A</div>`;
        html += `<div style="text-align:center; font-weight:600">Fichier B</div>`;
        for (const f of frames) {
          const ts = Number(f.timestamp || 0);
          const mm = Math.floor(ts / 60);
          const ss = Math.floor(ts % 60).toString().padStart(2, "0");
          const tsLabel = `T+${mm}:${ss}`;
          const meanDiff = f.mean_diff != null ? Number(f.mean_diff).toFixed(1) : "?";
          html += `<div><img src="data:image/png;base64,${f.frame_a_b64}" alt="Frame A ${tsLabel}" style="max-width:100%; image-rendering:pixelated; border:1px solid var(--border, #444)"></div>`;
          html += `<div><img src="data:image/png;base64,${f.frame_b_b64}" alt="Frame B ${tsLabel}" style="max-width:100%; image-rendering:pixelated; border:1px solid var(--border, #444)"></div>`;
          html += `<div style="grid-column:1/3; text-align:center; font-size:var(--fs-sm); color:var(--text-muted)">${tsLabel} — difference moyenne : ${meanDiff} / 255</div>`;
        }
        html += `</div>`;
        // Remplace le bouton par le grid (idempotent : 2e clic n'a pas d'effet).
        container.innerHTML = html;
      } catch (err) {
        if (msgEl) {
          msgEl.textContent = "Erreur reseau.";
          msgEl.style.color = "var(--danger, #f87171)";
        }
        console.error("[lib-duplicates] frames", err);
        btn.disabled = false;
      }
    });
  }, 0);
}

/* --- Helpers -------------------------------------------------- */

function _fmtSize(bytes) {
  // V6-04 : delegue a fmtBytes locale-aware (core/format.js).
  return _fmtBytesShared(bytes);
}

function _hookEvents() {
  $("libBtnCheckDups")?.addEventListener("click", () => _loadDuplicates());
}
