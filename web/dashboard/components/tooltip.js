/* components/tooltip.js — Helper unifie pour les tooltips de la dashboard.
 *
 * mega-hotfix frontend_ui_polish (#3) : consolidation des 3 patterns
 * historiques de tooltip qui coexistaient sans coordination :
 *   1) `title="..."`           - tooltip natif du navigateur (rapide, mais
 *                                style non personnalisable, delai variable)
 *   2) `data-tooltip="..."`    - convention CSS attendue par certains
 *                                composants (mais aucune impl partagee)
 *   3) tooltip custom inline   - styles ad-hoc (cf glossary-tooltip,
 *                                shortcut-tooltip, auto-tooltip)
 *
 * Ce module ne supprime AUCUN pattern existant (backward compat ABSOLUE) :
 * - tooltipAttrs() retourne un objet `{title, "data-tooltip"}` pour
 *   garantir que TOUT consommateur (CSS natif OU CSS custom) trouve la valeur.
 * - tooltipHtml() retourne directement la chaine d'attributs HTML serialisee
 *   et echappee, utilisable telle quelle dans un template literal.
 *
 * Les composants specialises (glossary-tooltip, shortcut-tooltip,
 * auto-tooltip) continuent d'exister et conservent leur API. Ce helper sert
 * uniquement de point d'entree commun pour les NOUVEAUX usages et pour
 * normaliser progressivement les anciens.
 */

import { escapeHtml } from "../core/dom.js";

/**
 * Genere les attributs HTML necessaires pour un tooltip unifie.
 * Le texte est echappe une seule fois ici, NE PAS le re-echapper en aval.
 *
 * @param {string} text - contenu du tooltip
 * @returns {string} attributs HTML prets a injecter (ex: ' title="..." data-tooltip="..."')
 *                   Renvoie une chaine vide si `text` est vide.
 *
 * @example
 *   `<button${tooltipHtml("Annuler")}>X</button>`
 */
export function tooltipHtml(text) {
  const s = String(text == null ? "" : text).trim();
  if (!s) return "";
  const escaped = escapeHtml(s);
  // Espace de tete pour s'inserer proprement dans un template literal apres
  // un autre attribut sans collision.
  return ` title="${escaped}" data-tooltip="${escaped}"`;
}

/**
 * Variante objet : retourne `{title, "data-tooltip"}` pour les callers qui
 * construisent leurs attributs via dataset / setAttribute.
 *
 * @param {string} text
 * @returns {{title: string, "data-tooltip": string} | null}
 */
export function tooltipAttrs(text) {
  const s = String(text == null ? "" : text).trim();
  if (!s) return null;
  return { title: s, "data-tooltip": s };
}

/**
 * Applique un tooltip a un element DOM existant (idempotent).
 * Utile pour les composants qui construisent leur DOM via createElement
 * plutot que par template literal.
 *
 * @param {HTMLElement} el
 * @param {string} text
 */
export function setTooltip(el, text) {
  if (!el || !el.setAttribute) return;
  const s = String(text == null ? "" : text).trim();
  if (!s) {
    el.removeAttribute("title");
    el.removeAttribute("data-tooltip");
    return;
  }
  el.setAttribute("title", s);
  el.setAttribute("data-tooltip", s);
}
