/* views/quality-simulator.js — Simulateur de preset qualite dashboard (G5 parite)
 *
 * Port ES module de web/views/quality-simulator.js (desktop).
 * Utilise showModal pour construire la modale dynamiquement.
 */

import { apiPost } from "../core/api.js";
import { showModal, closeModal } from "../components/modal.js";
import { escapeHtml } from "../core/dom.js";

/* --- Etat local --------------------------------------------- */
const simState = {
  selectedPreset: null,
  overrides: null,
  lastResult: null,
  inFlight: false,
  sliderTimer: null,
  activeTab: "simple",
  runId: "latest",
};

function _delta(delta, suffix) {
  const d = Number(delta) || 0;
  if (d === 0) return `<span class="qsim-delta qsim-delta--neutral">±0${suffix || ""}</span>`;
  const sign = d > 0 ? "+" : "";
  const cls = d > 0 ? "positive" : "negative";
  return `<span class="qsim-delta qsim-delta--${cls}">${sign}${d}${suffix || ""}</span>`;
}

function _buildBody() {
  return `
  <div class="qsim-scope-wrap" style="margin-bottom:12px">
    <label for="qsimScope" class="qsim-scope-label">Portée :</label>
    <select id="qsimScope" class="input" style="width:auto">
      <option value="run">Run courant</option>
      <option value="library">Toute la bibliothèque</option>
    </select>
  </div>

  <nav class="qsim-tabs" role="tablist">
    <button role="tab" type="button" class="qsim-tab is-active" data-qsim-tab="simple" aria-selected="true">Simple</button>
    <button role="tab" type="button" class="qsim-tab" data-qsim-tab="advanced" aria-selected="false">Avancé</button>
  </nav>

  <section class="qsim-panel" data-qsim-panel="simple">
    <div class="qsim-preset-grid" role="radiogroup" aria-label="Choisir un preset">
      <button type="button" class="qsim-preset-card" data-preset-id="equilibre" role="radio" aria-checked="false">
        <div class="qsim-preset-card__icon">⚖</div>
        <div class="qsim-preset-card__name">Équilibré</div>
        <div class="qsim-preset-card__hint">Recommandé pour bibliothèques mixtes</div>
      </button>
      <button type="button" class="qsim-preset-card" data-preset-id="remux_strict" role="radio" aria-checked="false">
        <div class="qsim-preset-card__icon">🎯</div>
        <div class="qsim-preset-card__name">Remux strict</div>
        <div class="qsim-preset-card__hint">Exigence élevée, bitrate priorisé</div>
      </button>
      <button type="button" class="qsim-preset-card" data-preset-id="light" role="radio" aria-checked="false">
        <div class="qsim-preset-card__icon">🪶</div>
        <div class="qsim-preset-card__name">Light</div>
        <div class="qsim-preset-card__hint">Tolérant, streaming-friendly</div>
      </button>
    </div>

    <div class="qsim-results hidden" id="qsimResults" aria-live="polite">
      <div class="qsim-before-after">
        <div class="qsim-score qsim-score--before">
          <div class="qsim-score__label">Avant</div>
          <div class="qsim-score__value" id="qsimBeforeValue">—</div>
          <div class="qsim-score__profile" id="qsimBeforeProfile">Actuel</div>
        </div>
        <div class="qsim-score__arrow" aria-hidden="true">→</div>
        <div class="qsim-score qsim-score--after">
          <div class="qsim-score__label">Après</div>
          <div class="qsim-score__value" id="qsimAfterValue">—</div>
          <div class="qsim-score__profile" id="qsimAfterProfile">—</div>
          <div class="qsim-score__delta" id="qsimDeltaBadge"></div>
        </div>
      </div>

      <div class="qsim-chart-wrap">
        <h3 class="qsim-section-title">Distribution par tier</h3>
        <div id="qsimTiersChart"></div>
      </div>

      <div class="qsim-stats" id="qsimStatsPills"></div>

      <details class="qsim-impacted">
        <summary>Films les plus impactés</summary>
        <div class="qsim-impacted-grid">
          <div class="qsim-impacted__col">
            <h4>🚀 Plus gros gains</h4>
            <ul id="qsimWinnersList"></ul>
          </div>
          <div class="qsim-impacted__col">
            <h4>📉 Plus grosses pertes</h4>
            <ul id="qsimLosersList"></ul>
          </div>
        </div>
      </details>

      <details class="qsim-breakdown">
        <summary>Impact par codec &amp; résolution</summary>
        <div class="qsim-breakdown-grid">
          <div><h4>Codec</h4><table class="qsim-breakdown-table" id="qsimByCodec"></table></div>
          <div><h4>Résolution</h4><table class="qsim-breakdown-table" id="qsimByResolution"></table></div>
        </div>
      </details>
    </div>

    <div class="qsim-empty" id="qsimEmpty">
      <p class="text-muted">Choisis un preset ci-dessus pour voir l'impact sur ton run courant.</p>
    </div>
  </section>

  <section class="qsim-panel hidden" data-qsim-panel="advanced">
    <p class="text-muted">Ajuste les pondérations et les seuils — la simulation se met à jour automatiquement.</p>

    <fieldset class="qsim-fieldset">
      <legend>Pondérations</legend>
      <div class="qsim-slider-row">
        <label>Vidéo <output id="qsimWVideoOut">60 %</output></label>
        <input type="range" min="0" max="100" value="60" data-qsim-weight="video" />
      </div>
      <div class="qsim-slider-row">
        <label>Audio <output id="qsimWAudioOut">30 %</output></label>
        <input type="range" min="0" max="100" value="30" data-qsim-weight="audio" />
      </div>
      <div class="qsim-slider-row">
        <label>Extras <output id="qsimWExtrasOut">10 %</output></label>
        <input type="range" min="0" max="100" value="10" data-qsim-weight="extras" />
      </div>
    </fieldset>

    <fieldset class="qsim-fieldset">
      <legend>Seuils de tiers</legend>
      <div class="qsim-slider-row">
        <label>Premium &ge; <output id="qsimTPremiumOut">85</output></label>
        <input type="range" min="70" max="95" value="85" data-qsim-tier="premium" />
      </div>
      <div class="qsim-slider-row">
        <label>Bon &ge; <output id="qsimTBonOut">68</output></label>
        <input type="range" min="55" max="80" value="68" data-qsim-tier="bon" />
      </div>
      <div class="qsim-slider-row">
        <label>Moyen &ge; <output id="qsimTMoyenOut">54</output></label>
        <input type="range" min="40" max="65" value="54" data-qsim-tier="moyen" />
      </div>
    </fieldset>

    <div class="qsim-advanced-mini-stats" id="qsimAdvStats"></div>
  </section>
  `;
}

