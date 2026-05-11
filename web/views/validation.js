/* views/validation.js — Validation table (fusion review + decisions) */

/* --- Draft auto (V2-03) ------------------------------------ */
/* Persiste les decisions in-memory dans localStorage pour survivre crash/refresh.
 * Cle : val_draft_<run_id>. TTL 30j. Nettoye apres save_validation reussi. */
const VAL_DRAFT_KEY_PREFIX = "val_draft_";
const VAL_DRAFT_TTL_MS = 30 * 24 * 60 * 60 * 1000;

let _draftSaveTimer = null;

function _scheduleDraftSave() {
  if (_draftSaveTimer) clearTimeout(_draftSaveTimer);
  _draftSaveTimer = setTimeout(_saveDraft, 500);
}

function _saveDraft() {
  if (!state.runId || !state.decisions) return;
  try {
    const payload = {
      ts: Date.now(),
      runId: state.runId,
      decisions: gatherDecisions(),
    };
    localStorage.setItem(VAL_DRAFT_KEY_PREFIX + state.runId, JSON.stringify(payload));
  } catch (e) {
    console.warn("[validation] draft save failed", e);
  }
}

function _checkAndOfferRestore() {
  if (!state.runId) return;
  let raw;
  try {
    raw = localStorage.getItem(VAL_DRAFT_KEY_PREFIX + state.runId);
  } catch (e) { return; }
  if (!raw) return;
  let draft;
  try {
    draft = JSON.parse(raw);
  } catch (e) { _clearDraft(); return; }
  if (!draft || !draft.decisions || typeof draft.decisions !== "object") return;

  const age = Date.now() - (draft.ts || 0);
  if (age > VAL_DRAFT_TTL_MS) {
    _clearDraft();
    return;
  }

  // Si toutes les decisions du draft sont identiques a l'etat courant, inutile de proposer.
  let differs = false;
  for (const [id, d] of Object.entries(draft.decisions)) {
    const cur = state.decisions[id];
    if (!cur || !!cur.ok !== !!d.ok || (cur.year || 0) !== (d.year || 0) || (cur.title || "") !== (d.title || "")) {
      differs = true; break;
    }
  }
  if (!differs) return;

  _showRestoreBanner(draft);
}

function _showRestoreBanner(draft) {
  if (document.getElementById("valDraftBanner")) return;
  // V6-04 : datetime locale-aware via core/format.js (window.formatDateTime).
  const date = (typeof window.formatDateTime === "function")
    ? window.formatDateTime(draft.ts)
    : new Date(draft.ts).toLocaleString();
  const count = Object.keys(draft.decisions || {}).length;
  const html = `<div class="alert alert--info" id="valDraftBanner" role="status" style="display:flex;gap:.6em;align-items:center;flex-wrap:wrap">
    <span>Decisions non sauvegardees du <strong>${escapeHtml(date)}</strong> (${count} films).</span>
    <button class="btn btn--compact" id="valDraftRestore">Restaurer</button>
    <button class="btn btn--compact" id="valDraftDiscard">Ignorer</button>
  </div>`;
  const root = document.getElementById("view-validation") || document.querySelector(".view-validation");
  if (!root) return;
  root.insertAdjacentHTML("afterbegin", html);
  document.getElementById("valDraftRestore")?.addEventListener("click", () => _restoreDraft(draft));
  document.getElementById("valDraftDiscard")?.addEventListener("click", () => _discardDraft());
}

function _restoreDraft(draft) {
  if (draft && draft.decisions && typeof draft.decisions === "object") {
    for (const [id, d] of Object.entries(draft.decisions)) {
      if (d && typeof d === "object") {
        state.decisions[id] = {
          ok: !!d.ok,
          title: String(d.title || ""),
          year: parseInt(d.year || 0, 10) || 0,
          edited: !!d.edited,
        };
      }
    }
  }
  document.getElementById("valDraftBanner")?.remove();
  if (typeof renderTable === "function") renderTable();
}

function _discardDraft() {
  _clearDraft();
  document.getElementById("valDraftBanner")?.remove();
}

function _clearDraft() {
  if (!state.runId) return;
  try {
    localStorage.removeItem(VAL_DRAFT_KEY_PREFIX + state.runId);
  } catch (e) { /* ignore */ }
}

/* --- Helpers ----------------------------------------------- */

function normalizeLooseText(txt) {
  return String(txt || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, " ").trim().toLowerCase();
}

function rowWarningFlags(row) {
  if (Array.isArray(row?.warning_flags) && row.warning_flags.length) {
    return row.warning_flags.map(x => String(x || "").trim()).filter(Boolean);
  }
  const notes = String(row?.notes || "").toLowerCase();
  const flags = [];
  if (notes.includes("nfo ignore: titre incoherent")) flags.push("nfo_title_mismatch");
  if (notes.includes("nfo ignore: annee incoherente")) flags.push("nfo_year_mismatch");
  if (notes.includes("conflit dossier/fichier")) flags.push("year_conflict_folder_file");
  if (notes.includes("dy=") && notes.includes("tmdb")) flags.push("tmdb_year_delta");
  return flags;
}

function rowChangeType(row, decision) {
  if (!row) return "none";
  if (String(row.kind || "").toLowerCase() === "collection") return "collection";
  const folder = String(row.folder || "").split(/[\\/]/).filter(Boolean).pop() || "";
  const target = String(decision?.title || row.proposed_title || "").trim();
  const targetYear = Number(decision?.year || row.proposed_year || 0);
  const folderYear = Number(row.year || 0);
  if (!target || target === folder) return "none";
  if (folderYear && targetYear && folderYear !== targetYear) return "fix_year";
  if (!folderYear && targetYear) return "add_year";
  return "rename";
}

function computeReviewRisk(row, decision) {
  let score = 0;
  const reasons = [];
  const conf = String(row.confidence_label || "").toLowerCase();
  if (conf === "low") { score += 40; reasons.push("Confiance faible"); }
  else if (conf === "med") { score += 20; reasons.push("Confiance moyenne"); }
  const flags = rowWarningFlags(row);
  if (flags.length) { score += flags.length * 15; reasons.push(`${flags.length} warning(s)`); }
  const src = String(row.proposed_source || "").toLowerCase();
  if (src === "name") { score += 15; reasons.push("Source = nom de fichier"); }
  const change = rowChangeType(row, decision);
  if (change === "fix_year") { score += 10; reasons.push("Correction d'annee"); }
  const level = score >= 50 ? "high" : score >= 25 ? "med" : "low";
  return { score, level, reasons };
}

