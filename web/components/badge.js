/* components/badge.js — Badge helpers */

/**
 * Set badge content and tone on an element.
 * @param {string} id   - element ID
 * @param {string} tone - ok|warn|bad|neutral|accent|info|high|med|low
 * @param {string} text - badge text
 */
function setBadge(id, tone, text) {
  const el = $(id);
  if (!el) return;
  el.className = `badge badge--${tone || "neutral"}`;
  el.textContent = String(text || "");
}

/** Return HTML string for a confidence badge. */
function badgeForConfidence(label) {
  const l = String(label || "").toLowerCase();
  if (l === "high") return '<span class="badge badge--high">High</span>';
  if (l === "med" || l === "medium") return '<span class="badge badge--med">Med</span>';
  return '<span class="badge badge--low">Low</span>';
}

/** Return HTML string for a severity badge. */
function severityBadge(severity) {
  const s = String(severity || "INFO").toUpperCase();
  if (s === "ERROR") return '<span class="badge badge--bad">ERROR</span>';
  if (s === "WARN") return '<span class="badge badge--warn">WARN</span>';
  return '<span class="badge badge--ok">INFO</span>';
}

/** Source label. */
function sourceLabel(source) {
  const s = String(source || "").toLowerCase();
  if (s === "nfo") return "NFO";
  if (s === "tmdb") return "TMDb";
  if (s === "name" || s === "folder") return "Nom";
  return String(source || "?");
}

/* --- P3.2 : tier pills (Platinum / Gold / Silver / Bronze / Reject) ---
 *
 * Une pastille cohérente utilisée partout où un tier est affiché.
 * Dot circulaire coloré à gauche + texte + background semi-transparent.
 * Respect des anciens noms (Premium/Bon/Moyen/Mauvais) pour rétrocompat.
 */

const _TIER_MAP = {
  platinum: { label: "Platinum", color: "#A78BFA", abbr: "PT" },
  premium:  { label: "Platinum", color: "#A78BFA", abbr: "PT" },  // legacy alias
  gold:     { label: "Gold",     color: "#FBBF24", abbr: "GO" },
  bon:      { label: "Gold",     color: "#FBBF24", abbr: "GO" },  // legacy
  silver:   { label: "Silver",   color: "#9CA3AF", abbr: "SI" },
  moyen:    { label: "Silver",   color: "#9CA3AF", abbr: "SI" },  // legacy
  bronze:   { label: "Bronze",   color: "#FB923C", abbr: "BR" },
  reject:   { label: "Reject",   color: "#EF4444", abbr: "RJ" },
  mauvais:  { label: "Reject",   color: "#EF4444", abbr: "RJ" },  // legacy
};

/**
 * Retourne le HTML d'une pastille tier visuelle (dot + texte).
 * @param {string} tier - Platinum|Gold|Silver|Bronze|Reject (ou alias legacy)
 * @param {object} [opts] - {compact: bool, showAbbr: bool}
 */
function tierPill(tier, opts) {
  const t = String(tier || "").trim().toLowerCase();
  const info = _TIER_MAP[t] || { label: String(tier || "?"), color: "var(--text-muted)", abbr: "??" };
  const compact = opts && opts.compact;
  const label = (opts && opts.showAbbr) ? info.abbr : info.label;
  const styleBg = `background:${info.color}22; border:1px solid ${info.color}55; color:${info.color}`;
  const sizing = compact
    ? "padding:.1em .5em; font-size:var(--fs-xs); border-radius:10px"
    : "padding:.25em .6em; font-size:var(--fs-sm); border-radius:14px";
  const dot = `<span class="tier-pill__dot" style="display:inline-block; width:.55em; height:.55em; border-radius:50%; background:${info.color}; margin-right:.4em; box-shadow:0 0 0 2px ${info.color}33"></span>`;
  return `<span class="tier-pill" style="display:inline-flex; align-items:center; font-weight:600; ${sizing}; ${styleBg}">${dot}${label}</span>`;
}

/** Score + tier pill combined : "82 [Gold]" style. */
function scoreTierPill(score, tier, opts) {
  const s = (score != null && score !== "") ? Number(score) : null;
  const scoreHtml = s != null ? `<span style="font-weight:700; margin-right:.4em">${Math.round(s)}</span>` : "";
  return `<span style="display:inline-flex; align-items:center">${scoreHtml}${tierPill(tier, opts)}</span>`;
}
