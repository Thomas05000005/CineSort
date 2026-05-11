/* global state, $, qsa, currentDecision, escapeHtml, badgeForConfidence, sourceLabel, openModal, findRowById, setSelectedFilmById, currentContextRunId, currentContextRowId, openRunFilmSelector, setRows, apiCall, setStatusMessage, flashActionButton, clearStatusMessageLater */

function normalizeLooseText(txt){
  return String(txt || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, " ")
    .trim()
    .toLowerCase();
}

function extractYearFromText(txt){
  const m = /\b(19\d{2}|20\d{2})\b/.exec(String(txt || ""));
  if(!m) return 0;
  const n = parseInt(m[1], 10);
  return Number.isFinite(n) ? n : 0;
}

function rowWarningFlags(row){
  if(Array.isArray(row?.warning_flags) && row.warning_flags.length){
    return row.warning_flags.map((x) => String(x || "").trim()).filter(Boolean);
  }
  const notes = String(row?.notes || "").toLowerCase();
  const flags = [];
  if(notes.includes("nfo ignore: titre incoherent")) flags.push("nfo_title_mismatch");
  if(notes.includes("nfo ignore: annee incoherente")) flags.push("nfo_year_mismatch");
  if(notes.includes("conflit dossier/fichier")) flags.push("year_conflict_folder_file");
  if(notes.includes("dy=") && notes.includes("tmdb")) flags.push("tmdb_year_delta");
  return flags;
}

function rowChangeType(row, decision){
  if(!row) return "none";
  if(String(row.kind || "").toLowerCase() === "collection"){
    return "collection";
  }
  const folderName = String(row.folder || "").split(/[\\/]/).filter(Boolean).pop() || "";
  const targetTitle = String(decision?.title || row.proposed_title || "").trim();
  const targetYear = Number(decision?.year || row.proposed_year || 0);
  if(!targetTitle || !targetYear){
    return "none";
  }
  const expectedName = `${targetTitle} (${targetYear})`;
  if(folderName.toLowerCase() === expectedName.toLowerCase()){
    return "already_ok";
  }
  const folderYear = extractYearFromText(folderName);
  if(folderYear && targetYear && folderYear !== targetYear){
    return "fix_year";
  }
  const hasYear = /\(\s*(19\d{2}|20\d{2})\s*\)/.test(folderName);
  const folderNoYear = normalizeLooseText(folderName.replace(/\(\s*(19\d{2}|20\d{2})\s*\)/g, " "));
  const targetNorm = normalizeLooseText(targetTitle);
  if((!hasYear) && folderNoYear && targetNorm && folderNoYear === targetNorm){
    return "add_year";
  }
  if(folderNoYear && targetNorm && folderNoYear !== targetNorm){
    return "normalize_title";
  }
  return "none";
}

function qualityInfoForRow(rowId){
  const key = String(rowId || "").trim();
  if(!key) return { status: "not_analyzed", tier: "", score: null };
  const rec = state.qualityByRow.get(key);
  if(!rec || typeof rec !== "object"){
    return { status: "not_analyzed", tier: "", score: null };
  }
  return {
    status: String(rec.status || "analyzed"),
    tier: String(rec.tier || "").toLowerCase(),
    score: Number.isFinite(Number(rec.score)) ? Number(rec.score) : null,
  };
}

function matchesQualityFilters(row){
  const stateFilter = $("qualityStateFilter")?.value || "all";
  const tierFilter = ($("qualityTierFilter")?.value || "all").toLowerCase();
  const scoreFilter = $("qualityScoreFilter")?.value || "all";
  const info = qualityInfoForRow(row?.row_id);

  if(stateFilter !== "all" && info.status !== stateFilter){
    return false;
  }
  if(tierFilter !== "all" && info.tier !== tierFilter){
    return false;
  }
  if(scoreFilter !== "all"){
    const score = Number.isFinite(info.score) ? Number(info.score) : null;
    if(score === null) return false;
    if(scoreFilter === "lt45" && !(score < 45)) return false;
    if(scoreFilter === "45_59" && !(score >= 45 && score <= 59)) return false;
    if(scoreFilter === "gte60" && !(score >= 60)) return false;
  }
  return true;
}