function matchesPreset(row, decision, preset) {
  if (!preset || preset === "none") return true;
  if (preset === "review_risk") {
    const risk = computeReviewRisk(row, decision);
    return risk.level === "high" || risk.level === "med";
  }
  if (preset === "add_year") return rowChangeType(row, decision) === "add_year";
  if (preset === "sensitive") return rowWarningFlags(row).length > 0;
  if (preset === "collections") return String(row.kind || "").toLowerCase() === "collection";
  return true;
}

/* --- Filtering --------------------------------------------- */

function getFilteredRows() {
  const search = normalizeLooseText($("searchBox")?.value || "");
  const confFilter = $("filterConf")?.value || "all";
  const sourceFilter = $("filterSource")?.value || "all";
  const preset = state.validationPreset || "none";

  return state.rows.filter((row) => {
    if (search) {
      const haystack = normalizeLooseText(`${row.proposed_title || ""} ${row.folder || ""} ${row.title || ""}`);
      if (!haystack.includes(search)) return false;
    }
    if (confFilter !== "all") {
      if (String(row.confidence_label || "").toLowerCase() !== confFilter) return false;
    }
    if (sourceFilter !== "all") {
      if (String(row.proposed_source || "").toLowerCase() !== sourceFilter) return false;
    }
    const dec = currentDecision(row);
    if (!matchesPreset(row, dec, preset)) return false;
    return true;
  });
}

/* --- Table rendering --------------------------------------- */

function _renderValidationRowHtml(row) {
  const dec = currentDecision(row);
  const kind = String(row.kind || "").toLowerCase();
  const kindBadge = kind === "tv_episode" ? ' <span class="badge badge--accent">Serie</span>' : "";
  const flags = rowWarningFlags(row);
  const notMovieBadge = flags.includes("not_a_movie") ? ' <span class="badge badge--not-a-movie" title="Contenu suspect (bonus, trailer, sample...)">Non-film ?</span>' : "";
  const integrityBadge = flags.includes("integrity_header_invalid") ? ' <span class="badge badge--integrity" title="Header fichier invalide — fichier possiblement corrompu">Corrompu ?</span>' : "";
  const sagaName = String(row.tmdb_collection_name || "").trim();
  const sagaBadge = sagaName ? ` <span class="badge badge--saga" title="Collection TMDb : ${escapeHtml(sagaName)}">Saga</span>` : "";
  const editionLabel = String(row.edition || "").trim();
  const editionBadge = editionLabel ? ` <span class="badge badge--edition" title="Edition : ${escapeHtml(editionLabel)}">${escapeHtml(editionLabel)}</span>` : "";
  const encodeWarnings = Array.isArray(row.encode_warnings) ? row.encode_warnings : [];
  const upscaleBadge = encodeWarnings.includes("upscale_suspect") ? ' <span class="badge badge--upscale" title="Bitrate trop bas pour la resolution — probable upscale">Upscale ?</span>' : "";
  const lightBadge = encodeWarnings.includes("4k_light") ? ' <span class="badge badge--4k-light" title="4K compresse — qualité web/streaming">4K light</span>' : "";
  const reencodeBadge = encodeWarnings.includes("reencode_degraded") ? ' <span class="badge badge--reencode" title="Re-encode destructif — bitrate extremement bas">Re-encode</span>' : "";
  const aa = row.audio_analysis || {};
  const audioBadge = aa.badge_label ? ` <span class="badge badge--audio-${aa.badge_tier || "basique"}" title="${escapeHtml(aa.badge_label + (aa.has_commentary ? " + Commentaire" : ""))}">${escapeHtml(aa.badge_label)}</span>` : "";
  const audioLangBadge = (aa.missing_language_count > 0 || aa.incomplete_languages) ? ' <span class="badge badge--audio-lang" title="Piste(s) audio sans tag langue">Langue ?</span>' : "";
  const mkvTitleBadge = encodeWarnings.includes("mkv_title_mismatch") ? ` <span class="badge badge--mkv-title" title="Titre conteneur : ${escapeHtml(row.container_title || "")}">MKV titre</span>` : "";
  const nfoFileMismatchBadge = flags.includes("nfo_file_mismatch") ? ' <span class="badge badge--nfo-mismatch" title="Le NFO matche seulement le dossier ou le fichier, pas les deux — fichier vidéo possiblement remplacé">NFO partiel</span>' : "";
  const titleAmbigBadge = flags.includes("title_ambiguity_detected") ? ' <span class="badge badge--title-ambig" title="Deux films TMDb portent ce titre (remake/reboot). Vérifier l\'année attendue.">Titre ambigu</span>' : "";
  const nfoRuntimeDetail = row.nfo_runtime_mismatch_detail || null;
  const nfoRuntimeBadge = encodeWarnings.includes("nfo_runtime_mismatch")
    ? ` <span class="badge badge--nfo-mismatch" title="Durée fichier ${nfoRuntimeDetail ? nfoRuntimeDetail.probe_minutes + "min" : "?"} ≠ NFO ${nfoRuntimeDetail ? nfoRuntimeDetail.nfo_minutes + "min" : "?"} — NFO probablement obsolète ou mauvais fichier">Durée NFO ?</span>`
    : "";
  const rootLevelBadge = flags.includes("root_level_source") ? ' <span class="badge badge--root-level" title="Film posé directement à la racine — sera rangé dans un sous-dossier Titre (Année) au prochain apply">Depuis la racine</span>' : "";
  const confLabel = String(row.confidence_label || "low").toLowerCase();

  const subCount = Number(row.subtitle_count || 0);
  const _sl = row.subtitle_languages || "";
  const subLangs = Array.isArray(_sl) ? _sl : String(_sl).split("|").filter(Boolean);
  const _sm = row.subtitle_missing || "";
  const subMissing = Array.isArray(_sm) ? _sm : String(_sm).split("|").filter(Boolean);
  let subBadge = '<span class="text-muted">&mdash;</span>';
  if (subCount > 0 && subMissing.length === 0 && subLangs.length > 0) {
    subBadge = `<span class="badge badge--ok">${subCount} (${subLangs.join(",")})</span>`;
  } else if (subCount > 0) {
    subBadge = `<span class="badge badge--warn">${subCount} (${subLangs.join(",") || "?"})</span>`;
  } else if (subMissing.length > 0) {
    subBadge = `<span class="badge badge--danger">0</span>`;
  }

  const scrapeBadges = (typeof scrapingStatusHtml === "function")
    ? scrapingStatusHtml(row, state.settings || {})
    : "";

  const rowIdAttr = escapeHtml(String(row.row_id || ""));
  const cls = state.selectedRowId === row.row_id ? ' class="selected"' : "";
  const titleForA11y = escapeHtml(dec.title || row.proposed_title || `film ${row.row_id}`);
  const cells = [
    `<td class="cell-narrow"><input type="checkbox" data-ok="${rowIdAttr}" ${dec.ok ? "checked" : ""} aria-label="Approuver ${titleForA11y}" /></td>`,
    `<td>${escapeHtml(dec.title || row.proposed_title || "")}${scrapeBadges}${kindBadge}${notMovieBadge}${integrityBadge}${sagaBadge}${editionBadge}${upscaleBadge}${lightBadge}${reencodeBadge}${audioBadge}${audioLangBadge}${mkvTitleBadge}${nfoFileMismatchBadge}${nfoRuntimeBadge}${titleAmbigBadge}${rootLevelBadge}</td>`,
    `<td><input type="number" class="input" style="width:70px;height:28px" data-year="${rowIdAttr}" value="${dec.year || row.proposed_year || ""}" aria-label="Année pour ${titleForA11y}" /></td>`,
    `<td class="cell-truncate" title="${escapeHtml(row.folder || "")}">${escapeHtml(shortPath(row.folder || "", 40))}</td>`,
    `<td class="cell-rename">${typeof renamePreviewHtml === "function" ? renamePreviewHtml(row, dec, state.settings || {}) : ""}</td>`,
    `<td>${sourceLabel(row.proposed_source)}</td>`,
    `<td>${badgeForConfidence(confLabel)}</td>`,
    `<td class="cell-narrow">${subBadge}</td>`,
    `<td class="cell-muted">${escapeHtml(rowChangeType(row, dec))}</td>`,
  ];
  return `<tr${cls} data-row-id="${rowIdAttr}">${cells.join("")}</tr>`;
}

