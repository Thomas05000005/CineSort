/* views/quality.js — Qualite / scoring / distribution + global stats */

/* === Panel: Run courant ================================== */

function renderQualityKpis(dash) {
  if (!dash) return;
  const kpis = dash.kpis || {};
  if ($("qKpiScore")) $("qKpiScore").textContent = kpis.score_avg ? `${Number(kpis.score_avg).toFixed(1)}/100` : "—";
  if ($("qKpiPremium")) $("qKpiPremium").textContent = kpis.premium_pct ? `${Number(kpis.premium_pct).toFixed(1)}%` : "—";
  if ($("qKpiFilms")) $("qKpiFilms").textContent = String(kpis.scored_count || kpis.total_rows || 0);
  if ($("qKpiPartial")) $("qKpiPartial").textContent = String(kpis.probe_partial_count || 0);
}

function renderQualityDistribution(dash) {
  if (!dash) return;
  const bins = dash.score_bins || dash.kpis?.score_bins || {};
  const total = Math.max(1, Number(dash.kpis?.total_rows || 1));
  const premium = Number(bins.premium || bins["85-100"] || 0);
  const good = Number(bins.good || bins["68-84"] || 0);
  const medium = Number(bins.medium || bins["54-67"] || 0);
  const bad = Number(bins.bad || bins["0-53"] || 0);
  const pct = (n) => `${Math.round((n / total) * 100)}%`;
  if ($("distPremium")) $("distPremium").style.width = pct(premium);
  if ($("distPremiumN")) $("distPremiumN").textContent = String(premium);
  if ($("distGood")) $("distGood").style.width = pct(good);
  if ($("distGoodN")) $("distGoodN").textContent = String(good);
  if ($("distMedium")) $("distMedium").style.width = pct(medium);
  if ($("distMediumN")) $("distMediumN").textContent = String(medium);
  if ($("distBad")) $("distBad").style.width = pct(bad);
  if ($("distBadN")) $("distBadN").textContent = String(bad);
}

function renderStatGrid(targetId, data) {
  const el = $(targetId);
  if (!el || !data || typeof data !== "object") { if (el) el.innerHTML = ""; return; }
  el.innerHTML = Object.entries(data)
    .map(([k, v]) => `<div class="stat-item"><span class="stat-item__label">${escapeHtml(k)}</span><span class="stat-item__value">${escapeHtml(String(v))}</span></div>`)
    .join("");
}

function renderQualityAnomalies(anomalies) {
  renderGenericTable("qualityAnomaliesTbody", {
    rows: Array.isArray(anomalies) ? anomalies : [],
    columns: [
      { render: (r) => severityBadge(r.severity || r.level) },
      { render: (r) => `<span class="cell-mono">${escapeHtml(r.code || "")}</span>` },
      { render: (r) => escapeHtml(r.message || "") },
      { render: (r) => `<span class="cell-truncate" title="${escapeHtml(r.path || "")}">${escapeHtml(shortPath(r.path || "", 60))}</span>` },
    ],
    emptyTitle: "Aucune anomalie.",
    emptyHint: "Toutes les analyses sont conformes.",
  });
}

function renderQualityView(dash) {
  if (!dash) return;

  /* Message si aucun film score */
  const scored = Number(dash.kpis?.scored_count || dash.kpis?.total_rows || 0);
  const emptyEl = $("qualityEmptyMsg");
  if (scored === 0) {
    // BUG 1 : la structure est { tools: { ffprobe, mediainfo } }
    const _t = state.probeToolsStatus?.tools || {};
    const probeOk = _t.ffprobe?.available || _t.mediainfo?.available;
    const msg = probeOk
      ? "Aucun film scoré. Lancez un scan pour analyser votre bibliothèque."
      : "Aucun film analysé. Les outils d'analyse vidéo (FFprobe, MediaInfo) ne sont pas installés. Installez-les depuis la page Accueil puis relancez un scan.";
    const ctaLabel = probeOk ? "Lancer un scan" : "Aller à l'Accueil";
    if (emptyEl) {
      // V2-07 : factory + bind helper (remplace l'ancienne markup inline V1-05).
      emptyEl.innerHTML = buildEmptyState({
        icon: probeOk ? "search" : "alert",
        title: probeOk ? "Aucun film scoré" : "Aucun film analysé",
        message: msg,
        ctaLabel,
        testId: "quality-empty-cta",
      });
      emptyEl.classList.remove("hidden");
      bindEmptyStateCta(emptyEl, () => {
        if (typeof navigateTo === "function") navigateTo("home");
        // Laisser le temps a la vue Accueil de se monter avant scroll/focus.
        setTimeout(() => {
          const target = $("btnStartPlan");
          if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "center" });
            try { target.focus({ preventScroll: true }); } catch (_e) { /* ignore */ }
          }
        }, 80);
      });
    }
    return;
  }
  if (emptyEl) emptyEl.classList.add("hidden");

  renderQualityKpis(dash);
  renderQualityDistribution(dash);
  renderStatGrid("qualityResolutions", dash.resolutions || dash.kpis?.resolutions);
  renderStatGrid("qualityHdr", dash.hdr || dash.kpis?.hdr);
  renderStatGrid("qualityAudio", dash.audio || dash.kpis?.audio);
  renderQualityAnomalies(dash.anomalies || []);
}

