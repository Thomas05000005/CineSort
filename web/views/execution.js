/* views/execution.js — Apply + undo + conflicts */

/* --- Formatting -------------------------------------------- */

function formatApplyResult(result, dryRun) {
  if (!result || typeof result !== "object") return "Resultat indisponible.";
  const lines = [
    dryRun ? "Mode simulation (dry-run)" : "Mode reel",
    `Run : ${result.run_id || state.runId || "—"}`,
    "",
    `Renommes : ${result.renamed || 0}`,
    `Deplaces : ${result.moved || 0}`,
    `Ignores : ${result.skipped || 0}`,
    `Erreurs : ${result.errors || 0}`,
  ];
  if (result.quarantined) lines.push(`Quarantaine : ${result.quarantined}`);
  if (result.cleanup_residual_diagnostic) {
    const d = result.cleanup_residual_diagnostic;
    lines.push("", "Nettoyage residuel :",
      `  Dossiers traites : ${d.processed || 0}`,
      `  Fichiers deplaces : ${d.files_moved || 0}`);
  }
  if (Array.isArray(result.skip_reasons) && result.skip_reasons.length) {
    lines.push("", "Raisons de skip :");
    for (const s of result.skip_reasons.slice(0, 10)) {
      lines.push(`  - ${String(s.path || "?").split(/[\\/]/).pop()}: ${s.reason || "?"}`);
    }
    if (result.skip_reasons.length > 10) lines.push(`  ... et ${result.skip_reasons.length - 10} autres.`);
  }
  return lines.join("\n");
}

function formatUndoPreview(preview) {
  if (!preview || typeof preview !== "object") return "Previsualisation indisponible.";
  const c = preview.counts || {};
  const cats = preview.categories || {};
  const lines = [
    `Run : ${preview.run_id || state.runId || "—"}`,
    `Batch : ${preview.batch_id || "—"}`,
    `Undo possible : ${preview.can_undo ? "oui" : "non"}`,
    "",
    `Operations : ${c.total || 0} (reversibles : ${c.reversible || 0})`,
    `Conflits prevus : ${c.conflicts_predicted || 0}`,
  ];
  if (Number(cats.empty_folder_dirs || 0) > 0) lines.push(`Dossiers vides : ${cats.empty_folder_dirs}`);
  if (Number(cats.cleanup_residual_dirs || 0) > 0) lines.push(`Dossiers residuels : ${cats.cleanup_residual_dirs}`);
  if (preview.message) lines.push("", preview.message);
  return lines.join("\n");
}

function formatUndoExecution(result, dryRun) {
  if (!result || typeof result !== "object") return "Resultat indisponible.";
  const c = result.counts || {};
  const lines = [
    dryRun ? "Annulation test" : "Annulation reelle",
    `Run : ${result.run_id || state.runId || "—"}`,
    `Statut : ${result.status || "—"}`,
    "",
    `Restaurees : ${c.done || 0}`,
    `Sautees : ${c.skipped || 0}`,
    `Echecs : ${c.failed || 0}`,
  ];
  if (result.message) lines.push("", result.message);
  return lines.join("\n");
}

/* --- Duplicates / Conflicts -------------------------------- */

async function checkDuplicates() {
  if (!state.runId) return null;
  const decisions = gatherDecisions();
  return apiCall("check_duplicates", () => window.pywebview.api.check_duplicates(state.runId, decisions), {
    fallbackMessage: "Impossible de verifier les conflits.",
  });
}

