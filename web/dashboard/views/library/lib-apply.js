/* lib-apply.js — Section 5 : Application (apply, undo, checklist, diagnostic) */

import { $, escapeHtml } from "../../core/dom.js";
import { apiPost } from "../../core/api.js";
import { showModal } from "../../components/modal.js";
import { libState } from "./library.js";
import { buildDecisionsPayload } from "./lib-validation.js";

let _checklistState = { saved: false, dryRunDone: false, dupsChecked: false };

/* --- Point d'entree ------------------------------------------- */

export function initApply(state) {
  _checklistState = { saved: false, dryRunDone: false, dupsChecked: false };
  const el = $("libApplyContent");
  if (!el) return;
  _render(el);
}

/* --- Rendu ---------------------------------------------------- */

function _render(el) {
  el.innerHTML = `
    <div class="card">
      <h4>Paramètres</h4>
      <div class="flex gap-4 mt-2">
        <label class="checkbox-row"><input type="checkbox" id="libCkDryRun" checked data-testid="lib-apply-ck-dryrun"> Mode test (dry-run)</label>
        <label class="checkbox-row"><input type="checkbox" id="libCkQuarantine"> Quarantaine non-OK</label>
      </div>
    </div>

    <div class="card mt-4">
      <h4>Nettoyage résiduel</h4>
      <div id="libCleanupPreview" class="mt-2 text-muted">Chargement...</div>
    </div>

    <div class="card mt-4">
      <h4>Sécurité — Checklist</h4>
      <div class="mt-2">
        <label class="checkbox-row"><input type="checkbox" id="libCheckSaved" disabled data-testid="lib-apply-check-saved"> Validation sauvegardée</label>
        <label class="checkbox-row"><input type="checkbox" id="libCheckDryRun" disabled data-testid="lib-apply-check-dryrun"> Mode test lancé</label>
        <label class="checkbox-row"><input type="checkbox" id="libCheckDups" disabled data-testid="lib-apply-check-dups"> Doublons vérifiés</label>
      </div>
    </div>

    <div class="card mt-4">
      <details id="libDiagnosticDetails">
        <summary>+ Diagnostic de prévision</summary>
        <div id="libDiagnosticContent" class="mt-2 text-muted">Cliquez pour charger la prévision.</div>
      </details>
    </div>

    <div class="mt-4 flex gap-2">
      <button id="libBtnApply" class="btn btn-primary" data-testid="lib-apply-btn-run">Appliquer les lignes validées</button>
      <span id="libApplyMsg" class="status-msg"></span>
    </div>

    <div id="libApplyResult" class="mt-4" style="display:none" data-testid="lib-apply-result">
      <pre id="libApplyResultText" class="logs-box" style="max-height:200px;overflow-y:auto"></pre>
    </div>

    <div class="card mt-6">
      <h4>Annulation (Undo)</h4>
      <p class="text-muted font-sm">Prévisualisez avant tout undo réel. L'undo ne force jamais l'écrasement.</p>
      <div class="flex gap-2 mt-2">
        <button id="libBtnUndoPreview" class="btn btn--compact" data-testid="lib-apply-btn-undo">Prévisualiser</button>
        <button id="libBtnUndoExec" class="btn btn--compact" disabled data-testid="lib-apply-btn-undo-exec">Exécuter l'annulation</button>
        <label class="checkbox-row"><input type="checkbox" id="libCkUndoDry" checked> Mode test</label>
      </div>
      <div id="libUndoMsg" class="status-msg mt-2"></div>
    </div>
  `;
  _hookEvents();
  _loadCleanupPreview();
}

/* --- Cleanup preview ------------------------------------------ */

async function _loadCleanupPreview() {
  const el = $("libCleanupPreview");
  if (!el || !libState.runId) return;
  try {
    const res = await apiPost("get_cleanup_residual_preview", { run_id: libState.runId });
    const d = res.data || {};
    if (d.total_dirs || d.total_files) {
      el.innerHTML = `${d.total_dirs || 0} dossier(s), ${d.total_files || 0} fichier(s) seraient nettoyés.`;
    } else {
      el.textContent = "Aucun nettoyage prévu.";
    }
  } catch { el.textContent = "Impossible de charger la prévision."; }
}