async function refreshQualityView(opts = {}) {
  const rid = currentContextRunId();
  const requested = rid || "latest";
  if (!opts.silent) setStatusMessage("qualityMsg", "Chargement...", { loading: true });
  const r = await apiCall("get_dashboard(quality)", () => window.pywebview.api.get_dashboard(requested), {
    statusId: "qualityMsg", fallbackMessage: "Impossible de charger les données qualité.",
  });
  if (!r || r.ok === false) return;
  state.dashboard = r;
  if (r.run_id && r.run_dir) setLastRunContext(r.run_id, r.run_dir);
  renderQualityView(r);
  if (!opts.silent) setStatusMessage("qualityMsg", "", {});
}

/* === Panel: Bibliotheque (global stats) ================== */

/** Build an inline SVG bar chart for timeline data. */
function buildTimelineSvg(timeline) {
  const points = Array.isArray(timeline) ? timeline : [];
  if (!points.length) return '<div class="empty-state"><div class="empty-state__title">Aucune donnée.</div></div>';

  const W = 560;
  const H = 140;
  const PAD_L = 32;
  const PAD_R = 8;
  const PAD_T = 12;
  const PAD_B = 24;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;
  const n = points.length;
  const barW = Math.max(4, Math.min(28, Math.floor(chartW / n) - 2));
  const gap = Math.max(1, Math.floor((chartW - n * barW) / Math.max(1, n - 1)));
  const maxScore = 100;

  function tierColor(score) {
    if (score >= 85) return "var(--success)";
    if (score >= 68) return "var(--accent)";
    if (score >= 54) return "var(--warning)";
    return "var(--danger)";
  }

  let bars = "";
  for (let i = 0; i < n; i++) {
    const p = points[i];
    const score = Number(p.score_avg || 0);
    const barH = Math.max(2, (score / maxScore) * chartH);
    const x = PAD_L + i * (barW + gap);
    const y = PAD_T + chartH - barH;
    bars += `<rect x="${x}" y="${y}" width="${barW}" height="${barH}" rx="2" fill="${tierColor(score)}" opacity="0.85">`;
    bars += `<title>Run ${i + 1}: ${score.toFixed(1)}/100</title></rect>`;
  }

  /* Y axis labels */
  let yLabels = "";
  for (const val of [0, 50, 100]) {
    const y = PAD_T + chartH - (val / maxScore) * chartH;
    yLabels += `<text x="${PAD_L - 4}" y="${y + 3}" text-anchor="end" fill="var(--text-muted)" font-size="9">${val}</text>`;
    yLabels += `<line x1="${PAD_L}" y1="${y}" x2="${W - PAD_R}" y2="${y}" stroke="var(--border)" stroke-dasharray="2,3"/>`;
  }

  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" xmlns="http://www.w3.org/2000/svg" style="display:block">
    ${yLabels}${bars}
  </svg>`;
}

function renderGlobalDistBars(tiers, totalScored) {
  const el = $("globalDistBars");
  if (!el) return;
  const t = tiers || {};
  const total = Math.max(1, Number(totalScored || 1));
  // U1 audit : 5 tiers modernes + fallback sur les anciens noms pour les
  // snapshots anterieurs a la migration 011.
  const platinum = Number(t["Platinum"] ?? t["Premium"] ?? 0);
  const gold = Number(t["Gold"] ?? t["Bon"] ?? 0);
  const silver = Number(t["Silver"] ?? t["Moyen"] ?? 0);
  const bronze = Number(t["Bronze"] ?? 0);
  const reject = Number(t["Reject"] ?? t["Mauvais"] ?? t["Faible"] ?? 0);
  const pct = (n) => `${Math.round((n / total) * 100)}%`;
  // P3.2 : utilise tierPill pour une pastille cohérente
  el.innerHTML = [
    `<div class="dist-row"><span class="dist-label">${typeof tierPill === "function" ? tierPill("platinum", {compact: true}) : "Platinum"}</span><div class="dist-bar-track"><div class="dist-bar-fill dist-bar-fill--premium" style="width:${pct(platinum)}"></div></div><span class="dist-count">${platinum}</span></div>`,
    `<div class="dist-row"><span class="dist-label">${typeof tierPill === "function" ? tierPill("gold", {compact: true}) : "Gold"}</span><div class="dist-bar-track"><div class="dist-bar-fill dist-bar-fill--good" style="width:${pct(gold)}"></div></div><span class="dist-count">${gold}</span></div>`,
    `<div class="dist-row"><span class="dist-label">${typeof tierPill === "function" ? tierPill("silver", {compact: true}) : "Silver"}</span><div class="dist-bar-track"><div class="dist-bar-fill dist-bar-fill--medium" style="width:${pct(silver)}"></div></div><span class="dist-count">${silver}</span></div>`,
    `<div class="dist-row"><span class="dist-label">${typeof tierPill === "function" ? tierPill("bronze", {compact: true}) : "Bronze"}</span><div class="dist-bar-track"><div class="dist-bar-fill dist-bar-fill--medium" style="width:${pct(bronze)}"></div></div><span class="dist-count">${bronze}</span></div>`,
    `<div class="dist-row"><span class="dist-label">${typeof tierPill === "function" ? tierPill("reject", {compact: true}) : "Reject"}</span><div class="dist-bar-track"><div class="dist-bar-fill dist-bar-fill--bad" style="width:${pct(reject)}"></div></div><span class="dist-count">${reject}</span></div>`,
  ].join("");
}

function trendClass(trend) {
  if (trend === "↑") return "text-success";
  if (trend === "↓") return "text-danger";
  return "text-muted";
}

function renderGlobalStats(data) {
  if (!data) return;
  const s = data.summary || {};

  /* KPIs */
  if ($("gKpiRuns")) $("gKpiRuns").textContent = String(s.total_runs || 0);
  if ($("gKpiFilms")) $("gKpiFilms").textContent = String(s.total_films || 0);
  if ($("gKpiScore")) $("gKpiScore").textContent = s.avg_score ? `${s.avg_score}/100` : "—";
  if ($("gKpiPremium")) $("gKpiPremium").textContent = s.premium_pct ? `${s.premium_pct}%` : "—";
  if ($("gKpiTrend")) {
    $("gKpiTrend").textContent = s.trend || "→";
    $("gKpiTrend").className = `kpi__value ${trendClass(s.trend)}`;
  }
  if ($("gKpiUnscored")) $("gKpiUnscored").textContent = String(s.unscored_films || 0);

  /* Timeline SVG chart */
  if ($("globalTimelineChart")) {
    $("globalTimelineChart").innerHTML = buildTimelineSvg(data.timeline);
  }

  /* Distribution */
  renderGlobalDistBars(data.tier_distribution, data.total_scored);

  /* Top anomalies */
  renderGenericTable("globalAnomaliesTbody", {
    rows: Array.isArray(data.top_anomalies) ? data.top_anomalies : [],
    columns: [
      { render: (r) => `<span class="cell-mono">${escapeHtml(r.code || "")}</span>` },
      { render: (r) => `<span class="fw-semi">${escapeHtml(String(r.count || 0))}</span>` },
      { render: (r) => escapeHtml(r.last_run_id || "—") },
    ],
    emptyTitle: "Aucune anomalie recurrente.",
  });

  /* Activity table */
  renderGenericTable("globalActivityTbody", {
    rows: Array.isArray(data.activity) ? data.activity : [],
    columns: [
      { render: (r) => escapeHtml(r.run_id || "—") },
      { render: (r) => fmtDateTime(r.start_ts) },
      { render: (r) => String(r.total_rows || 0) },
      { render: (r) => r.score_avg ? `${r.score_avg}/100` : "—" },
      { render: (r) => {
        const st = String(r.status || "").toUpperCase();
        if (st === "DONE") return r.applied ? '<span class="badge badge--ok">Appliqué</span>' : '<span class="badge badge--neutral">Analysé</span>';
        if (st === "FAILED") return '<span class="badge badge--bad">Échec</span>';
        if (st === "CANCELLED") return '<span class="badge badge--warn">Annulé</span>';
        return `<span class="badge badge--neutral">${escapeHtml(st)}</span>`;
      }},
      { render: (r) => {
        const a = Number(r.anomalies || 0);
        const e = Number(r.errors || 0);
        if (!a && !e) return '<span class="text-muted">—</span>';
        const parts = [];
        if (e) parts.push(`${e} err.`);
        if (a) parts.push(`${a} anom.`);
        return `<span class="text-warning">${escapeHtml(parts.join(", "))}</span>`;
      }},
    ],
    emptyTitle: "Aucun run enregistré.",
  });

  /* Space analysis */
  const space = data.space_analysis || {};
  const spaceEl = $("globalSpaceSection");
  if (spaceEl && space.total_bytes > 0) {
    // V6-04 : delegue a window.formatBytes (locale-aware) si dispo, sinon fallback FR Mo/Go.
    const _fb = (b) => {
      if (typeof window.formatBytes === "function") return window.formatBytes(b, 2);
      const n = Number(b) || 0;
      if (n < 1024*1024*1024) return `${(n/(1024*1024)).toFixed(1)} Mo`;
      return `${(n/(1024*1024*1024)).toFixed(2)} Go`;
    };
    let sh = `<p><strong>Espace total :</strong> ${_fb(space.total_bytes)} &nbsp; <strong>Moyenne :</strong> ${_fb(space.avg_bytes)} &nbsp; <strong>Recuperable :</strong> <span class="text-warning">${_fb(space.archivable_bytes)} (${space.archivable_count || 0} films)</span></p>`;
    const bt = space.by_tier || {};
    const tt = space.total_bytes || 1;
    sh += '<div class="space-bars mt-2">';
    // U1 audit : 5 tiers + fallback sur anciens noms pour les rapports pre-migration 011.
    const _legacy = { Platinum: "Premium", Gold: "Bon", Silver: "Moyen", Bronze: null, Reject: "Mauvais" };
    for (const [tier, cls] of [
      ["Platinum", "badge--ok"],
      ["Gold", "badge--neutral"],
      ["Silver", "badge--neutral"],
      ["Bronze", "badge--warn"],
      ["Reject", "badge--bad"],
    ]) {
      const b = bt[tier] || bt[_legacy[tier]] || 0;
      const p = Math.round(b / tt * 100);
      sh += `<div class="space-bar-row"><span class="space-bar-label">${tier}</span><div class="space-bar-track"><div class="space-bar-fill" style="width:${p}%"></div></div><span class="space-bar-value">${_fb(b)} (${p}%)</span></div>`;
    }
    sh += '</div>';
    spaceEl.innerHTML = sh;
    spaceEl.classList.remove("hidden");
  } else if (spaceEl) {
    spaceEl.classList.add("hidden");
  }

  /* Librarian suggestions */
  const libEl = $("globalLibrarianSection");
  const lib = data.librarian || {};
  const suggestions = lib.suggestions || [];
  const hs = lib.health_score ?? 100;
  if (libEl && (suggestions.length > 0 || hs < 100)) {
    const hsColor = hs >= 80 ? "var(--accent-success, var(--success, #34D399))" : hs >= 50 ? "var(--warning)" : "var(--danger)";
    let lh = `<p>Sante : <strong style="color:${hsColor}">${hs}%</strong></p>`;
    if (suggestions.length > 0) {
      lh += '<div class="suggestions-list mt-2">';
      for (const sg of suggestions) {
        const c = sg.priority === "high" ? "var(--danger)" : sg.priority === "medium" ? "var(--warning)" : "var(--accent)";
        lh += `<div class="suggestion-card" style="border-left-color:${c}">${esc(sg.message)}</div>`;
      }
      lh += '</div>';
    } else {
      lh += '<p class="text-muted mt-1">Bibliothèque en excellent état.</p>';
    }
    libEl.innerHTML = lh;
    libEl.classList.remove("hidden");
  } else if (libEl) {
    libEl.classList.add("hidden");
  }

  /* Health trend chart */
  const htEl = $("globalHealthTrend");
  const ht = data.health_trend || {};
  const hPoints = (data.timeline || []).filter((p) => p.health_score != null);
  if (htEl && hPoints.length >= 2) {
    const tColor = ht.delta > 0 ? "var(--success)" : ht.delta < 0 ? "var(--danger)" : "var(--text-muted)";
    let ch = `<p style="color:${tColor};font-weight:600">${esc(ht.message || "")}</p>`;
    const W = 360, H = 80, P = 16, n = hPoints.length;
    const xs = hPoints.map((_, i) => P + (i / Math.max(1, n - 1)) * (W - 2 * P));
    const ys = hPoints.map((p) => P + (1 - (p.health_score || 0) / 100) * (H - 2 * P));
    const pts = xs.map((x, i) => `${x},${ys[i]}`).join(" ");
    ch += `<svg class="health-chart mt-2" viewBox="0 0 ${W} ${H}"><polygon points="${xs[0]},${H - P} ${pts} ${xs[n - 1]},${H - P}" fill="var(--accent-soft,.12)" opacity="0.5"/><polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/></svg>`;
    htEl.innerHTML = ch;
    htEl.classList.remove("hidden");
  } else if (htEl) {
    htEl.classList.add("hidden");
  }
}

async function refreshGlobalStats(opts = {}) {
  if (!opts.silent) setStatusMessage("qualityMsg", "Chargement des statistiques globales...", { loading: true });
  const r = await apiCall("get_global_stats", () => window.pywebview.api.get_global_stats(20), {
    statusId: "qualityMsg", fallbackMessage: "Impossible de charger les stats globales.",
  });
  if (!r || r.ok === false) return;
  state.globalStats = r;
  renderGlobalStats(r);
  if (!opts.silent) setStatusMessage("qualityMsg", "", {});
}

/* === Quality presets ====================================== */

async function loadQualityPresets() {
  if (state.qualityPresets.length) return;
  try {
    const r = await apiCall("get_quality_presets", () => window.pywebview.api.get_quality_presets?.());
    if (Array.isArray(r?.presets)) state.qualityPresets = r.presets;
  } catch (_e) { /* optional endpoint */ }
}

async function loadQualityProfile() {
  try {
    const r = await apiCall("get_quality_profile", () => window.pywebview.api.get_quality_profile?.());
    if (r && r.ok !== false) state.qualityProfile = r;
  } catch (_e) { /* optional endpoint */ }
}

async function loadProbeToolsStatus(silent) {
  if (state.probeToolsInFlight) return;
  state.probeToolsInFlight = true;
  try {
    const r = await apiCall("get_probe_tools_status", () => window.pywebview.api.get_probe_tools_status());
    if (r && r.ok !== false) state.probeToolsStatus = r;
  } finally {
    state.probeToolsInFlight = false;
  }
}

/* === Mode toggle + events ================================ */

let _qualityMode = "run";

function setQualityMode(mode) {
  _qualityMode = mode;
  const panelRun = $("qualityPanelRun");
  const panelGlobal = $("qualityPanelGlobal");
  if (panelRun) panelRun.classList.toggle("hidden", mode !== "run");
  if (panelGlobal) panelGlobal.classList.toggle("hidden", mode !== "global");

  qsa("#qualityModeToggle .preset-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.qmode === mode)
  );

  if (mode === "global") refreshGlobalStats({ silent: false });
  else refreshQualityView({ silent: false });
}

function hookQualityEvents() {
  /* Mode toggle */
  $("qualityModeToggle")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-qmode]");
    if (btn) setQualityMode(btn.dataset.qmode);
  });

  $("btnQualityRefresh")?.addEventListener("click", () => {
    if (_qualityMode === "global") refreshGlobalStats();
    else refreshQualityView();
  });

  $("btnQualityOpenDir")?.addEventListener("click", () => {
    const dir = resolveRunDirFor(currentContextRunId());
    if (dir) openPathWithFeedback(dir, "qualityMsg");
  });

  /* Bouton "Analyser la qualite". Decoupe le run courant en lots de QUALITY_BATCH_SIZE
     films, appelle analyze_quality_batch pour chaque lot, et affiche le progres
     X/Y entre les lots. Sans decoupage, l'appel bloque pywebview pendant plusieurs
     minutes sans aucun feedback et refreshQualityView final ne rafraichit rien
     pendant que l'analyse tourne. */
  const QUALITY_BATCH_SIZE = 20;
  $("btnQualityAnalyze")?.addEventListener("click", async () => {
    const rid = currentContextRunId();
    if (!rid) {
      setStatusMessage("qualityMsg", "Lancez d'abord un scan.", { error: true });
      return;
    }
    const btn = $("btnQualityAnalyze");
    if (btn) btn.disabled = true;
    let _stopped = false;
    setStatusMessage("qualityMsg", "Chargement du plan…", { loading: true });
    try {
      // 1) Charger le plan pour obtenir la liste des row_ids a analyser.
      const plan = await apiCall(
        "get_plan(quality)",
        () => window.pywebview.api.get_plan(rid),
        { statusId: "qualityMsg", fallbackMessage: "Impossible de charger le plan." }
      );
      if (!plan || plan.ok === false) return;
      const allRows = Array.isArray(plan.rows) ? plan.rows : [];
      const rowIds = allRows
        .map(r => String((r && r.row_id) || "").trim())
        .filter(Boolean);
      if (rowIds.length === 0) {
        setStatusMessage("qualityMsg", "Aucun film à analyser.", { error: true });
        return;
      }

      // 2) Boucle par lots. Chaque lot = 1 appel pywebview court (quelques secondes).
      const total = rowIds.length;
      let analyzed = 0;
      let ignored = 0;
      let errors = 0;
      const t0 = performance.now();

      for (let i = 0; i < total; i += QUALITY_BATCH_SIZE) {
        if (_stopped) break;
        const batch = rowIds.slice(i, i + QUALITY_BATCH_SIZE);
        const done = i;
        const pct = Math.floor((done / total) * 100);
        const elapsed = (performance.now() - t0) / 1000;
        const speed = done > 0 ? done / elapsed : 0;
        const eta = done > 0 ? Math.round((total - done) / speed) : 0;
        setStatusMessage(
          "qualityMsg",
          `Analyse qualité ${done}/${total} (${pct}%) — ETA ${eta}s`,
          { loading: true }
        );

        const r = await apiCall(
          "analyze_quality_batch",
          () => window.pywebview.api.analyze_quality_batch(rid, batch, {
            reuse_existing: true,
            continue_on_error: true,
          }),
          { statusId: "qualityMsg", fallbackMessage: "Lot en erreur, poursuite…" }
        );
        if (r && r.ok) {
          analyzed += Number(r.analyzed || 0);
          ignored += Number(r.ignored || 0);
          errors += Number(r.errors || 0);
        } else if (r && r.ok === false) {
          // Un echec de lot ne stoppe pas le scan — on comptabilise les erreurs
          // et on continue pour donner au moins un resultat partiel.
          errors += batch.length;
        }
      }

      // 3) Refresh final — utiliser le run_id explicite pour eviter les alias "latest".
      const totalDt = Math.round((performance.now() - t0) / 1000);
      setStatusMessage(
        "qualityMsg",
        `Analyse terminée : ${analyzed} analysés, ${ignored} ignorés, ${errors} erreurs (${totalDt}s). Chargement des résultats…`,
        { success: true }
      );
      // Recharge l'etat dashboard pour le run_id explicite, puis re-render.
      try {
        const dash = await apiCall(
          "get_dashboard(quality-refresh)",
          () => window.pywebview.api.get_dashboard(rid),
          { statusId: "qualityMsg", fallbackMessage: "Résultats non chargés." }
        );
        if (dash && dash.ok !== false) {
          state.dashboard = dash;
          if (dash.run_id && dash.run_dir) setLastRunContext(dash.run_id, dash.run_dir);
          renderQualityView(dash);
        }
      } catch (err) {
        console.error("[quality] final refresh", err);
      }
      setStatusMessage(
        "qualityMsg",
        `Terminé : ${analyzed} films analysés en ${totalDt}s.`,
        { success: true }
      );
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  /* Quality presets — C4 : applique reellement le preset via apply_quality_preset.
     Avant, le listener ne faisait que toggler la classe active sans rien envoyer
     au backend. Le profil de scoring reste inchange malgre le clic. */
  $("qualityPresetGroup")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-quality-preset]");
    if (!btn) return;
    const presetId = String(btn.dataset.qualityPreset || "").trim();
    if (!presetId) return;
    const prev = qsa("#qualityPresetGroup .preset-btn.active").map(b => b);
    qsa("#qualityPresetGroup .preset-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    setStatusMessage("qualityMsg", `Application du preset "${presetId}"…`, { loading: true });
    try {
      const r = await apiCall(
        "apply_quality_preset",
        () => window.pywebview.api.apply_quality_preset(presetId),
        { statusId: "qualityMsg", fallbackMessage: "Preset non applique." }
      );
      if (r && r.ok !== false) {
        setStatusMessage("qualityMsg", `Preset "${presetId}" applique.`, { success: true });
        await loadQualityProfile();
        await refreshQualityView({ silent: true });
      } else {
        // Restaurer l'etat actif precedent en cas d'echec
        qsa("#qualityPresetGroup .preset-btn").forEach(b => b.classList.remove("active"));
        prev.forEach(b => b.classList.add("active"));
      }
    } catch (err) {
      console.error("[quality] apply_quality_preset", err);
      qsa("#qualityPresetGroup .preset-btn").forEach(b => b.classList.remove("active"));
      prev.forEach(b => b.classList.add("active"));
    }
  });

  /* Export/Import/Reset profil qualite (parite dashboard) */
  $("btnQualityExportProfile")?.addEventListener("click", async () => {
    try {
      const r = await apiCall("export_quality_profile", () => window.pywebview.api.export_quality_profile?.());
      if (!r || !r.ok) { _setProfileMsg("Export impossible.", "error"); return; }
      const json = r.json || JSON.stringify(r.profile_json || {}, null, 2);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `cinesort_quality_profile_${r.profile_id || "active"}.json`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 0);
      _setProfileMsg("Profil exporte.", "success");
    } catch (err) { _setProfileMsg("Erreur export : " + err, "error"); }
  });

  $("btnQualityImportProfile")?.addEventListener("click", () => {
    $("qualityImportInput")?.click();
  });

  $("qualityImportInput")?.addEventListener("change", (ev) => {
    const f = ev.target.files && ev.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const profile = JSON.parse(String(reader.result || ""));
        const r = await apiCall("import_quality_profile", () => window.pywebview.api.import_quality_profile?.(profile));
        if (!r || !r.ok) { _setProfileMsg("Import refuse : " + ((r && r.message) || "format invalide"), "error"); return; }
        _setProfileMsg("Profil importe et actif.", "success");
        await loadQualityProfile();
        await refreshQualityView({ silent: true });
      } catch (err) { _setProfileMsg("JSON invalide : " + err, "error"); }
    };
    reader.readAsText(f);
    ev.target.value = "";
  });

  $("btnQualityResetProfile")?.addEventListener("click", async () => {
    if (!confirm("Reinitialiser le profil de scoring au profil par defaut ?")) return;
    try {
      const r = await apiCall("reset_quality_profile", () => window.pywebview.api.reset_quality_profile?.());
      if (!r || !r.ok) { _setProfileMsg("Reinitialisation impossible.", "error"); return; }
      _setProfileMsg("Profil reinitialise.", "success");
      await loadQualityProfile();
      await refreshQualityView({ silent: true });
    } catch (err) { _setProfileMsg("Erreur : " + err, "error"); }
  });
}

function _setProfileMsg(text, level) {
  const el = document.getElementById("qualityProfileMsg");
  if (!el) return;
  el.textContent = text || "";
  el.className = level === "error" ? "status-msg isError" : level === "success" ? "status-msg isSuccess" : "text-muted";
}