function computeReviewRisk(row, decision){
  let score = 0;
  const reasons = [];

  const conf = String(row?.confidence_label || "").toLowerCase();
  if(conf === "low"){
    score += 35;
    reasons.push("confiance faible");
  } else if(conf === "med"){
    score += 20;
    reasons.push("confiance moyenne");
  }

  const source = String(row?.proposed_source || "").toLowerCase();
  if(source === "name"){
    score += 12;
    reasons.push("source nom");
  } else if(source === "tmdb"){
    score += 8;
    reasons.push("source TMDb");
  }

  const flags = rowWarningFlags(row);
  for(const flag of flags){
    if(flag === "nfo_title_mismatch"){
      score += 22;
      reasons.push("NFO titre mismatch");
    } else if(flag === "nfo_year_mismatch"){
      score += 18;
      reasons.push("NFO année mismatch");
    } else if(flag === "year_conflict_folder_file"){
      score += 16;
      reasons.push("conflit année dossier/fichier");
    } else if(flag === "tmdb_year_delta"){
      score += 10;
      reasons.push("TMDb delta année");
    } else {
      score += 6;
      reasons.push("warning heuristique");
    }
  }

  const changeType = rowChangeType(row, decision);
  if(changeType === "fix_year"){
    score += 16;
    reasons.push("correction année");
  } else if(changeType === "normalize_title"){
    score += 12;
    reasons.push("normalisation titre");
  } else if(changeType === "collection"){
    score += 8;
    reasons.push("ligne collection");
  } else if(changeType === "add_year"){
    score += 6;
    reasons.push("ajout année");
  }

  const q = qualityInfoForRow(row?.row_id);
  if(q.status === "error"){
    score += 25;
    reasons.push("erreur qualité");
  } else if(q.status === "not_analyzed"){
    score += 10;
    reasons.push("qualité non analysée");
  } else if(q.status === "ignored_existing"){
    score += 6;
    reasons.push("qualité réutilisée");
  }
  const qScore = Number.isFinite(q.score) ? Number(q.score) : null;
  if(qScore !== null){
    if(qScore < 45){
      score += 18;
      reasons.push("score qualité bas");
    } else if(qScore <= 59){
      score += 10;
      reasons.push("score qualité moyen-bas");
    } else if(qScore <= 69){
      score += 4;
      reasons.push("score qualité moyen");
    }
  }

  if(q.tier === "faible"){
    score += 8;
    reasons.push("tier faible");
  } else if(q.tier === "moyen"){
    score += 3;
    reasons.push("tier moyen");
  }

  score = Math.max(0, Math.min(100, score));
  const level = score >= 65 ? "high" : (score >= 40 ? "med" : "low");
  return { score, level, reasons };
}

function reviewRiskLevelLabel(level){
  if(level === "high") return "élevé";
  if(level === "med") return "moyen";
  return "léger";
}

function matchesValidationPreset(row, decision){
  const preset = String(state.validationPreset || "none");
  if(preset === "none"){
    return true;
  }
  const conf = String(row?.confidence_label || "");
  const source = String(row?.proposed_source || "");
  const flags = rowWarningFlags(row);
  const changeType = rowChangeType(row, decision);
  const q = qualityInfoForRow(row?.row_id);

  if(preset === "review_risk"){
    return computeReviewRisk(row, decision).score >= 40;
  }
  if(preset === "add_year"){
    return changeType === "add_year";
  }
  if(preset === "sensitive"){
    return changeType === "fix_year" || changeType === "normalize_title" || flags.length > 0;
  }
  if(preset === "collections"){
    return String(row?.kind || "") === "collection";
  }
  if(preset === "quality_low"){
    const score = Number.isFinite(q.score) ? Number(q.score) : null;
    return score !== null && score < 60;
  }
  return true;
}

