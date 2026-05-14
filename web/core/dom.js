/* core/dom.js — DOM helpers (single source of truth) */

function $(id) { return document.getElementById(id); }
function qsa(sel) { return Array.from(document.querySelectorAll(sel)); }

function esc(s) {
  const d = document.createElement("span");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

/** HTML entity escape — safe for innerHTML injection (couvre &, <, >, ", '). */
function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/**
 * Cf issue #67/#93 : valide qu'une URL utilise un scheme autorise (http/https/data:image)
 * avant injection dans un attribut src="" ou style="url(...)". Retourne chaine vide
 * si invalide — le caller doit gerer le fallback (placeholder vide).
 */
function safeUrl(u) {
  const s = String(u ?? "").trim();
  if (!s) return "";
  try {
    const parsed = new URL(s, window.location.href);
    const proto = parsed.protocol.toLowerCase();
    if (proto === "http:" || proto === "https:") return escapeHtml(s);
    if (proto === "data:" && s.toLowerCase().startsWith("data:image/")) return escapeHtml(s);
    return "";
  } catch {
    return "";
  }
}

/**
 * Tag template litteral securise contre XSS : echappe toutes les interpolations
 * par defaut, sauf si la valeur est marquee via rawHtml(). Usage :
 *
 *   el.innerHTML = safeHtml`<div>${userInput}</div>`;
 *   el.innerHTML = safeHtml`<tr>${rawHtml(builtRowHtml)}</tr>`;
 *
 * Preserve l'ergonomie des template literals tout en fermant la porte aux oublis
 * d'escapeHtml() dans les 200+ sites innerHTML du projet (voir AUDIT_20260422 F3).
 */
const _RAW_MARK = Symbol("cs.rawHtml");

function rawHtml(htmlString) {
  return { [_RAW_MARK]: true, html: String(htmlString ?? "") };
}

function safeHtml(strings, ...values) {
  let out = "";
  for (let i = 0; i < strings.length; i += 1) {
    out += strings[i];
    if (i < values.length) {
      const v = values[i];
      if (v && typeof v === "object" && v[_RAW_MARK]) {
        out += v.html;
      } else if (Array.isArray(v)) {
        // Les tableaux sont concatenes : chaque element passe par le meme traitement.
        for (const item of v) {
          if (item && typeof item === "object" && item[_RAW_MARK]) {
            out += item.html;
          } else {
            out += escapeHtml(item);
          }
        }
      } else {
        out += escapeHtml(v);
      }
    }
  }
  return out;
}

function setPill(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

/** Truncate long paths with ellipsis in the middle. */
function shortPath(path, maxLen) {
  const s = String(path || "");
  const n = Number(maxLen || 80);
  if (s.length <= n) return s;
  const half = Math.floor((n - 3) / 2);
  return s.slice(0, half) + "..." + s.slice(s.length - half);
}

/** Safe clipboard copy. */
function copyTextSafe(text) {
  const val = String(text || "").trim();
  if (!val) return false;
  if (navigator?.clipboard?.writeText) {
    navigator.clipboard.writeText(val).catch(() => {});
    return true;
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = val;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    return true;
  } catch (_e) {
    return false;
  }
}

/** LocalStorage helpers (silent on errors). */
function getStoredText(key) {
  try { return String(localStorage.getItem(key) || ""); }
  catch (_e) { return ""; }
}

function setStoredText(key, value) {
  try {
    if (value === undefined || value === null || String(value) === "") {
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(key, String(value));
    }
  } catch (_e) { /* no-op */ }
}

/** Append log lines to a logbox element. */
function appendLogs(targetId, logs) {
  if (!Array.isArray(logs) || !logs.length) return;
  const el = $(targetId);
  if (!el) return;
  const lines = logs.map(e => {
    if (typeof e === "string") return e;
    if (e && typeof e === "object") return `[${e.ts || ""}] ${e.level || "INFO"}: ${e.msg || e.message || ""}`;
    return String(e);
  });
  el.textContent += lines.join("\n") + "\n";
  el.scrollTop = el.scrollHeight;
}