function renderTable() {
  const filtered = getFilteredRows();
  const tbody = $("planTbody");
  if (!tbody) return;

  if (!filtered.length) {
    // V2-07 : si aucun film n'est charge, on propose un CTA "Lancer un scan".
    // Sinon (filtres trop restrictifs), on garde le message focus filtres.
    if (!state.rows.length) {
      tbody.innerHTML = `<tr class="tbl-empty"><td colspan="9">${buildEmptyState({
        icon: "film",
        title: "Aucun film à valider",
        message: "Lancez un scan pour analyser votre bibliothèque puis revenez ici pour valider les renommages.",
        ctaLabel: "Lancer un scan",
        testId: "validation-empty-cta",
      })}</td></tr>`;
      bindEmptyStateCta(tbody, () => {
        if (typeof navigateTo === "function") navigateTo("home");
      });
    } else {
      tbody.innerHTML = buildTableEmptyRow(9, "Aucun film a afficher.", "Modifiez les filtres ou chargez la table.");
    }
    updateValidationPills(filtered);
    scheduleTableLayoutRefresh();
    return;
  }

  if (window.VirtualTable) {
    window.VirtualTable.virtualizeTbody(tbody, filtered, _renderValidationRowHtml, {
      threshold: 500,
      colspan: "9",
    });
  } else {
    tbody.innerHTML = filtered.map(_renderValidationRowHtml).join("");
  }

  updateValidationPills(filtered);
  scheduleTableLayoutRefresh();
}

function updateValidationPills(filtered) {
  const rows = filtered || getFilteredRows();
  const checked = rows.filter(r => currentDecision(r).ok).length;
  const reviewCount = rows.filter(r => {
    const dec = currentDecision(r);
    const risk = computeReviewRisk(r, dec);
    return risk.level !== "low";
  }).length;
  setPill("valPillTotal", `${state.rows.length} films`);
  setPill("valPillChecked", `${checked} valides`);
  setPill("valPillReview", `${reviewCount} a revoir`);
}

/* --- Selection & Inspector --------------------------------- */

function selectValidationRow(row) {
  if (!row) return;
  setSelectedFilmContext(row, state.rowsRunId);
  /* Visual selection */
  qsa("#planTbody tr").forEach(tr => tr.classList.toggle("selected", tr.dataset.rowId === row.row_id));
  renderInspector(row);
}

function renderInspector(row) {
  if (!row) {
    if ($("inspectorTitle")) $("inspectorTitle").textContent = "Selectionnez un film";
    if ($("inspectorBody")) $("inspectorBody").textContent = "Les details apparaitront ici.";
    if ($("inspectorActions")) $("inspectorActions").innerHTML = "";
    return;
  }
  const dec = currentDecision(row);
  const risk = computeReviewRisk(row, dec);
  if ($("inspectorTitle")) $("inspectorTitle").textContent = `${dec.title || row.proposed_title || "?"} (${dec.year || row.proposed_year || "?"})`;

  const lines = [
    `Source : ${sourceLabel(row.proposed_source)}`,
    `Confiance : ${row.confidence_label || "?"} (${row.confidence_score || "?"})`,
    `Type : ${rowChangeType(row, dec)}`,
    `Risque : ${risk.level} (${risk.score})`,
  ];
  if (risk.reasons.length) lines.push("", "Raisons :", ...risk.reasons.map(r => `  - ${r}`));

  /* Sous-titres */
  const stCount = Number(row.subtitle_count || 0);
  const stLangs = (row.subtitle_languages || "").split("|").filter(Boolean);
  const stMissing = (row.subtitle_missing || "").split("|").filter(Boolean);
  const stOrphans = Number(row.subtitle_orphans || 0);
  lines.push("", `Sous-titres : ${stCount} fichier(s)` + (stLangs.length ? ` (${stLangs.join(", ")})` : ""));
  if (stMissing.length) lines.push(`  Manquant(s) : ${stMissing.join(", ")}`);
  if (stOrphans > 0) lines.push(`  Orphelin(s) : ${stOrphans}`);

  const flags = rowWarningFlags(row);
  if (flags.length) lines.push("", "Warnings :", ...flags.map(f => `  - ${f}`));
  if (row.notes) lines.push("", "Notes : " + row.notes);

  if ($("inspectorBody")) $("inspectorBody").textContent = lines.join("\n");
  if ($("inspectorActions")) {
    $("inspectorActions").innerHTML = `<button class="btn btn--compact" id="btnShowCandidates">Voir les suggestions</button> <button class="btn btn--compact" id="btnShowHistory">Historique</button> <button class="btn btn--compact" id="btnPerceptual">Analyse perceptuelle</button> <button class="btn btn--compact" id="btnExplainScore">Détail du score</button>`;
    $("btnShowCandidates")?.addEventListener("click", () => showCandidates(row.row_id));
    $("btnShowHistory")?.addEventListener("click", () => _showFilmHistory(row));
    $("btnPerceptual")?.addEventListener("click", () => _runPerceptualAnalysis(row));
    $("btnExplainScore")?.addEventListener("click", () => _showScoreExplanation(row));
  }
}