function renderConflictsSummary(dup) {
  const total = dup ? Number(dup.total_groups || 0) : 0;
  if ($("execConflictsBadge")) {
    if (total > 0) {
      $("execConflictsBadge").className = "badge badge--warn";
      $("execConflictsBadge").textContent = `${total} conflit(s)`;
    } else {
      $("execConflictsBadge").className = "badge badge--ok";
      $("execConflictsBadge").textContent = "0 conflit";
    }
  }
  if ($("execConflictsDetail")) {
    $("execConflictsDetail").textContent = total > 0
      ? `${total} doublon(s) potentiel(s) détecté(s). Vérifiez avant d'appliquer.`
      : "Aucun conflit détecté.";
  }

  /* Render conflicts table — avec comparaison qualite si disponible */
  const groups = (dup && Array.isArray(dup.groups)) ? dup.groups : [];
  renderGenericTable("dupTbody", {
    rows: groups,
    columns: [
      { render: (g) => escapeHtml(g.title || g.target || g.film || "?") + (g.year ? ` (${g.year})` : "") },
      { render: (g) => g.comparison ? _renderComparisonBadge(g.comparison) : escapeHtml(g.issue || g.reason || "?") },
      { render: (g) => String(g.row_count || (Array.isArray(g.rows) ? g.rows.length : g.rows) || 0) },
      { render: (g) => {
        if (!g.comparison) return g.exists ? '<span class="badge badge--warn">Oui</span>' : '<span class="badge badge--neutral">Non</span>';
        const rids = (Array.isArray(g.rows) ? g.rows : []).map(r => String(r.row_id || "")).filter(Boolean);
        return `<button class="btn btn-sm" data-action="show-comparison" data-comparison="${escapeHtml(JSON.stringify(g.comparison))}" data-title="${escapeHtml(g.title || "")}" data-rid-a="${escapeHtml(rids[0] || "")}" data-rid-b="${escapeHtml(rids[1] || "")}">Details</button>`;
      }},
    ],
    emptyTitle: "Aucun conflit.",
  });

  // Event delegation pour les boutons de comparaison (pas de onclick inline)
  const tbody = $("dupTbody");
  if (tbody) {
    tbody.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-action='show-comparison']");
      if (btn) _showComparisonModal(btn);
    });
  }
}

function _renderComparisonBadge(cmp) {
  if (!cmp) return "";
  const w = cmp.winner;
  if (w === "a") return '<span class="badge badge--ok">A meilleur</span>';
  if (w === "b") return '<span class="badge badge--ok">B meilleur</span>';
  return '<span class="badge badge--neutral">Equivalent</span>';
}

function _showComparisonModal(btnEl) {
  try {
    const cmp = JSON.parse(btnEl.dataset.comparison || "{}");
    const title = btnEl.dataset.title || "Doublon";
    const ridA = btnEl.dataset.ridA || "";
    const ridB = btnEl.dataset.ridB || "";
    openModal("modalCompare");
    const modal = $("modalCompare");
    if (!modal) return;
    const body = modal.querySelector(".modal-body") || modal;
    body.innerHTML = _buildComparisonHtml(cmp, title);
    // Bouton "Comparaison perceptuelle" si les deux row_ids sont disponibles
    if (ridA && ridB) {
      const extra = document.createElement("div");
      extra.style.marginTop = "var(--sp-3)";
      extra.innerHTML = `
        <button class="btn btn--compact" id="btnPerceptualCompare" data-rid-a="${escapeHtml(ridA)}" data-rid-b="${escapeHtml(ridB)}">
          Comparaison perceptuelle
        </button>
        <span id="perceptualCompareMsg" class="text-muted"></span>
        <div id="perceptualCompareResult" style="margin-top:var(--sp-3)"></div>
      `;
      body.appendChild(extra);
      $("btnPerceptualCompare")?.addEventListener("click", () => _runPerceptualCompare(ridA, ridB));
    }
  } catch (e) { console.error("[comparison modal]", e); }
}

async function _runPerceptualCompare(ridA, ridB) {
  const msg = $("perceptualCompareMsg");
  const result = $("perceptualCompareResult");
  if (msg) msg.textContent = " Analyse en cours...";
  try {
    const r = await apiCall("compare_perceptual", () => window.pywebview.api.compare_perceptual(state.runId || currentContextRunId(), ridA, ridB));
    if (!r || r.ok === false) {
      if (msg) msg.textContent = " Comparaison impossible : " + (r?.message || "erreur");
      return;
    }
    if (msg) msg.textContent = "";
    if (result) result.innerHTML = _buildPerceptualHtml(r);
  } catch (err) {
    if (msg) msg.textContent = " Erreur : " + err;
  }
}

