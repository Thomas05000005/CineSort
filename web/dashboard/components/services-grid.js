/* components/services-grid.js — Grille 2x2 des services connectes (Jellyfin/Plex/Radarr/TMDb).
 *
 * Reutilise les classes .services-grid / .service-tile de depth-effects.css.
 *
 * Usage :
 *   import { servicesGridHtml } from "../components/services-grid.js";
 *   container.innerHTML = servicesGridHtml([
 *     { name: "Jellyfin", initial: "J", avatar_bg: "#00A4DC", avatar_fg: "#fff",
 *       label: "Jellyfin", subtitle: "En ligne — 24ms", status: "on" },
 *     ...
 *   ]);
 */

import { escapeHtml } from "../core/dom.js";

/**
 * @typedef {Object} ServiceTile
 * @property {string} name      - nom complet
 * @property {string} [initial] - lettre(s) de l'avatar (defaut: premiere du nom)
 * @property {string} [avatar_bg] - couleur de fond avatar
 * @property {string} [avatar_fg] - couleur du texte avatar
 * @property {string} [label]   - titre affiche (defaut: name)
 * @property {string} [subtitle] - sous-titre (ex: "En ligne — 24ms")
 * @property {"on"|"off"|"warn"|"err"} [status] - statut du dot (defaut: off)
 * @property {string} [href]    - si present, tile devient un lien vers cette route
 */

/**
 * Rend la grille de services.
 * @param {ServiceTile[]} services
 * @returns {string} HTML
 */
export function servicesGridHtml(services) {
  if (!Array.isArray(services) || services.length === 0) {
    return `<p class="text-muted">Aucun service configure.</p>`;
  }
  const tiles = services.map((s) => {
    const initial = escapeHtml(s.initial || (s.name ? s.name[0] : "?"));
    const name = escapeHtml(s.label || s.name || "");
    const subtitle = escapeHtml(s.subtitle || "");
    const status = ["on", "off", "warn", "err"].includes(s.status) ? s.status : "off";
    const avatarStyle = [];
    if (s.avatar_bg) avatarStyle.push(`background:${escapeHtml(s.avatar_bg)}`);
    if (s.avatar_fg) avatarStyle.push(`color:${escapeHtml(s.avatar_fg)}`);
    const styleAttr = avatarStyle.length ? ` style="${avatarStyle.join(";")}"` : "";
    const tag = s.href ? "a" : "div";
    const hrefAttr = s.href ? ` href="${escapeHtml(s.href)}" data-nav-route="${escapeHtml(s.href)}"` : "";
    return `<${tag} class="service-tile"${hrefAttr}>
      <div class="service-avatar"${styleAttr}>${initial}</div>
      <div class="service-info">
        <div class="n">${name}</div>
        <div class="s">${subtitle}</div>
      </div>
      <span class="service-status-dot ${status}" aria-label="statut ${status}"></span>
    </${tag}>`;
  }).join("");
  return `<div class="services-grid">${tiles}</div>`;
}