/* --- Evenements ----------------------------------------------- */

function _hookEvents() {
  // Appliquer
  $("libBtnApply")?.addEventListener("click", _onApply);

  // Undo preview
  $("libBtnUndoPreview")?.addEventListener("click", _onUndoPreview);

  // Undo execution
  $("libBtnUndoExec")?.addEventListener("click", _onUndoExec);

  // Diagnostic details
  $("libDiagnosticDetails")?.addEventListener("toggle", (e) => {
    if (e.target.open) _loadDiagnostic();
  });

  // Cf #92 quick win #3 : Ctrl+Z = undo geste universel. Le shortcut
  // dispatch par core/keyboard.js declenche l'undo preview (jamais d'undo
  // direct sans preview, pour eviter une destruction accidentelle).
  // L'AbortController est associe a la duree de vie du DOM de la vue :
  // quand la vue est demontee, le listener est detache automatiquement.
  if (libState.runId && !libState._undoShortcutBound) {
    libState._undoShortcutBound = true;
    window.addEventListener("cinesort:undo-shortcut", () => {
      // Verifier que la vue Apply est toujours active (sinon ignorer).
      if (!libState.runId || !$("libBtnUndoPreview")) return;
      _onUndoPreview();
    });
  }
}

/* --- Apply ---------------------------------------------------- */

async function _onApply() {
  const btn = $("libBtnApply");
  if (btn) btn.disabled = true;
  const dryRun = !!$("libCkDryRun")?.checked;
  const quarantine = !!$("libCkQuarantine")?.checked;

  _showMsg("libApplyMsg", dryRun ? "Dry-run en cours..." : "Application en cours...");

  try {
    const decisions = buildDecisionsPayload();
    const approvedCount = Object.values(decisions).filter(d => d.ok).length;
    if (approvedCount === 0) { _showMsg("libApplyMsg", "Aucun film approuvé.", true); if (btn) btn.disabled = false; return; }

    if (!dryRun) {
      // Dry-run obligatoire d'abord
      const dryRes = await apiPost("apply", { run_id: libState.runId, decisions, dry_run: true, quarantine_unapproved: quarantine });
      const dryData = dryRes.data || {};
      const applied = dryData.applied ?? 0;
      const skipped = dryData.skipped ?? 0;

      // Demander confirmation
      const confirmed = await new Promise(resolve => {
        showModal({
          title: `Appliquer ${applied} film(s)`,
          body: `<p><strong>${applied}</strong> film(s) seront renommés/déplacés.</p>${skipped ? `<p>${skipped} ignoré(s).</p>` : ""}<p class="mt-4">Confirmer l'application réelle ?</p>`,
          actions: [
            { label: "Annuler", cls: "", onClick: () => resolve(false) },
            { label: "Confirmer", cls: "btn-primary", onClick: () => resolve(true) },
          ],
        });
      });
      if (!confirmed) { if (btn) btn.disabled = false; _showMsg("libApplyMsg", "Annulé."); return; }
    }

    // Execution
    const res = await apiPost("apply", { run_id: libState.runId, decisions, dry_run: dryRun, quarantine_unapproved: quarantine });
    const d = res.data || {};
    const applied = d.applied ?? 0;
    const skipped = d.skipped ?? 0;
    const failed = d.failed ?? 0;

    // Resultat detaille
    let resultText = `${dryRun ? "[DRY-RUN] " : ""}Résultat :\n`;
    resultText += `  Renommés/déplacés : ${applied}\n`;
    if (skipped) resultText += `  Ignorés : ${skipped}\n`;
    if (failed) resultText += `  Erreurs : ${failed}\n`;
    if (d.skip_reasons) {
      for (const [reason, count] of Object.entries(d.skip_reasons)) {
        resultText += `    - ${reason} : ${count}\n`;
      }
    }

    const resultEl = $("libApplyResult");
    const resultTextEl = $("libApplyResultText");
    if (resultEl) resultEl.style.display = "";
    if (resultTextEl) resultTextEl.textContent = resultText;

    _showMsg("libApplyMsg", dryRun ? `Dry-run : ${applied} film(s) seraient traités.` : `Application terminée : ${applied} film(s).`);

    // Mettre a jour la checklist
    if (dryRun) { _checklistState.dryRunDone = true; _updateChecklist(); }

  } catch { _showMsg("libApplyMsg", "Erreur réseau.", true); }
  finally { if (btn) btn.disabled = false; }
}