export function openQualitySimulator(currentRunId, initialOverrides) {
  simState.runId = currentRunId || "latest";
  simState.selectedPreset = null;
  simState.overrides = null;
  simState.lastResult = null;
  simState.inFlight = false;
  simState.pendingOverrides = (initialOverrides && typeof initialOverrides === "object") ? { ...initialOverrides } : null;

  showModal({
    title: "Simuler un preset qualité",
    body: _buildBody(),
    actions: [
      { label: "Annuler", cls: "", onClick: () => closeModal() },
      { label: "💾 Sauver comme custom", cls: "qsim-save-btn", onClick: _saveCustom },
      { label: "✓ Appliquer ce preset", cls: "btn-primary qsim-apply-btn", onClick: _applyPreset },
    ],
  });

  /* Disable apply/save au depart */
  _setActionsDisabled(true);
  _hookAll();
  _showPanel("simple");
}

function _setActionsDisabled(disabled) {
  document.querySelectorAll("[data-modal-action]").forEach((btn) => {
    const label = (btn.textContent || "").trim();
    if (label.includes("Appliquer") || label.includes("Sauver")) {
      btn.disabled = !!disabled;
    }
  });
}

function _hookAll() {
  document.querySelectorAll(".qsim-tab").forEach((btn) => {
    btn.addEventListener("click", () => _showPanel(btn.dataset.qsimTab));
  });
  document.querySelectorAll(".qsim-preset-card").forEach((card) => {
    card.addEventListener("click", () => _selectPreset(card.dataset.presetId));
  });
  document.querySelectorAll("[data-qsim-weight], [data-qsim-tier]").forEach((el) => {
    el.addEventListener("input", _onSliderChange);
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
  // G6 : inclure custom_rules passes via openQualitySimulator
  if (simState.pendingOverrides && Array.isArray(simState.pendingOverrides.custom_rules)) {
    out.custom_rules = simState.pendingOverrides.custom_rules;
  }
  return out;
}

async function _runSimulation() {
  if (simState.inFlight || !simState.selectedPreset) return;
  simState.inFlight = true;
  _setLoading(true);
  try {
    const scope = document.getElementById("qsimScope")?.value || "run";
    const res = await apiPost("quality/simulate_quality_preset", {
      run_id: simState.runId || "latest",
      preset_id: simState.selectedPreset,
      overrides: simState.overrides,
      scope,
    });
    const data = res?.data || {};
    if (!data.ok) {
      _showError(data.message || "Simulation impossible.");
      return;
    }
    simState.lastResult = data;
    _renderResults(data);
    _setActionsDisabled(false);
  } finally {
    simState.inFlight = false;
    _setLoading(false);
  }
}

function _setLoading(isLoading) {
  const overlay = document.getElementById("dashModal");
  if (overlay) overlay.classList.toggle("qsim-loading", !!isLoading);
}

function _showError(msg) {
  const empty = document.getElementById("qsimEmpty");
  if (empty) empty.innerHTML = `<p class="status-msg error">${escapeHtml(msg)}</p>`;
  document.getElementById("qsimResults")?.classList.add("hidden");
}

function _renderResults(data) {
  document.getElementById("qsimEmpty")?.classList.add("hidden");
  document.getElementById("qsimResults")?.classList.remove("hidden");

  document.getElementById("qsimBeforeValue").textContent = data.before.avg_score;
  document.getElementById("qsimBeforeProfile").textContent = data.before.profile_name || "Actuel";
  document.getElementById("qsimAfterValue").textContent = data.after.avg_score;
  document.getElementById("qsimAfterProfile").textContent = data.after.profile_name || data.preset_label;

  const deltaBadge = document.getElementById("qsimDeltaBadge");
  if (deltaBadge) deltaBadge.innerHTML = _delta(data.delta.avg_score_delta, " pts");

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
      <span class="qsim-stat__value">${escapeHtml(String(p.value))}</span>
      <span class="qsim-stat__label">${escapeHtml(p.label)}</span>
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
      <span class="qsim-impacted-item__title">${escapeHtml(r.title || r.row_id)}</span>
      <span class="qsim-impacted-item__tiers">
        <span class="qsim-tier-chip qsim-tier-chip--${String(r.tier_before || "").toLowerCase()}">${escapeHtml(r.tier_before || "")}</span>
        →
        <span class="qsim-tier-chip qsim-tier-chip--${String(r.tier_after || "").toLowerCase()}">${escapeHtml(r.tier_after || "")}</span>
      </span>
      <span class="qsim-impacted-item__delta">${_delta(r.delta, " pts")}</span>
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
      <td class="qsim-breakdown-key">${escapeHtml(k || "—")}</td>
      <td class="qsim-breakdown-count">${v.count}</td>
      <td class="qsim-breakdown-delta">${_delta(v.avg_delta)}</td>
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
      <span class="qsim-stat__value">${_delta(data.delta.avg_score_delta, " pts")}</span>
      <span class="qsim-stat__label">score moyen</span>
    </div>`;
}

async function _applyPreset() {
  if (!simState.selectedPreset) return;
  if (!window.confirm(`Appliquer le preset "${simState.selectedPreset}" ? Le profil qualité actif sera remplacé.`)) return;
  const res = await apiPost("quality/apply_quality_preset", { preset_id: simState.selectedPreset });
  if (res?.data?.ok) {
    closeModal();
    if (window.showToast) window.showToast({ type: "success", text: `Preset "${simState.selectedPreset}" appliqué.` });
  } else if (window.showToast) {
    window.showToast({ type: "error", text: (res?.data?.message) || "Application impossible." });
  }
}

async function _saveCustom() {
  if (!simState.lastResult) return;
  const name = window.prompt("Nom du preset custom :");
  if (!name || !name.trim()) return;
  const base = await apiPost("quality/get_quality_presets");
  let profileJson = null;
  const presets = base?.data?.presets || [];
  const match = presets.find((p) => p.preset_id === simState.selectedPreset);
  if (match) profileJson = match.profile_json || null;
  if (!profileJson) {
    if (window.showToast) window.showToast({ type: "error", text: "Impossible de récupérer le profil de base." });
    return;
  }
  if (simState.overrides) {
    profileJson.weights = { ...(profileJson.weights || {}), ...(simState.overrides.weights || {}) };
    profileJson.tiers = { ...(profileJson.tiers || {}), ...(simState.overrides.tiers || {}) };
  }
  const res = await apiPost("quality/save_custom_quality_preset", { name: name.trim(), profile_json: profileJson });
  if (res?.data?.ok && window.showToast) {
    window.showToast({ type: "success", text: `Preset "${name}" enregistré.` });
  }
}