function syncValidationPresetButtons(){
  const presetToButton = {
    review_risk: "btnPresetReviewRisk",
    add_year: "btnPresetAddYear",
    sensitive: "btnPresetSensitive",
    collections: "btnPresetCollections",
    quality_low: "btnPresetQualityLow",
  };
  const activePreset = String(state.validationPreset || "none");
  Object.entries(presetToButton).forEach(([preset, id]) => {
    const btn = $(id);
    if(!btn) return;
    btn.classList.toggle("active", activePreset === preset);
  });
  $("btnPresetReset")?.classList.toggle("active", activePreset === "none");
}

function getFilteredRows(){
  const q = ($("searchBox")?.value || "").toLowerCase().trim();
  const conf = $("filterConf")?.value || "all";
  const source = $("filterSource")?.value || "all";
  const kind = $("filterKind")?.value || "all";
  const changeType = $("filterChangeType")?.value || "all";
  const warning = $("filterWarning")?.value || "all";
  const filtered = state.rows.filter(r => {
    const d = currentDecision(r);
    if(conf === "high" || conf === "med" || conf === "low"){
      if(r.confidence_label !== conf) return false;
    } else if(conf === "med_low"){
      if(!(r.confidence_label === "med" || r.confidence_label === "low")) return false;
    }
    if(source !== "all"){
      const s = String(r.proposed_source || "");
      if(source === "tmdb_name"){
        if(!(s === "tmdb" || s === "name")) return false;
      } else if(s !== source){
        return false;
      }
    }
    if(kind !== "all" && String(r.kind || "") !== kind) return false;
    if(changeType !== "all" && rowChangeType(r, d) !== changeType) return false;
    if(warning !== "all"){
      const flags = rowWarningFlags(r);
      if(warning === "any_warning"){
        if(!flags.length) return false;
      } else if(!flags.includes(warning)){
        return false;
      }
    }
    if(!matchesValidationPreset(r, d)) return false;
    if(!matchesQualityFilters(r)) return false;
    if(!q) return true;
    const hay = `${r.proposed_title} ${r.proposed_year} ${r.folder} ${r.video}`.toLowerCase();
    return hay.includes(q);
  });

  if(String(state.validationPreset || "none") === "review_risk"){
    const confRank = { high: 1, med: 2, low: 3 };
    filtered.sort((a, b) => {
      const da = currentDecision(a);
      const db = currentDecision(b);
      const ra = computeReviewRisk(a, da);
      const rb = computeReviewRisk(b, db);
      if(rb.score !== ra.score) return rb.score - ra.score;

      const qa = qualityInfoForRow(a?.row_id);
      const qb = qualityInfoForRow(b?.row_id);
      const sa = Number.isFinite(qa.score) ? Number(qa.score) : 999;
      const sb = Number.isFinite(qb.score) ? Number(qb.score) : 999;
      if(sa !== sb) return sa - sb;

      const ca = confRank[String(a?.confidence_label || "")] || 0;
      const cb = confRank[String(b?.confidence_label || "")] || 0;
      if(cb !== ca) return cb - ca;

      return String(a?.row_id || "").localeCompare(String(b?.row_id || ""));
    });
  }

  return filtered;
}

function setValidationPreset(preset){
  state.validationPreset = String(preset || "none");
  renderTable();
  if(state.validationPreset === "review_risk"){
    const rows = getFilteredRows();
    let high = 0;
    for(const row of rows){
      const d = currentDecision(row);
      if(computeReviewRisk(row, d).level === "high"){
        high += 1;
      }
    }
    setStatusMessage(
      "validationMsg",
      `File à relire intelligente: ${rows.length} ligne(s), dont ${high} à risque élevé.`,
      { success: true },
    );
    clearStatusMessageLater("validationMsg", 3200);
  }
}

