/* components/badge.js — Badges tier et confiance CinemaLux */

import { escapeHtml } from "../core/dom.js";

/* Mapping tier → classe CSS + label (U1 audit, migration 011 : 5 tiers).
   Reutilise les classes existantes badge-success/info/warning/danger. Les anciens
   noms restent acceptes en entree pour compatibilite avec les rapports persistes
   avant la migration. */
const _TIER_MAP = {
  platinum: { cls: "badge-success", label: "Platinum" },
  gold:     { cls: "badge-warning", label: "Gold" },
  silver:   { cls: "badge-info",    label: "Silver" },
  bronze:   { cls: "badge-warning", label: "Bronze" },
  reject:   { cls: "badge-danger",  label: "Reject" },
  // Alias retro-compat (rapports anterieurs a la migration 011)
  premium:  { cls: "badge-success", label: "Platinum" },
  bon:      { cls: "badge-warning", label: "Gold" },
  moyen:    { cls: "badge-info",    label: "Silver" },
  faible:   { cls: "badge-warning", label: "Bronze" },
  mauvais:  { cls: "badge-danger",  label: "Reject" },
};

/* Mapping confiance → classe CSS + label */
const _CONFIDENCE_MAP = {
  high: { cls: "badge-success", label: "High" },
  med:  { cls: "badge-warning", label: "Med" },
  low:  { cls: "badge-danger",  label: "Low" },
};

/* Mapping statut run → classe CSS + label */
const _STATUS_MAP = {
  ok:        { cls: "badge-success", label: "OK" },
  done:      { cls: "badge-success", label: "Termine" },
  running:   { cls: "badge-info",    label: "En cours" },
  error:     { cls: "badge-danger",  label: "Erreur" },
  cancelled: { cls: "badge-warning", label: "Annule" },
};

/**
 * Genere un badge HTML.
 * @param {"tier"|"confidence"|"status"} type
 * @param {string} value - ex: "premium", "high", "ok"
 * @returns {string} HTML
 */
export function badgeHtml(type, value) {
  const key = String(value || "").toLowerCase().trim();
  let mapping;

  if (type === "tier") mapping = _TIER_MAP;
  else if (type === "confidence") mapping = _CONFIDENCE_MAP;
  else if (type === "status") mapping = _STATUS_MAP;
  else mapping = {};

  const entry = mapping[key];
  if (entry) {
    return `<span class="badge ${entry.cls}">${escapeHtml(entry.label)}</span>`;
  }
  // Fallback : badge neutre avec la valeur brute
  return `<span class="badge">${escapeHtml(value || "—")}</span>`;
}

/**
 * Genere un badge pour un score qualite (couleur par tier).
 * @param {number} score
 * @returns {string} HTML
 */
export function scoreBadgeHtml(score) {
  const s = Number(score) || 0;
  let tier;
  if (s >= 85) tier = "premium";
  else if (s >= 68) tier = "bon";
  else if (s >= 54) tier = "moyen";
  else tier = "mauvais";
  return badgeHtml("tier", tier);
}

/* P3.2 : tierPill — pastille visuelle dot + texte cohérente avec desktop. */
const _TIER_PILL_COLORS = {
  platinum: "#A78BFA", premium: "#A78BFA",
  gold: "#FBBF24", bon: "#FBBF24",
  silver: "#9CA3AF", moyen: "#9CA3AF",
  bronze: "#FB923C",
  reject: "#EF4444", mauvais: "#EF4444",
};

const _TIER_PILL_LABELS = {
  platinum: "Platinum", premium: "Platinum",
  gold: "Gold", bon: "Gold",
  silver: "Silver", moyen: "Silver",
  bronze: "Bronze",
  reject: "Reject", mauvais: "Reject",
};

/**
 * Retourne HTML d'une pastille tier (dot + texte) avec couleur dédiée.
 * @param {string} tier
 * @param {object} [opts] - {compact: bool}
 */
export function tierPill(tier, opts) {
  const t = String(tier || "").trim().toLowerCase();
  const color = _TIER_PILL_COLORS[t] || "var(--text-muted)";
  const label = _TIER_PILL_LABELS[t] || String(tier || "?");
  const compact = opts && opts.compact;
  const sizing = compact
    ? "padding:2px 8px; font-size:var(--fs-xs); border-radius:10px"
    : "padding:3px 10px; font-size:var(--fs-sm); border-radius:14px";
  const dot = `<span style="display:inline-block; width:7px; height:7px; border-radius:50%; background:${color}; margin-right:6px; box-shadow:0 0 0 2px ${color}33"></span>`;
  return `<span class="tier-pill" style="display:inline-flex; align-items:center; font-weight:600; background:${color}22; border:1px solid ${color}55; color:${color}; ${sizing}">${dot}${escapeHtml(label)}</span>`;
}

/** Score + tier pill combinés. */
export function scoreTierPill(score, tier, opts) {
  const s = (score != null && score !== "") ? Math.round(Number(score)) : null;
  const head = s != null ? `<span style="font-weight:700; margin-right:6px">${s}</span>` : "";
  return `<span style="display:inline-flex; align-items:center">${head}${tierPill(tier, opts)}</span>`;
}