/* --- P2.1 : Détail du score (explain-score) ---------------- */

function _tierColor(tier) {
  const t = String(tier || "").toLowerCase();
  if (t === "platinum") return "#A78BFA";
  if (t === "gold") return "#FBBF24";
  if (t === "silver") return "#9CA3AF";
  if (t === "bronze") return "#FB923C";
  return "#EF4444"; // Reject
}

function _fmtDelta(weighted) {
  const v = Number(weighted || 0);
  if (v === 0) return "0";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}`;
}

function _deltaColor(weighted) {
  const v = Number(weighted || 0);
  if (v > 0.5) return "#34D399";  // vert franc
  if (v > 0) return "#A7F3D0";    // vert clair
  if (v < -0.5) return "#EF4444"; // rouge franc
  if (v < 0) return "#FCA5A5";    // rouge clair
  return "var(--text-muted)";
}

function _buildCategoryBars(categories) {
  const cats = ["video", "audio", "extras"];
  return cats.map(cat => {
    const c = categories?.[cat] || {};
    const label = c.label || cat;
    const sub = c.subscore || 0;
    const weight = c.weight_pct || 0;
    const contrib = c.contribution || 0;
    const posCount = c.positive_count || 0;
    const negCount = c.negative_count || 0;
    const pct = Math.max(0, Math.min(100, sub));
    const fillColor = sub >= 85 ? "#A78BFA" : sub >= 68 ? "#FBBF24" : sub >= 54 ? "#9CA3AF" : sub >= 30 ? "#FB923C" : "#EF4444";
    return `<div class="mb-2">
      <div class="flex items-center justify-between font-sm">
        <strong>${escapeHtml(label)}</strong>
        <span class="text-muted font-xs">${weight}% du score — contrib. ${contrib.toFixed(1)}/100</span>
      </div>
      <div style="height:10px; background:var(--bg-raised); border-radius:5px; overflow:hidden; margin:.3em 0">
        <div style="width:${pct}%; height:100%; background:${fillColor}"></div>
      </div>
      <div class="font-xs text-muted">${sub}/100 · ${posCount} atout(s), ${negCount} pénalité(s)</div>
    </div>`;
  }).join("");
}

function _buildFactorsList(factors) {
  if (!Array.isArray(factors) || !factors.length) {
    return '<div class="text-muted font-sm">Aucun facteur enregistré.</div>';
  }
  // Trier par weighted_delta absolu décroissant pour voir l'impact en premier
  const sorted = [...factors].sort((a, b) => Math.abs(Number(b.weighted_delta || 0)) - Math.abs(Number(a.weighted_delta || 0)));
  const rows = sorted.slice(0, 25).map(f => {
    const wd = Number(f.weighted_delta || 0);
    const color = _deltaColor(wd);
    const catLabel = { video: "Vidéo", audio: "Audio", extras: "Extras", custom: "Règle", probe: "Sonde", perceptual: "Perceptuel" }[f.category] || f.category;
    return `<tr>
      <td class="font-xs text-muted">${escapeHtml(catLabel)}</td>
      <td>${escapeHtml(f.label || "")}</td>
      <td class="mono font-xs" style="text-align:right; color:${color}; font-weight:600">${_fmtDelta(wd)}</td>
    </tr>`;
  }).join("");
  const more = sorted.length > 25 ? `<tr><td colspan="3" class="font-xs text-muted" style="text-align:center">... et ${sorted.length - 25} autre(s) facteur(s)</td></tr>` : "";
  return `<table class="shortcuts-table" style="width:100%">
    <thead><tr><th class="font-xs">Catégorie</th><th class="font-xs">Règle</th><th class="font-xs" style="text-align:right">Impact</th></tr></thead>
    <tbody>${rows}${more}</tbody>
  </table>`;
}

function _buildSuggestionsList(suggestions) {
  if (!Array.isArray(suggestions) || !suggestions.length) return "";
  const items = suggestions.map(s => `<li class="font-sm">${escapeHtml(s)}</li>`).join("");
  return `<div class="mt-3 p-2" style="background:rgba(245,158,11,.1); border-left:3px solid #F59E0B; border-radius:4px">
    <div class="font-sm" style="color:#F59E0B; font-weight:600; margin-bottom:.3em">Pour améliorer le score :</div>
    <ul style="margin:0; padding-left:1.2em">${items}</ul>
  </div>`;
}

async function _showScoreExplanation(row) {
  if (!row || !row.row_id) return;
  const modal = $("modalScoreExplain");
  const body = $("scoreExplainBody");
  const title = $("modalScoreExplainTitle");
  if (!modal || !body) return;
  body.innerHTML = '<div class="text-secondary">Chargement du score...</div>';
  if (title) title.textContent = `Détail du score — ${row.proposed_title || "?"}`;
  openModal("modalScoreExplain");

  const r = await apiCall("get_quality_report", () => window.pywebview.api.get_quality_report(state.runId, row.row_id), {
    fallbackMessage: "Impossible de charger le rapport qualité.",
  });
  if (!r?.ok) {
    body.innerHTML = `<div class="alert alert--danger">${escapeHtml(r?.message || "Erreur de chargement.")}</div>`;
    return;
  }

  const score = Number(r.score || 0);
  const tier = String(r.tier || "?");
  const expl = r.explanation || (r.metrics?.score_explanation) || {};
  const narrative = expl.narrative || "Pas de narrative disponible.";
  const categories = expl.categories || {};
  const factors = expl.factors || [];
  const suggestions = expl.suggestions || [];
  const baseline = expl.baseline || {};
  // P4.2 : genre TMDb détecté (stocké dans metrics.primary_genre)
  const primaryGenre = r.metrics?.primary_genre || "";
  const genreBadge = primaryGenre
    ? ` <span class="badge badge--accent" style="font-size:var(--fs-xs); text-transform:capitalize">Genre : ${escapeHtml(primaryGenre)}</span>`
    : "";

  const tierColor = _tierColor(tier);
  const header = `<div class="card mb-3" style="padding:.75em; border-left:4px solid ${tierColor}">
    <div class="flex items-center gap-3">
      <div style="font-size:2em; font-weight:700; color:${tierColor}">${score}</div>
      <div>
        <div style="display:flex; align-items:center; gap:.4em">${typeof tierPill === "function" ? tierPill(tier) : `<strong>${escapeHtml(tier)}</strong>`} <span class="text-muted font-sm">/100</span>${genreBadge}</div>
        ${baseline.next_tier && baseline.distance_to_next_tier != null ? `<div class="font-xs text-muted">À ${baseline.distance_to_next_tier} point(s) du tier ${escapeHtml(baseline.next_tier)}</div>` : ""}
      </div>
    </div>
    <p class="font-sm" style="margin-top:.5em; font-style:italic; color:var(--text-secondary)">${escapeHtml(narrative)}</p>
  </div>`;

  const catsSection = `<div class="card mb-3" style="padding:.75em">
    <div class="card__eyebrow">Contribution par catégorie</div>
    ${_buildCategoryBars(categories)}
  </div>`;

  const factorsSection = `<div class="card mb-3" style="padding:.75em">
    <div class="card__eyebrow">Détail des règles appliquées (impact pondéré sur 100)</div>
    ${_buildFactorsList(factors)}
  </div>`;

  body.innerHTML = header + catsSection + factorsSection + _buildSuggestionsList(suggestions) + _buildFeedbackForm(row);
  _hookFeedbackForm(row);
}

/* --- P4.1 : feedback form pour calibration ----------------- */

function _buildFeedbackForm(row) {
  const tierOptions = ["Platinum", "Gold", "Silver", "Bronze", "Reject"];
  const opts = tierOptions.map(t => `<option value="${t}">${t}</option>`).join("");
  return `<div class="card mt-3" style="padding:.75em">
    <div class="card__eyebrow">Ce score vous semble-t-il juste ?</div>
    <div class="font-xs text-muted" style="margin-bottom:.5em">
      Votre feedback est stocké localement et sert à calibrer le scoring global (P4.1). Aucune donnée n'est envoyée à l'extérieur.
    </div>
    <div class="flex gap-2 mb-2" style="flex-wrap:wrap; align-items:center">
      <label class="font-sm" style="min-width:120px">Tier attendu :</label>
      <select id="fbUserTier" class="input" style="height:28px">${opts}</select>
      <label class="font-sm" style="min-width:120px">Catégorie (optionnel) :</label>
      <select id="fbCategoryFocus" class="input" style="height:28px">
        <option value="">Aucune</option>
        <option value="video">Vidéo sous/sur-évaluée</option>
        <option value="audio">Audio sous/sur-évalué</option>
        <option value="extras">Extras sous/sur-évalués</option>
      </select>
    </div>
    <input id="fbComment" class="input" placeholder="Commentaire libre (optionnel)" style="width:100%; margin-bottom:.4em" />
    <button class="btn btn--compact" id="fbSubmit">Enregistrer ce feedback</button>
    <div id="fbResult" class="font-sm mt-1" aria-live="polite"></div>
  </div>`;
}

function _hookFeedbackForm(row) {
  const btn = $("fbSubmit");
  const result = $("fbResult");
  if (!btn || !row) return;
  btn.addEventListener("click", async () => {
    const userTier = $("fbUserTier")?.value;
    const categoryFocus = $("fbCategoryFocus")?.value || null;
    const comment = $("fbComment")?.value || null;
    if (!userTier) return;
    btn.disabled = true;
    if (result) result.textContent = "Enregistrement...";
    try {
      const r = await apiCall("submit_score_feedback", () => window.pywebview.api.submit_score_feedback(state.runId, row.row_id, userTier, categoryFocus, comment));
      if (r?.ok) {
        const deltaLabel = r.tier_delta === 0 ? "Accord" : (r.tier_delta > 0 ? `Score sous-évalué (+${r.tier_delta})` : `Score sur-évalué (${r.tier_delta})`);
        if (result) result.innerHTML = `<span style="color:#34D399">✓ Feedback enregistré.</span> <span class="text-muted">(${escapeHtml(deltaLabel)})</span>`;
      } else {
        if (result) result.innerHTML = `<span style="color:#EF4444">${escapeHtml(r?.message || "Erreur")}</span>`;
        btn.disabled = false;
      }
    } catch (e) {
      if (result) result.textContent = "Erreur : " + String(e.message || e);
      btn.disabled = false;
    }
  });
}

/* --- Perceptual analysis ---------------------------------- */

async function _runPerceptualAnalysis(row) {
  const body = $("inspectorBody");
  if (!body) return;
  body.textContent = "Analyse perceptuelle en cours...";
  try {
    const r = await apiCall("get_perceptual_report", () => window.pywebview.api.get_perceptual_report(currentContextRunId(), row.row_id));
    if (!r?.ok) { body.textContent = "Erreur : " + (r?.message || "echec"); return; }
    const p = r.perceptual || {};
    const vp = p.video_perceptual || {};
    const ga = p.grain_analysis || {};
    const ap = p.audio_perceptual || {};
    const cv = p.cross_verdicts || [];
    let html = `<div class="perceptual-scores">`;
    html += `<span class="badge badge--perceptual-${esc(p.global_tier || "degrade")}">${esc(p.global_score ?? "?")}/100 ${esc(p.global_tier || "")}</span>`;
    html += ` <span class="text-muted">Video ${p.visual_score ?? "?"} | Audio ${p.audio_score ?? "?"}</span>`;
    html += `</div>`;

    // §16b v7.5.0 — Score composite V2 (cercle + jauges + accordeon + warnings)
    const gsv2 = p.global_score_v2 || r.perceptual?.global_score_v2;
    if (gsv2 && typeof window.renderScoreV2Container === "function") {
      html += `<div class="mt-2"><div class="font-sm text-muted" style="margin-bottom:.3em">Score CineSort V2</div>`;
      html += window.renderScoreV2Container(gsv2);
      html += `</div>`;
    }

    if (cv.length) {
      html += `<div class="cross-verdicts mt-1">`;
      cv.forEach(v => { html += `<div class="cross-verdict cross-verdict--${escapeHtml(v.severity || "info")}">${escapeHtml(v.label || "")}</div>`; });
      html += `</div>`;
    }
    if (ga.verdict_label) html += `<div class="mt-1 text-muted">Grain : ${escapeHtml(ga.verdict_label)}</div>`;
    html += `<details class="perceptual-details mt-1"><summary>Details</summary><pre style="font-size:var(--fs-xs)">${escapeHtml(JSON.stringify(vp, null, 2))}</pre></details>`;
    body.innerHTML = html;
    if (gsv2 && typeof window.bindScoreV2Events === "function") {
      window.bindScoreV2Events(body);
    }
  } catch (e) { body.textContent = "Erreur : " + e.message; }
}

/* --- Film history timeline ---------------------------------- */

function _filmId(row) {
  // Reproduit film_identity_key cote JS
  const ed = String(row.edition || "").trim().toLowerCase();
  const edSuffix = ed ? "|" + ed : "";
  const cands = Array.isArray(row.candidates) ? row.candidates : [];
  for (const c of cands) {
    if (c.tmdb_id && Number(c.tmdb_id) > 0) return "tmdb:" + c.tmdb_id + edSuffix;
  }
  const title = String(row.proposed_title || "").trim().toLowerCase();
  const year = Number(row.proposed_year || 0);
  return "title:" + title + "|" + year + edSuffix;
}

async function _showFilmHistory(row) {
  const fid = _filmId(row);
  const modal = $("modalFilmHistory");
  const body = $("filmHistoryBody");
  const title = $("modalFilmHistoryTitle");
  if (!modal || !body) return;
  body.innerHTML = '<div class="text-secondary">Chargement de l\'historique...</div>';
  if (title) title.textContent = `Historique — ${row.proposed_title || "?"}`;
  openModal("modalFilmHistory");

  try {
    const r = await apiCall("get_film_history", () => window.pywebview.api.get_film_history(fid));
    if (!r || !r.ok) {
      body.innerHTML = '<div class="text-muted">Aucun historique disponible pour ce film.</div>';
      return;
    }
    const events = r.events || [];
    if (!events.length) {
      body.innerHTML = '<div class="text-muted">Aucun événement enregistré pour ce film.</div>';
      return;
    }
    body.innerHTML = _renderFilmHistoryFull(events, r);
  } catch (e) {
    body.innerHTML = `<div class="alert alert--danger">Erreur : ${escapeHtml(String(e.message || e))}</div>`;
  }
}

function _shortenHistoryPath(p, max = 50) {
  const s = String(p || "");
  if (s.length <= max) return s;
  return s.slice(0, Math.floor(max * 0.4)) + " … " + s.slice(-Math.floor(max * 0.5));
}

function _renderScoreSparkline(events) {
  // Extrait les événements "score" et dessine un line chart SVG minimaliste
  const scorePoints = events.filter(e => e.type === "score" && Number.isFinite(Number(e.score)));
  if (scorePoints.length < 2) return "";

  const w = 780, h = 110, padL = 30, padR = 10, padT = 12, padB = 24;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const scores = scorePoints.map(p => Number(p.score));
  const minS = Math.max(0, Math.min(...scores) - 5);
  const maxS = Math.min(100, Math.max(...scores) + 5);
  const rangeS = Math.max(1, maxS - minS);
  const ts = scorePoints.map(p => Number(p.ts || 0));
  const minT = Math.min(...ts);
  const maxT = Math.max(...ts);
  const rangeT = Math.max(1, maxT - minT);

  const coords = scorePoints.map((p, i) => {
    const x = padL + (scorePoints.length === 1 ? innerW / 2 : (innerW * (Number(p.ts || 0) - minT) / rangeT));
    const y = padT + innerH - (innerH * (Number(p.score) - minS) / rangeS);
    return { x, y, p };
  });

  const polyPath = "M " + coords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" L ");
  const areaPath = polyPath + ` L ${coords[coords.length - 1].x},${padT + innerH} L ${coords[0].x},${padT + innerH} Z`;

  // Threshold lines (Platinum 85, Gold 68, Silver 54, Bronze 30)
  const thresholdLines = [
    { y: padT + innerH - (innerH * (85 - minS) / rangeS), color: "#A78BFA", label: "Pt" },
    { y: padT + innerH - (innerH * (68 - minS) / rangeS), color: "#FBBF24", label: "Go" },
    { y: padT + innerH - (innerH * (54 - minS) / rangeS), color: "#9CA3AF", label: "Si" },
  ].filter(l => l.y >= padT && l.y <= padT + innerH);

  const thresholdsHtml = thresholdLines.map(l =>
    `<line x1="${padL}" y1="${l.y}" x2="${padL + innerW}" y2="${l.y}" stroke="${l.color}" stroke-dasharray="2,3" stroke-width="0.5" opacity="0.4"/>
     <text x="${padL - 4}" y="${l.y + 3}" text-anchor="end" font-size="9" fill="${l.color}" opacity="0.7">${l.label}</text>`
  ).join("");

  const pointsHtml = coords.map(c => {
    const tier = String(c.p.tier || "").toLowerCase();
    const color = tier === "platinum" ? "#A78BFA" : tier === "gold" ? "#FBBF24" : tier === "silver" ? "#9CA3AF" : tier === "bronze" ? "#FB923C" : "#EF4444";
    return `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="3.5" fill="${color}" stroke="var(--bg-raised)" stroke-width="1.5"><title>Score ${c.p.score} (${c.p.tier || "?"})</title></circle>`;
  }).join("");

  const firstScore = scorePoints[0].score;
  const lastScore = scorePoints[scorePoints.length - 1].score;
  const totalDelta = lastScore - firstScore;
  const deltaLabel = totalDelta > 0 ? `+${totalDelta}` : String(totalDelta);
  const deltaColor = totalDelta > 0 ? "#34D399" : totalDelta < 0 ? "#EF4444" : "var(--text-muted)";

  return `<div class="card mb-3" style="padding:.75em">
    <div class="flex items-center justify-between mb-2">
      <div class="card__eyebrow">Évolution du score (${scorePoints.length} mesures)</div>
      <div class="font-sm" style="color:${deltaColor}; font-weight:600">Total ${deltaLabel}</div>
    </div>
    <svg viewBox="0 0 ${w} ${h}" style="width:100%; height:auto; display:block" preserveAspectRatio="xMidYMid meet">
      ${thresholdsHtml}
      <path d="${areaPath}" fill="url(#scoreGradFilm)" opacity="0.2"/>
      <path d="${polyPath}" fill="none" stroke="#60A5FA" stroke-width="2"/>
      ${pointsHtml}
      <defs><linearGradient id="scoreGradFilm" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#60A5FA" stop-opacity="0.6"/><stop offset="100%" stop-color="#60A5FA" stop-opacity="0"/></linearGradient></defs>
    </svg>
  </div>`;
}

function _renderFilmHistoryHeader(data) {
  const currentScore = data.current_score;
  const scanCount = data.scan_count || 0;
  const applyCount = data.apply_count || 0;
  const events = data.events || [];
  const scoreEvents = events.filter(e => e.type === "score");
  const firstScore = scoreEvents.length > 0 ? Number(scoreEvents[0].score) : null;
  const lastEvent = events[events.length - 1];
  const lastTier = scoreEvents.length > 0 ? String(scoreEvents[scoreEvents.length - 1].tier || "") : "";
  const daysSinceLast = lastEvent ? Math.floor((Date.now() / 1000 - Number(lastEvent.ts || 0)) / 86400) : null;

  const tierPillHtml = (currentScore != null && lastTier && typeof tierPill === "function")
    ? tierPill(lastTier, { compact: false })
    : "";
  const trendDelta = (firstScore != null && currentScore != null) ? (currentScore - firstScore) : 0;
  const trendHtml = trendDelta !== 0
    ? `<span class="font-xs" style="color:${trendDelta > 0 ? "#34D399" : "#EF4444"}; font-weight:600">${trendDelta > 0 ? "↑ +" : "↓ "}${trendDelta}</span>`
    : '<span class="font-xs text-muted">→ stable</span>';

  return `<div class="card mb-3" style="padding:.9em">
    <div style="display:flex; gap:20px; align-items:center; flex-wrap:wrap">
      <div>
        <div class="card__eyebrow">Film</div>
        <div style="font-size:1.1em; font-weight:700">${escapeHtml(data.title || "?")}${data.year ? ` <span class="text-muted">(${data.year})</span>` : ""}</div>
      </div>
      ${currentScore != null ? `
      <div>
        <div class="card__eyebrow">Score actuel</div>
        <div style="display:flex; align-items:center; gap:.5em">
          <span style="font-size:1.4em; font-weight:700">${currentScore}</span>
          ${tierPillHtml}
          ${trendHtml}
        </div>
      </div>` : ""}
      <div>
        <div class="card__eyebrow">Activité</div>
        <div class="font-sm"><strong>${scanCount}</strong> scan(s) · <strong>${applyCount}</strong> apply</div>
        ${daysSinceLast != null ? `<div class="font-xs text-muted">Dernier événement il y a ${daysSinceLast} jour(s)</div>` : ""}
      </div>
    </div>
  </div>`;
}