/* --- Undo ----------------------------------------------------- */

async function _onUndoPreview() {
  const btn = $("libBtnUndoPreview");
  if (btn) btn.disabled = true;
  try {
    const res = await apiPost("undo_last_apply", { run_id: libState.runId, dry_run: true });
    const d = res.data || {};
    if (!d.ok) {
      _showMsg("libUndoMsg", d.message || "Aucun apply à annuler.", true);
    } else {
      const count = d.count || d.operations_count || 0;
      _showMsg("libUndoMsg", `${count} opération(s) seraient restaurées.`);
      const undoExec = $("libBtnUndoExec");
      if (undoExec) undoExec.disabled = false;
    }
  } catch { _showMsg("libUndoMsg", "Erreur réseau.", true); }
  finally { if (btn) btn.disabled = false; }
}

async function _onUndoExec() {
  const dryRun = !!$("libCkUndoDry")?.checked;
  const btn = $("libBtnUndoExec");
  if (btn) btn.disabled = true;

  try {
    const res = await apiPost("undo_last_apply", { run_id: libState.runId, dry_run: dryRun });
    const d = res.data || {};
    _showMsg("libUndoMsg", d.ok ? `${dryRun ? "[TEST] " : ""}Annulation réussie.` : (d.message || "Échec."), !d.ok);
    // Cf #92 quick win #2 : refresh sidebar badges (counters faux apres undo
    // reel = perte confiance). On ne dispatch que pour les undo non-dry-run.
    if (d.ok && !dryRun) {
      window.dispatchEvent(new CustomEvent("cinesort:undo"));
    }
  } catch { _showMsg("libUndoMsg", "Erreur réseau.", true); }
  finally { if (btn) btn.disabled = false; }
}

/* --- Diagnostic ----------------------------------------------- */

async function _loadDiagnostic() {
  const el = $("libDiagnosticContent");
  if (!el || !libState.runId) return;
  el.textContent = "Chargement...";
  try {
    const decisions = buildDecisionsPayload();
    const approvedCount = Object.values(decisions).filter(d => d.ok).length;
    const rejectedCount = Object.values(decisions).filter(d => !d.ok).length;

    // Dry-run rapide pour la prevision
    const dryRes = await apiPost("apply", { run_id: libState.runId, decisions, dry_run: true, quarantine_unapproved: false });
    const d = dryRes.data || {};

    el.innerHTML = `
      <p>Films approuvés : <strong>${approvedCount}</strong> | Rejetés : <strong>${rejectedCount}</strong></p>
      <p>Seraient renommés/déplacés : <strong>${d.applied ?? 0}</strong></p>
      <p>Seraient ignorés : <strong>${d.skipped ?? 0}</strong></p>
      ${d.failed ? `<p class="text-danger">Erreurs potentielles : <strong>${d.failed}</strong></p>` : ""}
    `;
  } catch { el.textContent = "Erreur de chargement."; }
}

/* --- Checklist auto-update ------------------------------------ */

function _updateChecklist() {
  const saved = $("libCheckSaved");
  const dryRun = $("libCheckDryRun");
  const dups = $("libCheckDups");
  if (saved) saved.checked = _checklistState.saved;
  if (dryRun) dryRun.checked = _checklistState.dryRunDone;
  if (dups) dups.checked = _checklistState.dupsChecked;
}

/* --- Helpers -------------------------------------------------- */

function _showMsg(id, text, isError = false) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.className = "status-msg" + (isError ? " error" : " success");
}