function _buildPerceptualHtml(r) {
  // API compare_perceptual retourne {ok, comparison: {...}} (cf perceptual_support.py)
  const cmp = r.comparison || r;
  const scoreA = Number(cmp.score_a ?? 0);
  const scoreB = Number(cmp.score_b ?? 0);
  const verdict = String(cmp.winner_label || cmp.recommendation || "");
  const criteria = Array.isArray(cmp.criteria) ? cmp.criteria : [];
  let html = `<div class="card" style="padding:var(--sp-3)">
    <h4 style="margin-top:0">Similarite perceptuelle</h4>`;

  // §16b v7.5.0 — Score composite V2 cote-a-cote si dispo
  const gsvA = cmp.global_score_v2_a || cmp.score_v2_a;
  const gsvB = cmp.global_score_v2_b || cmp.score_v2_b;
  if ((gsvA || gsvB) && typeof window.renderScoreV2CompareHtml === "function") {
    html += window.renderScoreV2CompareHtml(gsvA, gsvB);
  } else if (scoreA || scoreB) {
    html += `<p><strong>Scores :</strong> A ${scoreA}/100 — B ${scoreB}/100</p>`;
  }
  if (verdict) html += `<p class="text-muted">${esc(verdict)}</p>`;

  if (criteria.length) {
    html += '<table class="compare-table" style="margin-top:var(--sp-2)"><thead><tr><th>Critere</th><th>A</th><th>B</th><th>Winner</th></tr></thead><tbody>';
    for (const c of criteria) {
      html += `<tr><td>${esc(c.criterion || c.label || c.name || "?")}</td><td>${esc(c.value_a ?? "-")}</td><td>${esc(c.value_b ?? "-")}</td><td>${esc(c.winner || "-")}</td></tr>`;
    }
    html += "</tbody></table>";
  }
  html += "</div>";
  return html;
}

function _compareTierColor(tier) {
  const t = String(tier || "").toLowerCase();
  if (t === "platinum") return "#A78BFA";
  if (t === "gold") return "#FBBF24";
  if (t === "silver") return "#9CA3AF";
  if (t === "bronze") return "#FB923C";
  return "#EF4444"; // Reject / unknown
}

function _compareCard(side, cmp) {
  // side = "a" ou "b"
  const isA = side === "a";
  const name = isA ? (cmp.file_a_name || "Fichier A") : (cmp.file_b_name || "Fichier B");
  const size = isA ? cmp.file_a_size : cmp.file_b_size;
  const quality = isA ? (cmp.quality_a || {}) : (cmp.quality_b || {});
  const verdict = isA ? cmp.verdict_a : cmp.verdict_b;
  const isWinner = cmp.winner === side;
  const isTie = cmp.winner === "tie";
  const tierColor = _compareTierColor(quality.tier);
  const verdictColor = isWinner ? "#34D399" : (isTie ? "#9CA3AF" : "#FB923C");
  const verdictIcon = isWinner ? "✓" : (isTie ? "≡" : "⚠");
  const borderColor = isWinner ? "#34D399" : (isTie ? "var(--border)" : "rgba(251,146,60,.4)");

  // Récupérer les valeurs techniques depuis les critères
  const byName = {};
  for (const c of (cmp.criteria || [])) {
    byName[c.name] = isA ? c.value_a : c.value_b;
  }
  const resolution = byName.resolution || "?";
  const codec = byName.video_codec || byName.codec || "?";
  const bitrate = byName.bitrate || "?";
  const audio = byName.audio_codec || byName.audio || "?";
  const channels = byName.audio_channels || byName.channels || "";
  const hdr = byName.hdr;

  return `<div class="compare-card" style="flex:1; min-width:0; padding:.9em; border:2px solid ${borderColor}; border-radius:8px; background:var(--bg-raised)">
    <div class="font-xs text-muted" style="margin-bottom:.2em; letter-spacing:.05em; text-transform:uppercase">Version ${side.toUpperCase()}</div>
    <div class="mono font-sm" style="word-break:break-all; font-weight:600; margin-bottom:.6em" title="${escapeHtml(name)}">${escapeHtml(name)}</div>

    <div class="font-sm" style="line-height:1.6; color:var(--text-secondary)">
      <div><strong>${escapeHtml(String(resolution))}</strong> · ${escapeHtml(String(codec).toUpperCase())} · ${escapeHtml(String(bitrate))}</div>
      <div>${escapeHtml(String(audio).toUpperCase())}${channels && channels !== "?" ? " " + escapeHtml(String(channels)) : ""}</div>
      ${hdr && hdr !== "-" && hdr !== "?" ? `<div class="text-muted">${escapeHtml(String(hdr))}</div>` : ""}
      <div style="margin-top:.3em"><strong>${escapeHtml(_formatFileSize(size || 0))}</strong></div>
    </div>

    <hr style="border:0; border-top:1px solid var(--border); margin:.7em 0">

    <div style="display:flex; align-items:center; justify-content:space-between">
      <div>
        <div class="font-xs text-muted">Score</div>
        <div style="font-size:1.4em; font-weight:700; color:${tierColor}">${quality.score || "?"}</div>
      </div>
      <div style="text-align:right">
        <div class="font-xs text-muted">Tier</div>
        <div>${typeof tierPill === "function" ? tierPill(quality.tier || "?", {compact: true}) : `<span class="font-sm" style="font-weight:600; color:${tierColor}">${escapeHtml(quality.tier || "?")}</span>`}</div>
      </div>
    </div>

    <div style="margin-top:.6em; padding:.35em .5em; border-radius:4px; background:${verdictColor}22; color:${verdictColor}; font-weight:600; font-size:var(--fs-sm); text-align:center">
      ${verdictIcon} ${escapeHtml(verdict || "")}
    </div>
  </div>`;
}

