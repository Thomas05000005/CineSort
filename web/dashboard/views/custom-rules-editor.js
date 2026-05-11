/* views/custom-rules-editor.js — Editeur de regles custom (G6) dashboard ES module.
 * Parite avec web/views/custom-rules-editor.js (desktop).
 */

import { apiPost } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { showModal, closeModal } from "../components/modal.js";
import { openQualitySimulator } from "./quality-simulator.js";

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
  ["=", "="], ["!=", "≠"],
  ["<", "<"], ["<=", "≤"], [">", ">"], [">=", "≥"],
  ["in", "est dans"], ["not_in", "pas dans"],
  ["contains", "contient"], ["not_contains", "ne contient pas"],
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

const state = { rules: [], templates: null };

function _genId() { return "rule_" + Math.random().toString(36).slice(2, 10); }

function _normalizeRule(r) {
  const out = {
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
  if (!out.conditions.length) out.conditions.push({ field: "video_codec", op: "=", value: "" });
  return out;
}

function _fieldOptsHtml(sel) {
  return FIELD_GROUPS.map(g => {
    const opts = g.options.map(([v, l]) =>
      `<option value="${escapeHtml(v)}"${v === sel ? " selected" : ""}>${escapeHtml(l)}</option>`).join("");
    return `<optgroup label="${escapeHtml(g.label)}">${opts}</optgroup>`;
  }).join("");
}

function _opOptsHtml(sel) {
  return OPERATORS.map(([v, l]) =>
    `<option value="${escapeHtml(v)}"${v === sel ? " selected" : ""}>${escapeHtml(l)}</option>`).join("");
}

function _actOptsHtml(sel) {
  return ACTION_TYPES.map(([v, l]) =>
    `<option value="${escapeHtml(v)}"${v === sel ? " selected" : ""}>${escapeHtml(l)}</option>`).join("");
}

function _fmtValue(v) {
  if (Array.isArray(v)) return v.join(",");
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v == null ? "" : v);
}

function _parseValue(raw, op) {
  const s = String(raw || "").trim();
  if (!s) return "";
  if (op === "between") return s.split(",").map(x => x.trim()).filter(Boolean).map(x => Number.isFinite(+x) ? +x : x);
  if (op === "in" || op === "not_in") return s.split(",").map(x => x.trim()).filter(Boolean);
  if (s === "true") return true;
  if (s === "false") return false;
  if (/^-?\d+(\.\d+)?$/.test(s) && Number.isFinite(+s)) return +s;
  return s;
}

function _condRowHtml(ruleId, c, idx) {
  const val = _fmtValue(c.value);
  return `
  <div class="rule-condition" data-rule-id="${escapeHtml(ruleId)}" data-cond-idx="${idx}">
    <select class="input" data-cond-field>${_fieldOptsHtml(c.field)}</select>
    <select class="input" data-cond-op>${_opOptsHtml(c.op)}</select>
    <input type="text" class="input rule-condition__value" data-cond-value value="${escapeHtml(val)}" placeholder="valeur (liste : a,b,c)" />
    <button type="button" class="btn btn--compact rule-condition__delete" data-action="delete-condition" title="Supprimer">✕</button>
  </div>`;
}

function _ruleCardHtml(r) {
  const conds = r.conditions.map((c, i) => _condRowHtml(r.id, c, i)).join("");
  const off = r.enabled ? "" : " rule-card--disabled";
  return `
  <article class="rule-card${off}" data-rule-id="${escapeHtml(r.id)}">
    <header class="rule-card__header">
      <label class="rule-toggle"><input type="checkbox" data-rule-enabled${r.enabled ? " checked" : ""}/><span class="rule-toggle__label">${r.enabled ? "Actif" : "Désactivé"}</span></label>
      <input type="text" class="input rule-card__name" data-rule-name value="${escapeHtml(r.name)}" placeholder="Nom de la règle" />
      <label class="rule-card__priority"><span>Prio</span><input type="number" min="0" max="999" class="input" data-rule-priority value="${escapeHtml(r.priority)}"/></label>
      <button type="button" class="btn btn--compact" data-action="move-up">↑</button>
      <button type="button" class="btn btn--compact" data-action="move-down">↓</button>
      <button type="button" class="btn btn--compact rule-card__delete" data-action="delete-rule">✕</button>
    </header>
    <section class="rule-card__body">
      <div class="rule-conditions">
        <div class="rule-conditions__header">
          <span class="rule-kw">SI</span>
          <select class="input" data-rule-match>
            <option value="all"${r.match === "all" ? " selected" : ""}>toutes les conditions</option>
            <option value="any"${r.match === "any" ? " selected" : ""}>au moins une condition</option>
          </select>
          <span class="text-muted">se vérifient :</span>
        </div>
        <div class="rule-conditions__list" data-conditions-list>${conds}</div>
        <button type="button" class="btn btn--compact" data-action="add-condition">+ Condition</button>
      </div>
      <div class="rule-action">
        <span class="rule-kw">ALORS</span>
        <select class="input" data-action-type>${_actOptsHtml(r.action.type)}</select>
        <input type="text" class="input rule-action__value" data-action-value value="${escapeHtml(_fmtValue(r.action.value))}" placeholder="Valeur" />
        <input type="text" class="input rule-action__reason" data-action-reason value="${escapeHtml(r.action.reason)}" placeholder="Raison (optionnel)" />
      </div>
    </section>
  </article>`;
}

