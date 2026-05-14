/* core/dom.js — Helpers DOM pour le dashboard distant */

/** Raccourci document.getElementById */
export function $(id) { return document.getElementById(id); }

/** Raccourci querySelectorAll → Array */
export function $$(sel) { return Array.from(document.querySelectorAll(sel)); }

/** Echappe les entites HTML pour eviter les injections XSS. */
export function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/**
 * Cf issue #67 : valide qu'une URL utilise un scheme autorise (http/https/data img)
 * avant injection dans un attribut src="" ou style="url(...)". Retourne chaine vide
 * si invalide — provoque un fallback safe cote appelant.
 */
export function safeUrl(u) {
  const s = String(u ?? "").trim();
  if (!s) return "";
  try {
    const parsed = new URL(s, window.location.href);
    const proto = parsed.protocol.toLowerCase();
    if (proto === "http:" || proto === "https:") return escapeHtml(s);
    // data: autorise UNIQUEMENT pour images (data:image/...)
    if (proto === "data:" && s.toLowerCase().startsWith("data:image/")) return escapeHtml(s);
    return "";
  } catch {
    return "";
  }
}

/**
 * V2-D (a11y) : bascule l'attribut aria-busy d'un conteneur ARIA-live.
 * Utilise en wrap des appels async (fetch / apiPost) sur les vues a polling
 * pour annoncer aux lecteurs d'ecran "chargement en cours" puis "termine".
 *
 * @param {string|HTMLElement} target - id ou element DOM cible.
 * @param {boolean} busy - true au debut du fetch, false apres reponse/erreur.
 */
export function setBusy(target, busy) {
  const elNode = typeof target === "string" ? document.getElementById(target) : target;
  if (!elNode || !elNode.setAttribute) return;
  elNode.setAttribute("aria-busy", busy ? "true" : "false");
}

/**
 * V2-D (a11y) : helper utilitaire pour wrapper un appel async avec
 * aria-busy automatique. Garantit que aria-busy retombe a false meme
 * en cas d'erreur (via try/finally).
 *
 * @param {string|HTMLElement} target - id ou element DOM cible.
 * @param {Function} fn - fonction async a executer.
 * @returns {Promise<*>} le resultat de fn.
 */
export async function withBusy(target, fn) {
  setBusy(target, true);
  try {
    return await fn();
  } finally {
    setBusy(target, false);
  }
}

/** Cree un element avec attributs et enfants optionnels. */
export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "className") e.className = v;
    else if (k === "textContent") e.textContent = v;
    else if (k === "innerHTML") e.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2).toLowerCase(), v);
    else e.setAttribute(k, v);
  }
  for (const child of children) {
    if (typeof child === "string") e.appendChild(document.createTextNode(child));
    else if (child instanceof Node) e.appendChild(child);
  }
  return e;
}
