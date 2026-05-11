/* views/quality-simulator.js — Simulateur de preset qualite (G5)
 *
 * Usage : openQualitySimulator() - lance la modale.
 * Expose en global : window.openQualitySimulator.
 */

(function () {
  /* --- Etat local ------------------------------------------------- */
  const simState = {
    activeTab: "simple",
    selectedPreset: null,
    overrides: null,
    lastResult: null,
    inFlight: false,
    sliderTimer: null,
  };

  function _esc(s) {
    if (window.escapeHtml) return window.escapeHtml(s);
    return String(s || "").replace(/[<>&"']/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function _deltaHtml(delta, suffix) {
    const d = Number(delta) || 0;
    if (d === 0) return `<span class="qsim-delta qsim-delta--neutral">±0${suffix || ""}</span>`;
    const sign = d > 0 ? "+" : "";
    const cls = d > 0 ? "positive" : "negative";
    return `<span class="qsim-delta qsim-delta--${cls}">${sign}${d}${suffix || ""}</span>`;
  }

  function openQualitySimulator(initialOverrides) {
    if (typeof openModal !== "function") return;
    openModal("modalQualitySimulator");
    _resetState();
    _hookTabs();
    _hookCards();
    _hookSliders();
    _hookActions();
    _showPanel("simple");
    _showEmptyState();
    // G6 : overrides externes (ex: custom_rules depuis l'editeur)
    if (initialOverrides && typeof initialOverrides === "object") {
      simState.pendingOverrides = { ...initialOverrides };
    }
  }

  function _resetState() {
    simState.selectedPreset = null;
    simState.overrides = null;
    simState.lastResult = null;
    const results = document.getElementById("qsimResults");
    if (results) results.classList.add("hidden");
    const empty = document.getElementById("qsimEmpty");
    if (empty) empty.classList.remove("hidden");
    document.querySelectorAll(".qsim-preset-card").forEach((c) => {
      c.classList.remove("is-active");
      c.setAttribute("aria-checked", "false");
    });
    _disableActions();
  }

  function _disableActions() {
    const apply = document.getElementById("qsimBtnApply");
    const save = document.getElementById("qsimBtnSaveCustom");
    if (apply) apply.disabled = true;
    if (save) save.disabled = true;
  }

  function _enableActions() {
    const apply = document.getElementById("qsimBtnApply");
    const save = document.getElementById("qsimBtnSaveCustom");
    if (apply) apply.disabled = false;
    if (save) save.disabled = false;
  }

  function _hookTabs() {
    document.querySelectorAll(".qsim-tab").forEach((btn) => {
      if (btn.dataset.hookedQsim) return;
      btn.dataset.hookedQsim = "1";
      btn.addEventListener("click", () => _showPanel(btn.dataset.qsimTab));
    });
  }

  function _showPanel(tab) {
    simState.activeTab = tab;
    document.querySelectorAll(".qsim-tab").forEach((b) => {
      const active = b.dataset.qsimTab === tab;
      b.classList.toggle("is-active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll(".qsim-panel").forEach((p) => {
      p.classList.toggle("hidden", p.dataset.qsimPanel !== tab);
    });
  }

  function _hookCards() {
    document.querySelectorAll(".qsim-preset-card").forEach((card) => {
      if (card.dataset.hookedQsim) return;
      card.dataset.hookedQsim = "1";
      card.addEventListener("click", () => _selectPreset(card.dataset.presetId));
    });
  }

  function _selectPreset(presetId) {
    simState.selectedPreset = presetId;
    simState.overrides = null;
    document.querySelectorAll(".qsim-preset-card").forEach((c) => {
      const active = c.dataset.presetId === presetId;
      c.classList.toggle("is-active", active);
      c.setAttribute("aria-checked", active ? "true" : "false");
    });
    _runSimulation();
  }

  function _hookSliders() {
    document.querySelectorAll("[data-qsim-weight], [data-qsim-tier]").forEach((el) => {
      if (el.dataset.hookedQsim) return;
      el.dataset.hookedQsim = "1";
      el.addEventListener("input", _onSliderChange);
    });
  }

  function _onSliderChange() {
    _refreshSliderOutputs();
    clearTimeout(simState.sliderTimer);
    simState.sliderTimer = setTimeout(() => {
      if (!simState.selectedPreset) return;
      simState.overrides = _gatherOverrides();
      _runSimulation();
    }, 280);
  }

  function _refreshSliderOutputs() {
    const mapW = [["video", "qsimWVideoOut", " %"], ["audio", "qsimWAudioOut", " %"], ["extras", "qsimWExtrasOut", " %"]];
    for (const [key, outId, suffix] of mapW) {
      const input = document.querySelector(`[data-qsim-weight="${key}"]`);
      const out = document.getElementById(outId);
      if (input && out) out.textContent = `${input.value}${suffix}`;
    }
    const mapT = [["premium", "qsimTPremiumOut"], ["bon", "qsimTBonOut"], ["moyen", "qsimTMoyenOut"]];
    for (const [key, outId] of mapT) {
      const input = document.querySelector(`[data-qsim-tier="${key}"]`);
      const out = document.getElementById(outId);
      if (input && out) out.textContent = input.value;
    }
  }

  function _gatherOverrides() {
    const weights = {};
    ["video", "audio", "extras"].forEach((k) => {
      const el = document.querySelector(`[data-qsim-weight="${k}"]`);
      if (el) weights[k] = parseInt(el.value, 10);
    });
    const tiers = {};
    ["premium", "bon", "moyen"].forEach((k) => {
      const el = document.querySelector(`[data-qsim-tier="${k}"]`);
      if (el) tiers[k] = parseInt(el.value, 10);
    });
    const out = { weights, tiers };
    // G6 : merge custom_rules si passes via openQualitySimulator
    if (simState.pendingOverrides && Array.isArray(simState.pendingOverrides.custom_rules)) {
      out.custom_rules = simState.pendingOverrides.custom_rules;
    }
    return out;
  }

  async function _runSimulation() {
    if (simState.inFlight) return;
    if (!simState.selectedPreset) return;
    const scope = document.getElementById("qsimScope")?.value || "run";

    simState.inFlight = true;
    _setLoading(true);
    try {
      const res = await apiCall("simulate_quality_preset", () =>
        window.pywebview.api.simulate_quality_preset(
          state.runId || "latest",
          simState.selectedPreset,
          simState.overrides,
          scope
        ), { fallbackMessage: "Simulation impossible." });
      if (!res || !res.ok) {
        if (window.toast) window.toast({ type: "error", text: (res && res.message) || "Simulation echouee." });
        return;
      }
      simState.lastResult = res;
      _renderResults(res);
      _enableActions();
    } finally {
      simState.inFlight = false;
      _setLoading(false);
    }
  }

  function _setLoading(isLoading) {
    const card = document.querySelector(".qsim-card");
    if (card) card.classList.toggle("qsim-loading", !!isLoading);
  }

  function _showEmptyState() {
    const empty = document.getElementById("qsimEmpty");
    if (empty) empty.classList.remove("hidden");
  }

  function _renderResults(data) {
    document.getElementById("qsimEmpty")?.classList.add("hidden");
    document.getElementById("qsimResults")?.classList.remove("hidden");

    document.getElementById("qsimBeforeValue").textContent = data.before.avg_score;
    document.getElementById("qsimBeforeProfile").textContent = data.before.profile_name || "Actuel";
    document.getElementById("qsimAfterValue").textContent = data.after.avg_score;
    document.getElementById("qsimAfterProfile").textContent = data.after.profile_name || data.preset_label;

    const deltaBadge = document.getElementById("qsimDeltaBadge");
    if (deltaBadge) deltaBadge.innerHTML = _deltaHtml(data.delta.avg_score_delta, " pts");

    _renderTiersChart(data.before.tiers, data.after.tiers);
    _renderStatsPills(data);
    _renderImpacted(data.top_winners, "qsimWinnersList");
    _renderImpacted(data.top_losers, "qsimLosersList");
    _renderBreakdown(data.by_codec, "qsimByCodec");
    _renderBreakdown(data.by_resolution, "qsimByResolution");
    _renderAdvancedStats(data);
  }

  function _renderTiersChart(before, after) {
    const host = document.getElementById("qsimTiersChart");
    if (!host) return;
    // U1 audit : tiers modernes (Platinum/Gold/Silver/Bronze/Reject, migration 011)
    const order = ["Platinum", "Gold", "Silver", "Bronze", "Reject"];
    const colors = {
      Platinum: "var(--success)",
      Gold: "var(--accent)",
      Silver: "var(--info, #38BDF8)",
      Bronze: "var(--warning)",
      Reject: "var(--danger)",
    };
    const maxVal = Math.max(1, ...order.flatMap((t) => [before[t] || 0, after[t] || 0]));

    const barW = 38, gap = 8, groupGap = 28;
    const W = order.length * (2 * barW + gap + groupGap);
    const H = 160, baseY = H - 36;

    let svg = `<svg class="qsim-bar-chart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Distribution par tier avant et apres">`;
    order.forEach((t, i) => {
      const gx = i * (2 * barW + gap + groupGap) + 10;
      const b = before[t] || 0;
      const a = after[t] || 0;
      const bh = Math.round((b / maxVal) * (baseY - 10));
      const ah = Math.round((a / maxVal) * (baseY - 10));
      svg += `<rect x="${gx}" y="${baseY - bh}" width="${barW}" height="${bh}" rx="3" fill="${colors[t]}" opacity="0.35"><title>${t} (avant) : ${b}</title></rect>`;
      svg += `<rect x="${gx + barW + gap}" y="${baseY - ah}" width="${barW}" height="${ah}" rx="3" fill="${colors[t]}"><title>${t} (apres) : ${a}</title></rect>`;
      svg += `<text x="${gx + barW + gap / 2}" y="${baseY + 16}" text-anchor="middle" fill="currentColor" font-size="11">${t}</text>`;
      svg += `<text x="${gx + barW / 2}" y="${baseY - bh - 4}" text-anchor="middle" fill="currentColor" font-size="10" opacity="0.7">${b}</text>`;
      svg += `<text x="${gx + barW + gap + barW / 2}" y="${baseY - ah - 4}" text-anchor="middle" fill="currentColor" font-size="10" font-weight="600">${a}</text>`;
    });
    svg += `</svg>`;
    svg += `<div class="qsim-chart-legend"><span class="qsim-legend qsim-legend--before">Avant</span><span class="qsim-legend qsim-legend--after">Après</span></div>`;
    host.innerHTML = svg;
  }

  function _renderStatsPills(data) {
    const host = document.getElementById("qsimStatsPills");
    if (!host) return;
    const d = data.delta;
    const pills = [
      { cls: d.premium_gained > 0 ? "positive" : "neutral", value: `+${d.premium_gained}`, label: "Premium gagnés" },
      { cls: d.mauvais_reduced > 0 ? "positive" : "neutral", value: `-${d.mauvais_reduced}`, label: "Faibles réduits" },
      { cls: "neutral", value: d.unchanged_count, label: "Sans changement" },
      { cls: d.net_tier_degradation > 0 ? "negative" : "neutral", value: d.net_tier_degradation, label: "Rétrogradés" },
    ];
    host.innerHTML = pills.map((p) => `
      <div class="qsim-stat qsim-stat--${p.cls}">
        <span class="qsim-stat__value">${_esc(p.value)}</span>
        <span class="qsim-stat__label">${_esc(p.label)}</span>
      </div>`).join("");
  }

  function _renderImpacted(list, targetId) {
    const host = document.getElementById(targetId);
    if (!host) return;
    if (!list || list.length === 0) {
      host.innerHTML = `<li class="text-muted">—</li>`;
      return;
    }
    host.innerHTML = list.slice(0, 8).map((r) => `
      <li class="qsim-impacted-item">
        <span class="qsim-impacted-item__title">${_esc(r.title || r.row_id)}</span>
        <span class="qsim-impacted-item__tiers">
          <span class="qsim-tier-chip qsim-tier-chip--${String(r.tier_before || "").toLowerCase()}">${_esc(r.tier_before || "")}</span>
          →
          <span class="qsim-tier-chip qsim-tier-chip--${String(r.tier_after || "").toLowerCase()}">${_esc(r.tier_after || "")}</span>
        </span>
        <span class="qsim-impacted-item__delta">${_deltaHtml(r.delta, " pts")}</span>
      </li>`).join("");
  }

  function _renderBreakdown(dict, targetId) {
    const host = document.getElementById(targetId);
    if (!host) return;
    const entries = Object.entries(dict || {}).sort((a, b) => (b[1].count || 0) - (a[1].count || 0));
    if (entries.length === 0) {
      host.innerHTML = `<tr><td class="text-muted">—</td></tr>`;
      return;
    }
    host.innerHTML = entries.map(([k, v]) => `
      <tr>
        <td class="qsim-breakdown-key">${_esc(k || "—")}</td>
        <td class="qsim-breakdown-count">${v.count}</td>
        <td class="qsim-breakdown-delta">${_deltaHtml(v.avg_delta)}</td>
      </tr>`).join("");
  }

  function _renderAdvancedStats(data) {
    const host = document.getElementById("qsimAdvStats");
    if (!host) return;
    host.innerHTML = `
      <div class="qsim-stat qsim-stat--neutral">
        <span class="qsim-stat__value">${data.films_count}</span>
        <span class="qsim-stat__label">films simulés</span>
      </div>
      <div class="qsim-stat qsim-stat--neutral">
        <span class="qsim-stat__value">${data.elapsed_ms} ms</span>
        <span class="qsim-stat__label">calcul</span>
      </div>
      <div class="qsim-stat qsim-stat--${data.delta.avg_score_delta > 0 ? "positive" : "negative"}">
        <span class="qsim-stat__value">${_deltaHtml(data.delta.avg_score_delta, " pts")}</span>
        <span class="qsim-stat__label">score moyen</span>
      </div>`;
  }

  function _hookActions() {
    const btnApply = document.getElementById("qsimBtnApply");
    if (btnApply && !btnApply.dataset.hookedQsim) {
      btnApply.dataset.hookedQsim = "1";
      btnApply.addEventListener("click", _applyPreset);
    }
    const btnSave = document.getElementById("qsimBtnSaveCustom");
    if (btnSave && !btnSave.dataset.hookedQsim) {
      btnSave.dataset.hookedQsim = "1";
      btnSave.addEventListener("click", _saveCustom);
    }
  }

  async function _applyPreset() {
    if (!simState.selectedPreset) return;
    if (typeof uiConfirm === "function") {
      const ok = await uiConfirm({
        title: "Appliquer ce preset ?",
        message: `Le profil qualité actif sera remplacé par "${simState.selectedPreset}". Les scores seront recalculés au prochain scan.`,
        confirmLabel: "Appliquer",
      });
      if (!ok) return;
    }
    const res = await apiCall("apply_quality_preset", () =>
      window.pywebview.api.apply_quality_preset(simState.selectedPreset),
      { fallbackMessage: "Application impossible." });
    if (res && res.ok) {
      if (window.toast) window.toast({ type: "success", text: `Preset "${simState.selectedPreset}" appliqué.` });
      if (typeof closeModal === "function") closeModal("modalQualitySimulator");
      if (typeof refreshQualityView === "function") refreshQualityView();
    }
  }

  async function _saveCustom() {
    if (!simState.lastResult) return;
    const name = window.prompt("Nom du preset custom :");
    if (!name || !name.trim()) return;
    const base = await apiCall("get_quality_presets", () => window.pywebview.api.get_quality_presets(), {});
    let profileJson = null;
    if (base && Array.isArray(base.presets)) {
      const match = base.presets.find((p) => p.preset_id === simState.selectedPreset);
      if (match) profileJson = match.profile_json || null;
    }
    if (!profileJson) {
      if (window.toast) window.toast({ type: "error", text: "Impossible de récupérer le profil de base." });
      return;
    }
    if (simState.overrides) {
      profileJson.weights = { ...(profileJson.weights || {}), ...(simState.overrides.weights || {}) };
      profileJson.tiers = { ...(profileJson.tiers || {}), ...(simState.overrides.tiers || {}) };
    }
    const res = await apiCall("save_custom_quality_preset", () =>
      window.pywebview.api.save_custom_quality_preset(name.trim(), profileJson),
      { fallbackMessage: "Sauvegarde impossible." });
    if (res && res.ok) {
      if (window.toast) window.toast({ type: "success", text: `Preset "${name}" enregistré.` });
    }
  }

  window.openQualitySimulator = openQualitySimulator;

  // H-9 audit QA 20260429 : remplace l'onclick inline du bouton
  // #btnQualitySimulate (qui assumait que openQualitySimulator soit deja
  // global au moment du parse HTML — race condition au boot). On attache
  // un event listener apres DOMContentLoaded ce qui garantit que la
  // fonction est bien definie ici.
  function _wireSimulateButton() {
    const btn = document.getElementById("btnQualitySimulate");
    if (btn && !btn._cineSimWired) {
      btn._cineSimWired = true;
      btn.addEventListener("click", () => openQualitySimulator());
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _wireSimulateButton);
  } else {
    _wireSimulateButton();
  }
})();