function _buildComparisonHtml(cmp, title) {
  // P3.1 : rendu côte-à-côte type mockup utilisateur (remplace la table classique).
  const recommendation = cmp.recommendation || "";
  const savings = Number(cmp.size_savings) || 0;

  let html = `<div class="flex gap-3" style="align-items:stretch; flex-wrap:wrap">
    ${_compareCard("a", cmp)}
    ${_compareCard("b", cmp)}
  </div>`;

  if (recommendation) {
    html += `<div class="mt-3 p-2" style="background:rgba(96,165,250,.1); border-left:3px solid #60A5FA; border-radius:4px">
      <div class="font-sm" style="font-weight:600; color:#60A5FA; margin-bottom:.2em">Recommandation</div>
      <div class="font-sm">${escapeHtml(recommendation)}${savings > 0 ? ` — économie potentielle ${escapeHtml(_formatFileSize(savings))}` : ""}</div>
    </div>`;
  }

  // Détail critère par critère (caché par défaut, expand au besoin)
  html += `<details class="mt-3"><summary class="font-sm" style="cursor:pointer; font-weight:600">Voir le détail critère par critère</summary>`;
  html += '<div class="table-wrap mt-2"><table class="compare-table"><thead><tr><th>Critère</th><th>Version A</th><th>Version B</th><th>Points</th></tr></thead><tbody>';
  for (const c of (cmp.criteria || [])) {
    const pts = Number(c.points_delta || 0);
    const ptsStr = pts === 0 ? "=" : (pts > 0 ? `A+${pts}` : `B+${-pts}`);
    const ptsColor = pts === 0 ? "var(--text-muted)" : (pts > 0 ? "#34D399" : "#F59E0B");
    const aCls = c.winner === "a" ? 'style="color:#34D399; font-weight:600"' : "";
    const bCls = c.winner === "b" ? 'style="color:#34D399; font-weight:600"' : "";
    html += `<tr><td>${esc(c.label)}</td><td ${aCls}>${esc(c.value_a || "?")}</td><td ${bCls}>${esc(c.value_b || "?")}</td><td class="mono font-xs" style="color:${ptsColor}; text-align:right">${ptsStr}</td></tr>`;
  }
  html += '</tbody></table></div></details>';

  return html;
}

function _criterionBadge(winner) {
  if (winner === "a" || winner === "b") return '<span class="badge badge--ok compare-winner">✓</span>';
  if (winner === "tie") return '<span class="badge badge--neutral">=</span>';
  return '<span class="badge badge--neutral">?</span>';
}

/* _formatFileSize supprime : utiliser fmtFileSize (core/format.js). */
const _formatFileSize = fmtFileSize;

/* --- Apply ------------------------------------------------- */