function _renderTimelineEvents(events) {
  const items = events.map((e, idx) => {
    const date = _fmtEventDate(e.ts);
    const isLast = idx === events.length - 1;
    const connector = isLast ? "" : '<div style="position:absolute; left:14px; top:28px; bottom:-16px; width:2px; background:var(--border)"></div>';

    let iconColor = "var(--text-muted)";
    let icon = "•";
    let bodyHtml = "";

    if (e.type === "scan") {
      iconColor = "#60A5FA";
      icon = "🔍";
      bodyHtml = `<div><strong>Scan</strong> — confiance <strong>${e.confidence}</strong>, source ${escapeHtml(e.source || "?")}</div>${(e.warnings || []).length ? `<div class="font-xs text-muted">${(e.warnings || []).map(w => escapeHtml(w)).join(", ")}</div>` : ""}`;
    } else if (e.type === "score") {
      iconColor = "#FBBF24";
      icon = "⭐";
      const deltaText = e.delta === 0 ? "" : (e.delta > 0 ? ` <span style="color:#34D399">+${e.delta}</span>` : ` <span style="color:#EF4444">${e.delta}</span>`);
      const tierHtml = typeof tierPill === "function" ? tierPill(e.tier || "", { compact: true }) : escapeHtml(String(e.tier || ""));
      bodyHtml = `<div><strong>Score ${e.score}</strong>${deltaText} &nbsp; ${tierHtml}</div>`;
    } else if (e.type === "apply") {
      iconColor = "#34D399";
      icon = "📁";
      const ops = (e.operations || []).map(op => `<div class="mono font-xs text-muted" title="${escapeHtml(op.from || "")} → ${escapeHtml(op.to || "")}">${escapeHtml(_shortenHistoryPath(op.from || ""))}<br>&nbsp;→ ${escapeHtml(_shortenHistoryPath(op.to || ""))}</div>`).join("");
      bodyHtml = `<div><strong>Apply</strong> (${(e.operations || []).length} op)</div><div class="mt-1">${ops}</div>`;
    } else {
      bodyHtml = `<div>${escapeHtml(e.type || "?")}</div>`;
    }

    return `<div style="position:relative; padding-left:36px; padding-bottom:16px; min-height:30px">
      <div style="position:absolute; left:6px; top:4px; width:20px; height:20px; border-radius:50%; background:var(--bg-raised); border:2px solid ${iconColor}; display:flex; align-items:center; justify-content:center; font-size:.7em; z-index:2">${icon}</div>
      ${connector}
      <div class="font-xs text-muted" style="margin-bottom:2px">${escapeHtml(date)}</div>
      <div class="font-sm">${bodyHtml}</div>
    </div>`;
  }).join("");
  return `<div class="card" style="padding:.9em"><div class="card__eyebrow mb-2">Chronologie détaillée</div>${items}</div>`;
}