function _buildBody() {
  return `
  <div class="rules-editor">
    <p class="text-muted">Règles conditionnelles qui complètent les pondérations. Appliquées dans l'ordre de priorité.</p>
    <div class="rules-templates flex gap-2 items-center" style="flex-wrap:wrap;margin:var(--sp-2) 0">
      <span class="text-muted">Templates :</span>
      <button type="button" class="btn btn--compact" data-rule-template="trash_like">📋 TRaSH-like</button>
      <button type="button" class="btn btn--compact" data-rule-template="purist">🎯 Puriste</button>
      <button type="button" class="btn btn--compact" data-rule-template="casual">🪶 Casual</button>
      <span class="text-muted">|</span>
      <button type="button" class="btn btn--compact" id="btnRulesImport">📥 Importer JSON</button>
      <input type="file" id="rulesImportInput" accept=".json,application/json" hidden />
      <button type="button" class="btn btn--compact" id="btnRulesExport">📤 Exporter JSON</button>
    </div>
    <div id="customRulesList" class="rules-list" aria-live="polite"></div>
    <div class="rules-actions flex gap-2 items-center" style="flex-wrap:wrap;margin-top:var(--sp-3)">
      <button type="button" class="btn btn--compact btn-primary" id="btnRuleAdd">+ Ajouter une règle</button>
      <div class="flex-1"></div>
      <span class="text-muted" id="rulesCount">0 règle(s)</span>
      <button type="button" class="btn btn--compact" id="btnRulesPreviewImpact">🎛 Simuler l'impact</button>
    </div>
    <p id="rulesMsg" class="text-muted" style="margin-top:var(--sp-2)"></p>
  </div>`;
}

function _findRule(id) { return state.rules.find(r => r.id === id); }

function _gatherRuleFromDom(card) {
  const id = card.getAttribute("data-rule-id");
  const r = _findRule(id);
  if (!r) return;
  r.enabled = !!card.querySelector("[data-rule-enabled]").checked;
  r.name = card.querySelector("[data-rule-name]").value || "Règle sans nom";
  r.priority = +card.querySelector("[data-rule-priority]").value || 0;
  r.match = card.querySelector("[data-rule-match]").value === "any" ? "any" : "all";
  r.conditions = Array.from(card.querySelectorAll(".rule-condition")).map(row => ({
    field: row.querySelector("[data-cond-field]").value,
    op: row.querySelector("[data-cond-op]").value,
    value: _parseValue(row.querySelector("[data-cond-value]").value, row.querySelector("[data-cond-op]").value),
  }));
  r.action = {
    type: card.querySelector("[data-action-type]").value,
    value: _parseValue(card.querySelector("[data-action-value]").value, "="),
    reason: card.querySelector("[data-action-reason]").value || "",
  };
}

function _gatherAll() {
  document.querySelectorAll("#customRulesList .rule-card").forEach(_gatherRuleFromDom);
  return state.rules.map(r => ({ ...r }));
}

function _renderList() {
  const host = document.getElementById("customRulesList");
  if (!host) return;
  const sorted = [...state.rules].sort((a, b) => a.priority - b.priority);
  host.innerHTML = sorted.length
    ? sorted.map(_ruleCardHtml).join("")
    : `<p class="text-muted" style="text-align:center;padding:var(--sp-4)">Aucune règle. Chargez un template ou ajoutez-en une.</p>`;
  const count = document.getElementById("rulesCount");
  if (count) count.textContent = `${state.rules.length} règle(s)`;
}

function _setMsg(text, level) {
  const el = document.getElementById("rulesMsg");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = level === "error" ? "var(--danger)" : level === "success" ? "var(--success)" : "var(--text-muted)";
}

async function _loadTemplates() {
  if (state.templates) return state.templates;
  try {
    const res = await apiPost("get_custom_rules_templates");
    state.templates = (res && res.templates) || [];
  } catch { state.templates = []; }
  return state.templates;
}

async function _applyTemplate(tid) {
  await _loadTemplates();
  const tpl = (state.templates || []).find(t => t.id === tid);
  if (!tpl) return;
  if (state.rules.length && !confirm(`Charger le template "${tpl.name}" ? Les règles actuelles seront remplacées.`)) return;
  state.rules = (tpl.rules || []).map(r => _normalizeRule({ ...r, id: _genId() }));
  _renderList();
  _setMsg(`Template "${tpl.name}" chargé (${state.rules.length} règles).`, "success");
}