async function applySelected() {
  console.log("[execution] apply");
  if (state.applyInFlight) {
    setStatusMessage("applyMsg", "Execution en cours...", { loading: true });
    return;
  }
  if (!state.runId) {
    setStatusMessage("applyMsg", "Lancez d'abord une analyse.", { error: true });
    flashActionButton("btnApply", "error");
    return;
  }

  const dry = !!$("ckDryRun")?.checked;
  const quar = !!$("ckQuarantine")?.checked;
  state.applyInFlight = true;
  const btn = $("btnApply");
  if (btn) btn.disabled = true;

  try {
    setStatusMessage("applyMsg", "Execution en cours...", { loading: true });
    if ($("applyResult")) $("applyResult").textContent = "...";

    /* Save decisions first */
    const saveRes = await persistValidation();
    if (!saveRes?.ok) {
      setStatusMessage("applyMsg", `Stoppee : ${saveRes?.message || "decisions non enregistrees."}`, { error: true });
      flashActionButton(btn, "error");
      return;
    }

    /* Check duplicates */
    const decisions = gatherDecisions();
    const dup = await checkDuplicates();
    if (dup && dup.ok && Number(dup.total_groups || 0) > 0) {
      renderConflictsSummary(dup);
      const proceed = await uiConfirm({
        title: "Conflits détectés",
        message: `${dup.total_groups} doublon(s) détecté(s). Continuer ?`,
        confirmLabel: "Continuer", danger: true,
      });
      if (!proceed) {
        setStatusMessage("applyMsg", "Annulee (conflits).");
        return;
      }
    }

    /* Execute apply — l'appel est bloquant cote backend. Indicateur visuel
       pendant l'attente : spinner + message clair. Le detail arrive a la fin. */
    const approvedCount = Object.values(decisions).filter(d => d && d.ok).length;
    const mode = dry ? "dry-run" : "reel";
    setStatusMessage("applyMsg",
      `\u29F3 Application ${mode} en cours (${approvedCount} film(s) approuve(s))...`,
      { loading: true });
    if ($("applyResult")) $("applyResult").textContent = `Application ${mode} de ${approvedCount} film(s) en cours...\nCette operation peut prendre plusieurs minutes.\nLes details s'afficheront ici a la fin.`;

    const r = await apiCall("apply", () => window.pywebview.api.apply(state.runId, decisions, dry, quar), {
      statusId: "applyMsg", fallbackMessage: "Erreur pendant l'application.",
    });
    if (!r?.ok) {
      setStatusMessage("applyMsg", "Application impossible.", { error: true });
      if ($("applyResult")) $("applyResult").textContent = r?.message || "";
      flashActionButton(btn, "error");
      if (typeof toast === "function") toast({ type: "error", text: r?.message || "Application impossible." });
      return;
    }

    setStatusMessage("applyMsg", "Execution terminee.", { success: true });
    if ($("applyResult")) $("applyResult").textContent = formatApplyResult(r.result, dry);
    /* J15 : dispatch event pour l'activity log */
    if (typeof window !== "undefined") {
      document.dispatchEvent(new CustomEvent("cinesort:event", {
        detail: { type: "apply", msg: dry ? `Dry-run : ${approvedCount} film(s).` : `Apply reel : ${approvedCount} film(s) deplaces.` }
      }));
    }

    if (typeof toast === "function") {
      if (dry) {
        toast({ type: "success", text: `Dry-run termine : ${approvedCount} film(s) traite(s).` });
      } else {
        /* K17 : confetti sur apply reel si >=10 films deplaces */
        if (approvedCount >= 10 && typeof launchConfetti === "function") {
          launchConfetti({ count: Math.min(160, approvedCount * 4) });
        }
        /* E2 : toast avec bouton "Annuler" qui declenche undo immediatement. */
        toast({
          type: "success",
          text: `Application reussie : ${approvedCount} film(s) deplace(s).`,
          actionLabel: "Annuler",
          onAction: () => {
            try {
              const ckUndo = $("ckUndoDryRun");
              if (ckUndo) ckUndo.checked = false;
              undoLastApply();
            } catch (e) { console.error("[undo from toast]", e); }
          },
        });
      }
    }
    state.cleanupResidualLastResult = {
      run_id: String(state.runId || ""),
      dry_run: !!dry,
      diagnostic: r.result?.cleanup_residual_diagnostic || null,
    };
    flashActionButton(btn, "ok");
    if (!dry) await refreshUndoPreview({ silent: true });
  } finally {
    state.applyInFlight = false;
    if (btn) btn.disabled = false;
  }
}

/* --- Undo -------------------------------------------------- */

async function refreshUndoPreview(opts = {}) {
  const rid = currentContextRunId();
  if (!rid) return;
  const r = await apiCall("undo_preview", () => window.pywebview.api.undo_last_apply_preview(rid));
  state.undoPreview = r;
  if ($("undoSummary")) {
    if (r?.can_undo) {
      $("undoSummary").textContent = `Batch : ${r.batch_id || "?"} — ${r.counts?.total || 0} operation(s)`;
      if ($("btnUndoRun")) $("btnUndoRun").disabled = false;
    } else {
      $("undoSummary").textContent = "Aucune operation annulable.";
      if ($("btnUndoRun")) $("btnUndoRun").disabled = true;
    }
  }
}

