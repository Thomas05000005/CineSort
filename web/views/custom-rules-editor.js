/* custom-rules-editor.js — Éditeur visuel de règles custom (G6) desktop. */
(function () {
  "use strict";

  const FIELD_GROUPS = [
    { label: "Vidéo", options: [
      ["video_codec", "Codec vidéo"],
      ["resolution", "Résolution"],
      ["resolution_rank", "Rang résolution (0-3)"],
      ["bitrate_kbps", "Bitrate (kbps)"],
      ["has_hdr10", "HDR10"],
      ["has_hdr10p", "HDR10+"],
      ["has_dv", "Dolby Vision"],
    ]},
    { label: "Audio", options: [
      ["audio_codec", "Codec audio"],
      ["audio_channels", "Canaux audio"],
    ]},
    { label: "Métadonnées", options: [
      ["year", "Année"],
      ["edition", "Édition"],
      ["tmdb_in_collection", "Dans une collection"],
    ]},
    { label: "Sous-titres", options: [
      ["subtitle_count", "Nombre de sous-titres"],
      ["subtitle_langs", "Langues sous-titres"],
    ]},
    { label: "Signaux", options: [
      ["warning_flags", "Alertes"],
      ["tier_before", "Tier avant règles"],
      ["score_before", "Score avant règles"],
      ["file_size_gb", "Taille (Go)"],
      ["duration_s", "Durée (s)"],
    ]},
  ];

  const OPERATORS = [
    ["=", "="],
    ["!=", "≠"],
    ["<", "<"],
    ["<=", "≤"],
    [">", ">"],
    [">=", "≥"],
    ["in", "est dans"],
    ["not_in", "pas dans"],
    ["contains", "contient"],
    ["not_contains", "ne contient pas"],
    ["between", "entre"],
  ];

  const ACTION_TYPES = [
    ["score_delta", "Ajouter/retirer des points"],
    ["score_multiplier", "Multiplier le score"],
    ["force_score", "Forcer le score à"],
    ["force_tier", "Forcer le tier"],
    ["cap_max", "Plafonner le score à"],
    ["cap_min", "Relever le score à"],
    ["flag_warning", "Ajouter un flag"],
  ];

  const state = {
    rules: [],
    templates: null,
    loaded: false,
  };

  function _genId() {
    return "rule_" + Math.random().toString(36).slice(2, 10);
  }

  function _esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function _normalizeRule(r) {
    const cleaned = {
      id: r.id || _genId(),
      name: r.name || "Règle sans nom",
      description: r.description || "",
      enabled: r.enabled !== false,
      priority: Number.isFinite(+r.priority) ? +r.priority : 10,
      conditions: Array.isArray(r.conditions) ? r.conditions.map(c => ({
        field: c.field || "video_codec",
        op: c.op || "=",
        value: c.value == null ? "" : c.value,
      })) : [],
      match: r.match === "any" ? "any" : "all",
      action: {
        type: (r.action && r.action.type) || "score_delta",
        value: r.action ? (r.action.value == null ? "" : r.action.value) : 0,
        reason: (r.action && r.action.reason) || "",
      },
    };
    if (!cleaned.conditions.length) {
      cleaned.conditions.push({ field: "video_codec", op: "=", value: "" });
    }
    return cleaned;
  }

  function _fieldOptionsHtml(selected) {
    return FIELD_GROUPS.map(g => {
      const opts = g.options.map(([v, l]) =>
        `<option value="${_esc(v)}"${v === selected ? " selected" : ""}>${_esc(l)}</option>`).join("");
      return `<optgroup label="${_esc(g.label)}">${opts}</optgroup>`;
    }).join("");
  }

  function _opOptionsHtml(selected) {
    return OPERATORS.map(([v, l]) =>
      `<option value="${_esc(v)}"${v === selected ? " selected" : ""}>${_esc(l)}</option>`).join("");
  }

  function _actionOptionsHtml(selected) {
    return ACTION_TYPES.map(([v, l]) =>
      `<option value="${_esc(v)}"${v === selected ? " selected" : ""}>${_esc(l)}</option>`).join("");
  }

  function _formatValueForInput(val) {
    if (Array.isArray(val)) return val.join(",");
    if (typeof val === "boolean") return val ? "true" : "false";
    return String(val == null ? "" : val);
  }

  function _parseValue(raw, op) {
    const s = String(raw || "").trim();
    if (!s) return "";
    if (op === "between") {
      const parts = s.split(",").map(x => x.trim()).filter(Boolean);
      return parts.map(x => Number.isFinite(+x) ? +x : x);
    }
    if (op === "in" || op === "not_in") {
      return s.split(",").map(x => x.trim()).filter(Boolean);
    }
    if (s === "true") return true;
    if (s === "false") return false;
    if (Number.isFinite(+s) && /^-?\d+(\.\d+)?$/.test(s)) return +s;
    return s;
  }

  function _renderConditionRow(ruleId, cond, condIdx) {
    const value = _formatValueForInput(cond.value);
    return `
      <div class="rule-condition" data-rule-id="${_esc(ruleId)}" data-cond-idx="${condIdx}">
        <select class="input" data-cond-field>${_fieldOptionsHtml(cond.field)}</select>
        <select class="input" data-cond-op>${_opOptionsHtml(cond.op)}</select>
        <input type="text" class="input rule-condition__value" data-cond-value value="${_esc(value)}" placeholder="valeur (liste : a,b,c)" />
        <button type="button" class="btn btn--compact btn--ghost rule-condition__delete" data-action="delete-condition" title="Supprimer cette condition">✕</button>
      </div>`;
  }

  function _renderRuleCard(rule) {
    const condsHtml = rule.conditions.map((c, i) => _renderConditionRow(rule.id, c, i)).join("");
    const disabledClass = rule.enabled ? "" : " rule-card--disabled";
    return `
      <article class="rule-card${disabledClass}" data-rule-id="${_esc(rule.id)}">
        <header class="rule-card__header">
          <label class="rule-toggle" title="Activer/désactiver">
            <input type="checkbox" data-rule-enabled${rule.enabled ? " checked" : ""} />
            <span class="rule-toggle__label">${rule.enabled ? "Actif" : "Désactivé"}</span>
          </label>
          <input type="text" class="input rule-card__name" data-rule-name value="${_esc(rule.name)}" placeholder="Nom de la règle" />
          <label class="rule-card__priority" title="Priorité (plus petit = exécuté en premier)">
            <span>Prio</span>
            <input type="number" min="0" max="999" class="input" data-rule-priority value="${_esc(rule.priority)}" />
          </label>
          <button type="button" class="btn btn--compact btn--ghost" data-action="move-up" title="Monter">↑</button>
          <button type="button" class="btn btn--compact btn--ghost" data-action="move-down" title="Descendre">↓</button>
          <button type="button" class="btn btn--compact btn--ghost rule-card__delete" data-action="delete-rule" title="Supprimer la règle">✕</button>
        </header>

        <section class="rule-card__body">
          <div class="rule-conditions">
            <div class="rule-conditions__header">
              <span class="rule-kw">SI</span>
              <select class="input" data-rule-match>
                <option value="all"${rule.match === "all" ? " selected" : ""}>toutes les conditions</option>
                <option value="any"${rule.match === "any" ? " selected" : ""}>au moins une condition</option>
              </select>
              <span class="text-muted">se vérifient :</span>
            </div>
            <div class="rule-conditions__list" data-conditions-list>${condsHtml}</div>
            <button type="button" class="btn btn--compact btn--ghost" data-action="add-condition">+ Condition</button>
          </div>

          <div class="rule-action">
            <span class="rule-kw">ALORS</span>
            <select class="input" data-action-type>${_actionOptionsHtml(rule.action.type)}</select>
            <input type="text" class="input rule-action__value" data-action-value value="${_esc(_formatValueForInput(rule.action.value))}" placeholder="Valeur" />
            <input type="text" class="input rule-action__reason" data-action-reason value="${_esc(rule.action.reason)}" placeholder="Raison (optionnel)" />
          </div>
        </section>
      </article>`;
  }

  function _render() {
    const host = document.getElementById("customRulesList");
    if (!host) return;
    const sorted = [...state.rules].sort((a, b) => (a.priority - b.priority) || 0);
    if (!sorted.length) {
      host.innerHTML = `<p class="text-muted" style="text-align:center;padding:var(--sp-4)">Aucune règle. Chargez un template ou ajoutez-en une.</p>`;
    } else {
      host.innerHTML = sorted.map(_renderRuleCard).join("");
    }
    const count = document.getElementById("rulesCount");
    if (count) count.textContent = `${state.rules.length} règle(s)`;
    const btnSim = document.getElementById("btnRulesPreviewImpact");
    if (btnSim) btnSim.disabled = state.rules.length === 0;
  }

  function _findRule(ruleId) {
    return state.rules.find(r => r.id === ruleId);
  }

  function _gatherRuleFromDom(card) {
    const id = card.getAttribute("data-rule-id");
    const rule = _findRule(id);
    if (!rule) return null;
    rule.enabled = !!card.querySelector('[data-rule-enabled]').checked;
    rule.name = card.querySelector('[data-rule-name]').value || "Règle sans nom";
    rule.priority = +card.querySelector('[data-rule-priority]').value || 0;
    rule.match = card.querySelector('[data-rule-match]').value === "any" ? "any" : "all";
    const condRows = card.querySelectorAll(".rule-condition");
    rule.conditions = Array.from(condRows).map(row => {
      const field = row.querySelector('[data-cond-field]').value;
      const op = row.querySelector('[data-cond-op]').value;
      const raw = row.querySelector('[data-cond-value]').value;
      return { field, op, value: _parseValue(raw, op) };
    });
    const atype = card.querySelector('[data-action-type]').value;
    const aval = card.querySelector('[data-action-value]').value;
    const areason = card.querySelector('[data-action-reason]').value;
    rule.action = {
      type: atype,
      value: _parseValue(aval, atype === "force_tier" || atype === "flag_warning" ? "=" : "="),
      reason: areason,
    };
    return rule;
  }

  function _gatherAllRules() {
    const host = document.getElementById("customRulesList");
    if (!host) return [];
    host.querySelectorAll(".rule-card").forEach(card => _gatherRuleFromDom(card));
    return state.rules.map(r => ({
      id: r.id,
      name: r.name,
      description: r.description,
      enabled: r.enabled,
      priority: r.priority,
      conditions: r.conditions,
      match: r.match,
      action: r.action,
    }));
  }

  function _addRule() {
    const rule = _normalizeRule({
      id: _genId(),
      name: "Nouvelle règle",
      enabled: true,
      priority: (Math.max(0, ...state.rules.map(r => r.priority)) + 10),
      conditions: [{ field: "video_codec", op: "=", value: "" }],
      action: { type: "score_delta", value: 0, reason: "" },
    });
    state.rules.push(rule);
    _render();
  }

  function _deleteRule(ruleId) {
    state.rules = state.rules.filter(r => r.id !== ruleId);
    _render();
  }

  function _moveRule(ruleId, direction) {
    _gatherAllRules();
    const rule = _findRule(ruleId);
    if (!rule) return;
    const sorted = [...state.rules].sort((a, b) => a.priority - b.priority);
    const idx = sorted.findIndex(r => r.id === ruleId);
    if (idx < 0) return;
    const swapIdx = direction === "up" ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= sorted.length) return;
    const other = sorted[swapIdx];
    const tmp = rule.priority;
    rule.priority = other.priority;
    other.priority = tmp;
    _render();
  }

  function _addCondition(ruleId) {
    _gatherAllRules();
    const rule = _findRule(ruleId);
    if (!rule) return;
    rule.conditions.push({ field: "video_codec", op: "=", value: "" });
    _render();
  }

  function _deleteCondition(ruleId, condIdx) {
    _gatherAllRules();
    const rule = _findRule(ruleId);
    if (!rule) return;
    rule.conditions.splice(condIdx, 1);
    if (!rule.conditions.length) {
      rule.conditions.push({ field: "video_codec", op: "=", value: "" });
    }
    _render();
  }

  async function _loadTemplates() {
    if (state.templates) return state.templates;
    try {
      const res = await window.pywebview.api.get_custom_rules_templates();
      state.templates = (res && res.templates) || [];
    } catch (e) {
      state.templates = [];
    }
    return state.templates;
  }

  async function _applyTemplate(templateId) {
    await _loadTemplates();
    const tpl = (state.templates || []).find(t => t.id === templateId);
    if (!tpl) return;
    if (state.rules.length && !confirm(`Charger le template "${tpl.name}" ? Les règles actuelles seront remplacées.`)) {
      return;
    }
    state.rules = (tpl.rules || []).map(r => _normalizeRule({ ...r, id: _genId() }));
    _render();
    _setMsg(`Template "${tpl.name}" chargé (${state.rules.length} règle(s)).`);
  }

  function _exportJson() {
    const payload = JSON.stringify(_gatherAllRules(), null, 2);
    const blob = new Blob([payload], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cinesort_custom_rules.json";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 0);
  }

  function _importJson(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result || ""));
        if (!Array.isArray(parsed)) throw new Error("Le JSON doit être un tableau de règles.");
        state.rules = parsed.map(r => _normalizeRule({ ...r, id: r.id || _genId() }));
        _render();
        _setMsg(`${state.rules.length} règle(s) importée(s).`);
      } catch (e) {
        _setMsg("Import échoué : " + (e.message || e), "error");
      }
    };
    reader.onerror = () => _setMsg("Lecture du fichier impossible.", "error");
    reader.readAsText(file);
  }

  async function _saveRules() {
    const rules = _gatherAllRules();
    try {
      // Validation preflight
      const v = await window.pywebview.api.validate_custom_rules(rules);
      if (!v || !v.ok) {
        _setMsg("Règles invalides : " + ((v && v.errors) || []).join(" ; "), "error");
        return;
      }
      // Charger le profil actif, injecter custom_rules, sauver
      const profRes = await window.pywebview.api.get_quality_profile();
      if (!profRes || !profRes.ok) {
        _setMsg("Profil qualité introuvable.", "error");
        return;
      }
      const profile = profRes.profile_json || {};
      profile.custom_rules = v.normalized || rules;
      const saveRes = await window.pywebview.api.save_quality_profile(profile);
      if (!saveRes || !saveRes.ok) {
        _setMsg("Sauvegarde impossible : " + ((saveRes && (saveRes.message || (saveRes.errors || []).join(" ; "))) || "erreur"), "error");
        return;
      }
      _setMsg(`Règles enregistrées (${rules.length}).`, "success");
    } catch (e) {
      _setMsg("Erreur : " + (e.message || e), "error");
    }
  }

  function _setMsg(text, level) {
    const el = document.getElementById("rulesMsg");
    if (!el) return;
    el.textContent = text || "";
    el.className = "status-msg" + (level === "error" ? " status-msg--error" : level === "success" ? " status-msg--success" : "");
  }

  async function _previewImpact() {
    _gatherAllRules();
    const rules = state.rules;
    if (!rules.length) return;
    if (typeof window.openQualitySimulator === "function") {
      window.openQualitySimulator({ custom_rules: rules });
    } else {
      _setMsg("Simulateur indisponible.", "error");
    }
  }

  function _hookEvents() {
    const host = document.getElementById("customRulesCard");
    if (!host || host.dataset.hooked === "1") return;
    host.dataset.hooked = "1";

    host.addEventListener("click", (ev) => {
      const tplBtn = ev.target.closest("[data-rule-template]");
      if (tplBtn) { _applyTemplate(tplBtn.getAttribute("data-rule-template")); return; }

      const t = ev.target.closest("[data-action]");
      if (t) {
        const action = t.getAttribute("data-action");
        const card = t.closest(".rule-card");
        const ruleId = card ? card.getAttribute("data-rule-id") : null;
        if (action === "delete-rule" && ruleId) { _deleteRule(ruleId); return; }
        if (action === "move-up" && ruleId) { _moveRule(ruleId, "up"); return; }
        if (action === "move-down" && ruleId) { _moveRule(ruleId, "down"); return; }
        if (action === "add-condition" && ruleId) { _addCondition(ruleId); return; }
        if (action === "delete-condition" && ruleId) {
          const row = t.closest(".rule-condition");
          if (row) _deleteCondition(ruleId, +row.getAttribute("data-cond-idx"));
          return;
        }
      }

      if (ev.target.id === "btnRuleAdd") { _addRule(); return; }
      if (ev.target.id === "btnRulesSave") { _saveRules(); return; }
      if (ev.target.id === "btnRulesImport") { document.getElementById("rulesImportInput").click(); return; }
      if (ev.target.id === "btnRulesExport") { _exportJson(); return; }
      if (ev.target.id === "btnRulesPreviewImpact") { _previewImpact(); return; }
    });

    const fileInput = document.getElementById("rulesImportInput");
    if (fileInput) {
      fileInput.addEventListener("change", () => {
        const f = fileInput.files && fileInput.files[0];
        if (f) _importJson(f);
        fileInput.value = "";
      });
    }
  }

  async function openCustomRulesEditor() {
    _hookEvents();
    if (!state.loaded) {
      try {
        const profRes = await window.pywebview.api.get_quality_profile();
        const profile = (profRes && profRes.profile_json) || {};
        state.rules = (profile.custom_rules || []).map(r => _normalizeRule({ ...r, id: r.id || _genId() }));
      } catch (e) {
        state.rules = [];
      }
      state.loaded = true;
    }
    _render();
  }

  // Expose
  window.openCustomRulesEditor = openCustomRulesEditor;
  window._customRulesState = state; // debug

  // Auto-init : attendre que la vue qualité soit visible et initialiser l'editeur
  document.addEventListener("DOMContentLoaded", () => {
    const card = document.getElementById("customRulesCard");
    if (card) {
      // Charger silencieusement (editeur s'affiche directement dans la vue qualité)
      openCustomRulesEditor().catch(() => {});
    }
  });
})();