function _renderFilmHistoryFull(events, data) {
  return _renderFilmHistoryHeader(data) + _renderScoreSparkline(events) + _renderTimelineEvents(events);
}

// Legacy export pour rétrocompat (si d'autres callers)
function _renderTimeline(events, data) {
  return _renderFilmHistoryFull(events, data);
}

function _fmtEventDate(ts) {
  // V6-04 : datetime locale-aware via core/format.js (window.formatDateTime).
  if (!ts) return "—";
  try {
    if (typeof window.formatDateTime === "function") return window.formatDateTime(ts);
    return new Date(ts * 1000).toLocaleString();
  } catch { return "—"; }
}

/* --- Candidates -------------------------------------------- */

async function showCandidates(rowId) {
  const row = findRowById(rowId);
  if (!row) return;
  state.candidatesForRow = row;
  const candidates = row.candidates || [];
  const list = $("candList");
  if (!list) return;

  if (!candidates.length) {
    list.innerHTML = buildEmptyStateHtml("Aucune suggestion disponible.", "Seul le resultat principal est propose.");
    openModal("modalCandidates");
    return;
  }

  list.innerHTML = candidates.map((c, i) => {
    const title = String(c.title || "?");
    const year = Number(c.year || 0);
    const src = sourceLabel(c.source);
    const note = String(c.note || "");
    return `<div class="flex items-center gap-3 mb-3" style="padding:var(--sp-2);border:1px solid var(--border);border-radius:var(--radius-sm)">
      <div class="flex-1">
        <div class="fw-medium">${escapeHtml(title)}${year ? ` (${year})` : ""}</div>
        <div class="font-xs text-muted">${escapeHtml(src)} ${note ? "— " + escapeHtml(note) : ""}</div>
      </div>
      <button class="btn btn--compact btn--primary" data-pick-cand="${i}">Choisir</button>
    </div>`;
  }).join("");

  list.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-pick-cand]");
    if (!btn) return;
    const idx = parseInt(btn.dataset.pickCand, 10);
    const cand = candidates[idx];
    if (!cand || !state.candidatesForRow) return;
    const dec = currentDecision(state.candidatesForRow);
    dec.title = String(cand.title || "").trim();
    dec.year = Number(cand.year || 0);
    dec.edited = true;
    closeModal("modalCandidates");
    renderTable();
    _scheduleDraftSave();
  }, { once: true });

  openModal("modalCandidates");
}