function renderTable(){
  const tbody = $("planTbody");
  tbody.innerHTML = "";
  syncValidationPresetButtons();
  const rows = getFilteredRows();

  $("countPill").textContent = `${rows.length} lignes affichées / ${state.rows.length}`;

  if(rows.length === 0){
    const hasPlanRows = state.rows.length > 0;
    const activeRunId = String(state.runId || "").trim();
    const rowsRunId = String(state.rowsRunId || "").trim();
    const msg = hasPlanRows
      ? "Aucune ligne ne correspond au filtre actuel."
      : (activeRunId && activeRunId !== rowsRunId)
        ? "Aucune table chargée pour ce run. Chargez la table de validation."
        : "Aucune ligne disponible. Lancez une analyse puis chargez la table.";
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="10" class="tableEmpty">${escapeHtml(msg)}</td>`;
    tbody.appendChild(tr);
    return;
  }

  for(const row of rows){
    const d = currentDecision(row);
    const reviewRisk = state.validationPreset === "review_risk" ? computeReviewRisk(row, d) : null;
    const kind = row.kind === "collection"
      ? `<span class="typePill">Collection</span>`
      : `<span class="typePill">Single</span>`;

    const years = Array.from(new Set((row.candidates || []).map(c => c.year).filter(Boolean))).sort((a, b) => b - a);
    let yearSelect = "";
    if(years.length >= 2){
      yearSelect = `<select class="select" data-year-select="${row.row_id}">
        ${years.map(y => `<option value="${y}" ${y === d.year ? "selected" : ""}>${y}</option>`).join("")}
      </select>`;
    } else {
      yearSelect = `<span class="muted">—</span>`;
    }

    const editedCls = d.edited ? "edited" : "";
    const selectedCls = (String(state.selectedRowId || "") === String(row.row_id || "")) ? "selectedRow" : "";
    const rowTitle = String(d.title || row.proposed_title || row.video || row.folder || row.row_id || "").trim();
    const checkboxAria = `Valider la ligne: ${rowTitle || "film"}`;
    const detectedYear = Number(row.detected_year || 0);
    const retainedYear = Number(d.year || row.proposed_year || 0);
    let analysisText = String(row.notes || "");
    if(detectedYear > 0 && retainedYear > 0 && detectedYear !== retainedYear){
      analysisText = `Année détectée: ${detectedYear} · année retenue: ${retainedYear}. ${analysisText}`;
    }
    const riskBadgeHtml = reviewRisk
      ? `<div class="mt6"><span class="badge ${reviewRisk.level === "high" ? "low" : (reviewRisk.level === "med" ? "med" : "neutral")}">Risque ${reviewRiskLevelLabel(reviewRisk.level)} ${reviewRisk.score}/100</span></div>`
      : "";
    const riskDetails = reviewRisk
      ? `Risque ${reviewRisk.score}/100 (${reviewRiskLevelLabel(reviewRisk.level)}): ${(reviewRisk.reasons || []).slice(0, 4).join(" | ")}. `
      : "";
    const analysisTooltip = `${riskDetails}${analysisText}`.trim();

    const tr = document.createElement("tr");
    tr.dataset.rowId = String(row.row_id || "");
    tr.className = selectedCls;
    tr.innerHTML = `
      <td><input type="checkbox" data-ok="${row.row_id}" ${d.ok ? "checked" : ""} aria-label="${escapeHtml(checkboxAria)}"></td>
      <td>${badgeForConfidence(row.confidence_label)} <div class="muted">${row.confidence}/100</div>${riskBadgeHtml}</td>
      <td>${kind}</td>
      <td class="muted oneLine" title="${escapeHtml(row.folder)}">${escapeHtml(row.folder)}</td>
      <td class="muted oneLine" title="${escapeHtml(row.video || "")}">${escapeHtml(row.video || "")}</td>
      <td>
        <input class="smallInput ${editedCls}" data-title="${row.row_id}" value="${escapeHtml(d.title)}" />
      </td>
      <td>
        <input class="smallInput ${editedCls}" data-year="${row.row_id}" type="number" min="1900" max="2100" value="${d.year || ""}" />
        <div class="mt6">${yearSelect}</div>
      </td>
      <td class="muted" title="${escapeHtml(sourceLabel(row.proposed_source || ""))}">${escapeHtml(sourceLabel(row.proposed_source || ""))}</td>
      <td class="muted" title="${escapeHtml(analysisTooltip)}">${escapeHtml(row.notes || "")}</td>
      <td>
        <div class="actions">
          <button class="btn smallBtn" data-cand="${row.row_id}">Propositions</button>
          <button class="btn smallBtn" data-open="${escapeHtml(row.folder)}">Ouvrir</button>
        </div>
      </td>
    `;
    const analysisCell = tr.querySelector("td:nth-child(9)");
    if(analysisCell){
      analysisCell.setAttribute("title", analysisTooltip);
      analysisCell.textContent = analysisText;
      analysisCell.classList.add("muted");
    }
    tbody.appendChild(tr);
  }
}

async function hydrateTmdbPosters(row){
  const missingIds = [];
  for(const c of (row.candidates || [])){
    if(c.source === "tmdb" && c.tmdb_id && !c.poster_url){
      missingIds.push(Number(c.tmdb_id));
    }
  }
  if(!missingIds.length) return;

  try {
    const r = await apiCall("get_tmdb_posters", () => window.pywebview.api.get_tmdb_posters(missingIds, "w92"));
    if(!r || !r.ok || !r.posters) return;
    const posters = r.posters;
    for(const c of (row.candidates || [])){
      if(c.source !== "tmdb" || !c.tmdb_id || c.poster_url) continue;
      const p = posters[String(c.tmdb_id)];
      if(p) c.poster_url = p;
    }
  } catch(_err){
    // ignore poster refresh failure
  }
}

function renderCandidatesList(rowId){
  const row = findRowById(rowId);
  if(!row) return;

  const list = $("candList");
  list.innerHTML = "";
  const cands = (row.candidates || []).slice().sort((a, b) => (b.score || 0) - (a.score || 0));

  if(!cands.length){
    list.innerHTML = `<div class="muted">Aucune proposition.</div>`;
    return;
  }

  for(const c of cands){
    const label = c.source === "tmdb" ? "TMDb" : c.source === "nfo" ? "NFO" : "Nom";
    const year = c.year ? `(${c.year})` : "";
    const note = c.note ? ` • ${escapeHtml(c.note)}` : "";
    const tmdb = c.tmdb_id ? ` • id=${c.tmdb_id}` : "";
    const poster = (c.source === "tmdb" && c.poster_url)
      ? `<div class="candPosterWrap">
          <img class="candPoster" src="${escapeHtml(c.poster_url)}" loading="lazy" alt="Poster TMDb" onerror="this.parentElement.classList.add('missing')" />
          <div class="candPoster placeholder">${label}</div>
        </div>`
      : `<div class="candPoster placeholder">${label}</div>`;

    const el = document.createElement("div");
    el.className = "candItem";
    el.innerHTML = `
      <div class="candMain">
        ${poster}
        <div>
          <div class="candTitle">${escapeHtml(c.title)} ${escapeHtml(year)}</div>
          <div class="candMeta">${label}${tmdb}${note}</div>
        </div>
      </div>
      <button class="btn primary smallBtn" data-pick="${rowId}" data-ptitle="${escapeHtml(c.title)}" data-pyear="${c.year || ""}">Choisir</button>
    `;
    list.appendChild(el);
  }
}

async function showCandidates(rowId){
  const row = findRowById(rowId);
  if(!row) return;

  state.candidatesForRow = row;
  $("candHeader").textContent = `${row.kind.toUpperCase()} — ${row.video || ""} — dossier: ${row.folder}`;
  await hydrateTmdbPosters(row);
  renderCandidatesList(rowId);
  openModal("modalCandidates");
}

function enhanceNextValidationLayout(){
  const view = $("view-validate");
  if(!view || view.dataset.nextEnhanced === "1"){
    return;
  }
  view.dataset.nextEnhanced = "1";
  view.classList.add("validationNextView");
  view.querySelector(".validationStageCard")?.classList.add("nextStageCard");
  view.querySelector(".validationFiltersCard")?.classList.add("nextWorkbenchCard", "nextFilterZone");
  view.querySelector(".validationActionsCard")?.classList.add("nextWorkbenchCard", "nextActionZone");
  view.querySelector(".validationTableCard")?.classList.add("nextWorkbenchCard", "nextDataZone");
  view.querySelector(".validationStageHelp")?.classList.add("nextSupportZone");
}