function _exportJson() {
  const payload = JSON.stringify(_gatherAll(), null, 2);
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
      if (!Array.isArray(parsed)) throw new Error("JSON doit être un tableau");
      state.rules = parsed.map(r => _normalizeRule({ ...r, id: r.id || _genId() }));
      _renderList();
      _setMsg(`${state.rules.length} règles importées.`, "success");
    } catch (e) { _setMsg("Import échoué : " + (e.message || e), "error"); }
  };
  reader.readAsText(file);
}

async function _saveRules() {
  const rules = _gatherAll();
  const v = await apiPost("validate_custom_rules", { rules });
  if (!v || !v.ok) { _setMsg("Règles invalides : " + ((v && v.errors) || []).join(" ; "), "error"); return; }
  const profRes = await apiPost("get_quality_profile");
  if (!profRes || !profRes.ok) { _setMsg("Profil qualité introuvable.", "error"); return; }
  const profile = profRes.profile_json || {};
  profile.custom_rules = v.normalized || rules;
  const save = await apiPost("save_quality_profile", { profile_json: profile });
  if (!save || !save.ok) { _setMsg("Sauvegarde impossible.", "error"); return; }
  _setMsg(`${rules.length} règles enregistrées.`, "success");
}

function _addRule() {
  const maxPrio = state.rules.length ? Math.max(...state.rules.map(r => r.priority)) : 0;
  state.rules.push(_normalizeRule({
    id: _genId(), name: "Nouvelle règle", priority: maxPrio + 10,
    conditions: [{ field: "video_codec", op: "=", value: "" }],
    action: { type: "score_delta", value: 0, reason: "" },
  }));
  _renderList();
}

function _deleteRule(id) {
  state.rules = state.rules.filter(r => r.id !== id);
  _renderList();
}

function _moveRule(id, dir) {
  _gatherAll();
  const sorted = [...state.rules].sort((a, b) => a.priority - b.priority);
  const idx = sorted.findIndex(r => r.id === id);
  const swap = dir === "up" ? idx - 1 : idx + 1;
  if (swap < 0 || swap >= sorted.length) return;
  const tmp = sorted[idx].priority;
  sorted[idx].priority = sorted[swap].priority;
  sorted[swap].priority = tmp;
  _renderList();
}

function _addCondition(id) {
  _gatherAll();
  const r = _findRule(id);
  if (r) { r.conditions.push({ field: "video_codec", op: "=", value: "" }); _renderList(); }
}

function _deleteCondition(id, idx) {
  _gatherAll();
  const r = _findRule(id);
  if (!r) return;
  r.conditions.splice(idx, 1);
  if (!r.conditions.length) r.conditions.push({ field: "video_codec", op: "=", value: "" });
  _renderList();
}

function _previewImpact() {
  _gatherAll();
  if (!state.rules.length) return;
  closeModal();
  openQualitySimulator("latest", { custom_rules: state.rules });
}

function _hook() {
  const host = document.querySelector(".modal-card");
  if (!host) return;

  host.addEventListener("click", (ev) => {
    const tplBtn = ev.target.closest("[data-rule-template]");
    if (tplBtn) { _applyTemplate(tplBtn.getAttribute("data-rule-template")); return; }

    const t = ev.target.closest("[data-action]");
    if (t) {
      const action = t.getAttribute("data-action");
      const card = t.closest(".rule-card");
      const ruleId = card ? card.getAttribute("data-rule-id") : null;
      if (action === "delete-rule" && ruleId) return _deleteRule(ruleId);
      if (action === "move-up" && ruleId) return _moveRule(ruleId, "up");
      if (action === "move-down" && ruleId) return _moveRule(ruleId, "down");
      if (action === "add-condition" && ruleId) return _addCondition(ruleId);
      if (action === "delete-condition" && ruleId) {
        const row = t.closest(".rule-condition");
        if (row) _deleteCondition(ruleId, +row.getAttribute("data-cond-idx"));
        return;
      }
    }

    if (ev.target.id === "btnRuleAdd") return _addRule();
    if (ev.target.id === "btnRulesExport") return _exportJson();
    if (ev.target.id === "btnRulesImport") { document.getElementById("rulesImportInput").click(); return; }
    if (ev.target.id === "btnRulesPreviewImpact") return _previewImpact();
  });

  const file = document.getElementById("rulesImportInput");
  if (file) {
    file.addEventListener("change", () => {
      const f = file.files && file.files[0];
      if (f) _importJson(f);
      file.value = "";
    });
  }
}

export async function openCustomRulesEditor() {
  state.rules = [];
  try {
    const profRes = await apiPost("get_quality_profile");
    const profile = (profRes && profRes.profile_json) || {};
    state.rules = (profile.custom_rules || []).map(r => _normalizeRule({ ...r, id: r.id || _genId() }));
  } catch {
    state.rules = [];
  }

  showModal({
    title: "Règles personnalisées (G6)",
    body: _buildBody(),
    actions: [
      { label: "Annuler", cls: "", onClick: () => closeModal() },
      { label: "💾 Enregistrer", cls: "btn-primary", onClick: _saveRules },
    ],
  });

  _renderList();
  _hook();
}