async function runUndoBatch() {
  const rid = currentContextRunId();
  if (!rid || state.undoInFlight) return;
  const dry = !!$("ckUndoDryRun")?.checked;
  state.undoInFlight = true;
  try {
    setStatusMessage("applyMsg", "Annulation en cours...", { loading: true });
    const r = await apiCall("undo_last_apply", () => window.pywebview.api.undo_last_apply(rid, dry), {
      statusId: "applyMsg",
    });

    // P1.2 : refus atomique si un fichier a été modifié depuis l'apply
    if (r?.status === "ABORTED_HASH_MISMATCH") {
      const details = (r.preverify?.mismatch_details || []).slice(0, 5);
      const lines = details.map(d => `• ${d.dst_path}\n  (${d.reason})`).join("\n");
      const more = r.preverify?.hash_mismatch_count > details.length ? `\n...et ${r.preverify.hash_mismatch_count - details.length} autre(s).` : "";
      const msg = `Annulation refusée : ${r.preverify?.hash_mismatch_count} fichier(s) ont été modifiés depuis l'apply.\n\n${lines}${more}\n\nAucun fichier n'a été déplacé. Relancez en cochant "Forcer" pour passer outre (les fichiers modifiés seront laissés en place).`;
      if ($("undoResult")) $("undoResult").textContent = msg;
      setStatusMessage("applyMsg", "Annulation refusee (fichiers modifies).", { error: true });
      if (typeof toast === "function") {
        toast({ type: "error", text: "Annulation refusée : fichiers modifiés depuis l'apply." });
      }
      return;
    }

    if ($("undoResult")) $("undoResult").textContent = r?.ok ? formatUndoExecution(r.result || r, dry) : (r?.message || "Erreur");
    if (r?.ok) {
      setStatusMessage("applyMsg", dry ? "Preview undo terminee." : "Annulation terminee.", { success: true });
      if (typeof toast === "function") {
        toast({ type: "success", text: dry ? "Preview undo terminee." : "Annulation terminee." });
      }
    } else if (typeof toast === "function") {
      toast({ type: "error", text: r?.message || "Annulation impossible." });
    }
  } finally {
    state.undoInFlight = false;
  }
}

/* --- Undo V5 (per-film) ------------------------------------ */

async function loadUndoV5Detail() {
  const rid = currentContextRunId();
  if (!rid) return;
  setStatusMessage("undoV5Msg", "Chargement...", { loading: true });
  const r = await apiCall("undo_by_row_preview", () => window.pywebview.api.undo_by_row_preview(rid));
  if (!r?.ok) {
    setStatusMessage("undoV5Msg", r?.message || "Erreur", { error: true });
    return;
  }
  state.undoV5BatchId = r.batch_id || null;
  const rows = Array.isArray(r.rows) ? r.rows : [];
  renderGenericTable("undoV5Tbody", {
    rows,
    columns: [
      { render: (r) => `<input type="checkbox" data-undo-row="${escapeHtml(r.row_id || r.id || "")}" checked />` },
      { render: (r) => escapeHtml(r.title || r.path || "?") },
      { render: (r) => escapeHtml(r.operation || r.op_type || "?") },
      { render: (r) => r.reversible !== false ? '<span class="badge badge--ok">OK</span>' : '<span class="badge badge--bad">Non</span>' },
    ],
    emptyTitle: "Aucune operation.",
  });
  setStatusMessage("undoV5Msg", `${rows.length} operation(s) chargees.`, { success: true, clearMs: 2000 });
}

function getSelectedUndoV5Rows() {
  return Array.from(qsa("#undoV5Tbody input[data-undo-row]:checked")).map(ch => ch.dataset.undoRow);
}

async function executeUndoV5(dryRun) {
  const rid = currentContextRunId();
  const sel = getSelectedUndoV5Rows();
  if (!rid || !sel.length) {
    setStatusMessage("undoV5Msg", "Selectionnez au moins un film.", { error: true });
    return;
  }
  setStatusMessage("undoV5Msg", dryRun ? "Preview..." : "Annulation...", { loading: true });
  const r = await apiCall("undo_selected_rows", () => window.pywebview.api.undo_selected_rows(rid, sel, dryRun, state.undoV5BatchId));
  if (r?.ok) {
    setStatusMessage("undoV5Msg", dryRun ? "Preview terminee." : "Annulation terminee.", { success: true, clearMs: 3000 });
    if ($("undoResult")) $("undoResult").textContent = formatUndoExecution(r.result || r, dryRun);
  } else {
    setStatusMessage("undoV5Msg", r?.message || "Erreur", { error: true });
  }
}

/* --- Cleanup residual -------------------------------------- */