/* Keyboard shortcuts migrated to core/keyboard.js */

/* --- Load table -------------------------------------------- */

async function loadTable() {
  if (!state.runId && !currentContextRunId()) {
    setStatusMessage("valMsg", "Aucun run actif.", { error: true });
    return;
  }
  const rid = state.runId || currentContextRunId();
  state.runId = rid;

  setStatusMessage("valMsg", "Chargement...", { loading: true });
  const r = await apiCall("get_plan", () => window.pywebview.api.get_plan(rid), {
    statusId: "valMsg", fallbackMessage: "Impossible de charger la table.",
  });
  if (!r?.ok || !Array.isArray(r.rows)) {
    setStatusMessage("valMsg", r?.message || "Erreur de chargement.", { error: true });
    return;
  }

  setRows(r.rows, rid);

  /* Load prior decisions */
  const v = await apiCall("load_validation", () => window.pywebview.api.load_validation(rid));
  if (v && typeof v === "object" && v.ok !== false) {
    const saved = v.decisions || v;
    for (const [id, d] of Object.entries(saved)) {
      if (d && typeof d === "object") {
        state.decisions[id] = { ok: !!d.ok, title: d.title || "", year: d.year || 0, edited: !!d.edited };
      }
    }
  }

  /* Initialize decisions for rows without saved decisions */
  for (const row of state.rows) {
    currentDecision(row);
  }

  renderTable();
  setStatusMessage("valMsg", `${state.rows.length} films charges.`, { success: true, clearMs: 2000 });

  // V2-03 : proposer restauration si un draft non sauvegarde existe pour ce run.
  _checkAndOfferRestore();
}