async function refreshCleanupResidualPreview() {
  const rid = currentContextRunId();
  if (!rid) return;
  const r = await apiCall("cleanup_preview", () => window.pywebview.api.get_cleanup_residual_preview(rid));
  state.cleanupResidualPreview = r;
  if ($("execCleanupBody")) {
    if (r?.ok && r.total > 0) {
      $("execCleanupBody").textContent = `${r.total} dossier(s) a nettoyer. ${r.files || 0} fichier(s) concernes.`;
    } else {
      $("execCleanupBody").textContent = "Aucun nettoyage en attente.";
    }
  }
}

/* --- P1.3 : Preview apply visuel --------------------------- */

function _fmtTier(label) {
  const m = {
    high: { text: "Haute", cls: "badge--ok" },
    med: { text: "Moy", cls: "badge--warn" },
    low: { text: "Faible", cls: "badge--bad" },
  };
  const k = (label || "").toLowerCase();
  const entry = m[k] || { text: label || "?", cls: "badge" };
  return `<span class="badge ${entry.cls}" style="font-size:var(--fs-xs)">${entry.text}</span>`;
}

function _fmtChangeTypeLabel(t) {
  const map = {
    rename_folder: "Renommage dossier",
    move_files: "Déplacement fichiers",
    move_mixed: "Renommage + déplacement",
    noop: "Aucun changement",
  };
  return map[t] || t || "Changement";
}

function _shortenPath(p, max = 64) {
  const s = String(p || "");
  if (s.length <= max) return s;
  return s.slice(0, Math.floor(max * 0.4)) + " … " + s.slice(-Math.floor(max * 0.5));
}

function _buildPreviewFilmCard(film) {
  const warns = (film.warnings || []).filter(w => w && !w.startsWith("subtitle_missing_"));
  const warnTags = warns.length
    ? ` <span class="badge badge--warn" title="${escapeHtml(warns.join(", "))}" style="font-size:var(--fs-xs)">${warns.length} alerte${warns.length > 1 ? "s" : ""}</span>`
    : "";
  const opsLines = (film.ops || []).map(op => {
    const arrow = '<span style="color:var(--accent); margin:0 .5em">→</span>';
    return `<div class="mono font-xs" style="padding:.2em 0">
      <span style="color:var(--text-muted)">${escapeHtml(op.op_type)}</span>
      <div style="margin-left:.5em">
        <div>${escapeHtml(_shortenPath(op.src_path, 72))}</div>
        <div>${arrow}${escapeHtml(_shortenPath(op.dst_path, 72))}</div>
      </div>
    </div>`;
  }).join("");
  const headerRight = `${_fmtTier(film.confidence_label)}${warnTags}`;
  return `<div class="card mb-2" style="padding:.75em">
    <div class="flex items-center justify-between gap-2">
      <div>
        <strong>${escapeHtml(film.title || "?")}</strong>
        ${film.year ? `<span class="text-muted"> (${escapeHtml(String(film.year))})</span>` : ""}
        <div class="font-xs text-muted">${escapeHtml(_fmtChangeTypeLabel(film.change_type))}</div>
      </div>
      <div>${headerRight}</div>
    </div>
    <div class="mt-2">${opsLines}</div>
  </div>`;
}

async function showApplyPreview() {
  if (!state.runId) {
    setStatusMessage("applyMsg", "Lancez un scan avant de demander un apercu.", { error: true });
    return;
  }
  const modal = $("modalApplyPreview");
  const body = $("applyPreviewBody");
  if (!modal || !body) return;
  body.innerHTML = '<div class="text-secondary">Calcul du plan...</div>';
  openModal("modalApplyPreview");

  const decisions = gatherDecisions();
  const r = await apiCall("build_apply_preview", () => window.pywebview.api.build_apply_preview(state.runId, decisions), {
    fallbackMessage: "Impossible de construire l'apercu.",
  });
  if (!r?.ok) {
    body.innerHTML = `<div class="alert alert--danger">${escapeHtml(r?.message || "Erreur de calcul.")}</div>`;
    return;
  }
  const t = r.totals || {};
  const films = r.films || [];
  const header = `<div class="card mb-3" style="padding:.75em">
    <div class="flex gap-3 items-center">
      <div><strong>${t.films || 0}</strong> <span class="text-muted">film(s)</span></div>
      <div><strong>${t.changes_count || 0}</strong> <span class="text-muted">changement(s)</span></div>
      ${t.noop_count ? `<div><strong>${t.noop_count}</strong> <span class="text-muted">déjà conforme(s)</span></div>` : ""}
      ${t.quarantined ? `<div class="text-warn"><strong>${t.quarantined}</strong> en quarantaine</div>` : ""}
      ${t.errors ? `<div class="text-danger"><strong>${t.errors}</strong> erreur(s)</div>` : ""}
    </div>
    <div class="font-xs text-muted mt-1">Total ${t.total_ops || 0} opération(s) prévues. Aucun fichier n'a encore été touché.</div>
  </div>`;
  const filmsHtml = films.length
    ? films.map(_buildPreviewFilmCard).join("")
    : '<div class="text-secondary">Aucun film avec changement dans ce plan.</div>';
  body.innerHTML = header + filmsHtml;
}

/* --- P2.3 : Télécharger le journal d'audit ----------------- */

async function downloadApplyAudit(format = "jsonl") {
  if (!state.runId) {
    setStatusMessage("applyMsg", "Lancez un scan avant de télécharger l'audit.", { error: true });
    return;
  }
  const r = await apiCall("export_apply_audit", () => window.pywebview.api.export_apply_audit(state.runId, null, format), {
    fallbackMessage: "Impossible de récupérer le journal d'audit.",
  });
  if (!r?.ok) {
    setStatusMessage("applyMsg", r?.message || "Erreur.", { error: true });
    return;
  }
  if (r.count === 0 || !r.content) {
    setStatusMessage("applyMsg", "Aucune entrée d'audit disponible (apply réel nécessaire).", { error: true });
    return;
  }
  const mime = format === "csv" ? "text/csv" : "application/x-ndjson";
  const blob = new Blob([r.content], { type: mime + ";charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  a.download = `apply_audit_${state.runId}_${ts}.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  setStatusMessage("applyMsg", `Journal d'audit téléchargé (${r.count} entrée(s)).`, { success: true, clearMs: 3000 });
}

/* --- Refresh execution view -------------------------------- */

async function refreshExecutionView(opts = {}) {
  // Audit ID-ROB-002 : Promise.allSettled pour qu'un seul refresh en echec
  // ne casse pas les autres (preview undo / duplicates / residuels independants).
  const labels = ["undoPreview", "duplicates", "cleanupResidual"];
  const results = await Promise.allSettled([
    refreshUndoPreview(opts),
    checkDuplicates().then(dup => { if (dup) renderConflictsSummary(dup); }),
    refreshCleanupResidualPreview(),
  ]);
  const failed = labels.filter((_, i) => results[i].status !== "fulfilled");
  if (failed.length > 0) console.warn("[execution] refresh partiel, echecs:", failed);
}

/* --- Events ------------------------------------------------ */

function hookExecutionEvents() {
  $("btnApply")?.addEventListener("click", applySelected);
  $("btnPreviewApply")?.addEventListener("click", showApplyPreview);
  $("btnApplyFromPreview")?.addEventListener("click", () => {
    // Depuis la preview, basculer en mode apply réel (décocher dry-run)
    const dr = $("ckDryRun");
    if (dr) dr.checked = false;
    // Lancer l'apply normal
    applySelected();
  });
  $("btnDownloadAudit")?.addEventListener("click", () => downloadApplyAudit("jsonl"));
  $("btnDownloadAuditCsv")?.addEventListener("click", () => downloadApplyAudit("csv"));
  $("btnUndoPreview")?.addEventListener("click", () => {
    refreshUndoPreview();
    if (state.undoPreview) {
      if ($("undoResult")) $("undoResult").textContent = formatUndoPreview(state.undoPreview);
    }
  });
  $("btnUndoRun")?.addEventListener("click", runUndoBatch);

  /* Undo V5 */
  $("btnUndoV5Load")?.addEventListener("click", loadUndoV5Detail);
  $("btnUndoV5SelectAll")?.addEventListener("click", () => qsa("#undoV5Tbody input[data-undo-row]").forEach(ch => ch.checked = true));
  $("btnUndoV5DeselectAll")?.addEventListener("click", () => qsa("#undoV5Tbody input[data-undo-row]").forEach(ch => ch.checked = false));
  $("btnUndoV5Preview")?.addEventListener("click", () => executeUndoV5(true));
  $("btnUndoV5Execute")?.addEventListener("click", async () => {
    const proceed = await uiConfirm({
      title: "Annulation selective",
      message: `Annuler ${getSelectedUndoV5Rows().length} operation(s) ?`,
      confirmLabel: "Annuler", danger: true,
    });
    if (proceed) await executeUndoV5(false);
  });
}