async function ensureValidationLoaded() {
  if (state.rows.length && state.rowsRunId === (state.runId || currentContextRunId())) return;
  await loadTable();
}

async function saveValidationFromUI() {
  console.log("[validation] save");
  const r = await persistValidation();
  if (r?.ok) {
    _clearDraft();  // V2-03 : draft localStorage plus necessaire apres confirmation serveur.
    setStatusMessage("valMsg", "Decisions enregistrees.", { success: true, clearMs: 2000 });
    flashActionButton("btnSaveValidation", "ok");
  } else {
    setStatusMessage("valMsg", r?.message || "Erreur d'enregistrement.", { error: true });
    flashActionButton("btnSaveValidation", "error");
  }
}

/* --- Events ------------------------------------------------ */

/* --- Focus mode (K16) -------------------------------------- */

function toggleFocusMode() {
  const on = !document.body.classList.contains("focus-mode");
  document.body.classList.toggle("focus-mode", on);
  const btn = $("btnFocusMode");
  if (btn) btn.setAttribute("aria-pressed", on ? "true" : "false");
  let badge = document.getElementById("focusBadge");
  if (on) {
    if (!badge) {
      badge = document.createElement("button");
      badge.id = "focusBadge";
      badge.className = "focus-badge";
      badge.textContent = "Focus actif (Esc pour quitter)";
      badge.addEventListener("click", toggleFocusMode);
      document.body.appendChild(badge);
    }
    if (typeof toast === "function") toast({ type: "info", text: "Mode Focus actif — Esc pour quitter", duration: 2400 });
  } else if (badge) {
    badge.remove();
  }
}

function hookValidationEvents() {
  /* Filters */
  $("searchBox")?.addEventListener("input", renderTable);
  $("filterConf")?.addEventListener("change", renderTable);
  $("filterSource")?.addEventListener("change", renderTable);

  /* Presets */
  $("valPresets")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-preset]");
    if (!btn) return;
    state.validationPreset = btn.dataset.preset;
    qsa("#valPresets .preset-btn").forEach(b => b.classList.toggle("active", b.dataset.preset === state.validationPreset));
    renderTable();
  });

  /* Bulk check/uncheck — itere sur les rows filtres (pas seulement les rows
   * actuellement dans le DOM, qui peuvent etre une fenetre virtualisee). */
  $("btnCheckVisible")?.addEventListener("click", () => {
    for (const row of getFilteredRows()) currentDecision(row).ok = true;
    renderTable();
    _scheduleDraftSave();
  });
  $("btnUncheckVisible")?.addEventListener("click", () => {
    for (const row of getFilteredRows()) currentDecision(row).ok = false;
    renderTable();
    _scheduleDraftSave();
  });

  /* Save */
  $("btnSaveValidation")?.addEventListener("click", saveValidationFromUI);
  $("btnFocusMode")?.addEventListener("click", toggleFocusMode);

  /* M5 : Event delegation click pour selection de ligne (evite un listener par tr) */
  $("planTbody")?.addEventListener("click", (e) => {
    if (e.target.closest("input")) return;
    const tr = e.target.closest("tr[data-row-id]");
    if (!tr) return;
    const row = findRowById(tr.dataset.rowId);
    if (row) selectValidationRow(row);
  });

  /* Delegated checkbox + year changes */
  $("planTbody")?.addEventListener("change", (e) => {
    const ck = e.target.closest("[data-ok]");
    if (ck) {
      const row = findRowById(ck.dataset.ok);
      if (row) currentDecision(row).ok = ck.checked;
      updateValidationPills();
      _scheduleDraftSave();
      return;
    }
    const yr = e.target.closest("[data-year]");
    if (yr) {
      const row = findRowById(yr.dataset.year);
      if (row) {
        const dec = currentDecision(row);
        dec.year = parseInt(yr.value, 10) || 0;
        dec.edited = true;
      }
      _scheduleDraftSave();
    }
  });

  /* Keyboard shortcuts now in core/keyboard.js */
}
