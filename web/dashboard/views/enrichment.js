/* views/enrichment.js — Scaffold V4.1 enrichissement IA (Ollama)
 *
 * Vue dediee aux suggestions d'enrichissement generees par LLM local :
 *  - Synopsis FR genere (3-5 phrases)
 *  - Tags semantiques (ambiance, sous-genres, tropes)
 *
 * Strategie scaffold : tant que le feature flag ai_enrichment est OFF
 * cote backend (cf cinesort/app/enrichment_facade.py), la vue affiche
 * une bannière "fonctionnalite en preparation" + l'etat de detection
 * Ollama (introspection only, pas de generation reelle).
 *
 * Badge "IA generated" :
 *  - Visible orange (couleur invariante non liee aux tier hex
 *    Gold/Silver/Bronze/Platinum) chaque fois que ai_generated === true
 *    dans une reponse facade. Distingue VISUELLEMENT le contenu humain
 *    du contenu LLM, requis pour la transparence editoriale.
 *
 * Actions dangereuses (memoire feedback-cinesort-actions-dangereuses) :
 *  - "Appliquer toutes les suggestions IA" passe par dangerConfirmModal
 *    avec liste des films touches + consequence + delai 3s si >50 elements.
 *
 * Endpoints consommes (a cabler en V4.1 runtime, pas encore exposes) :
 *   enrichment/get_status()               -> { feature_flag, ollama_available, model, endpoint }
 *   enrichment/enrichment_for_film(id)    -> { ok, ai_generated, synopsis, tags, model }
 *   enrichment/apply_bulk(film_ids)       -> { applied: N, skipped: N }
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { dangerConfirmModal } from "../components/modal.js";
import { showToast } from "../components/toast.js";

const STYLE_ID = "enrichmentViewStyle";
const STYLE_CSS = `
  .enrichment-view { padding: 16px; }
  .enrichment-view__header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .enrichment-view__header h1 { margin: 0; font-size: 1.25em; }
  .enrichment-banner { padding: 12px 16px; border-radius: 8px; background: rgba(255, 165, 0, 0.08); border: 1px solid rgba(255, 165, 0, 0.35); margin-bottom: 16px; }
  .enrichment-banner__title { margin: 0 0 4px 0; font-weight: 600; color: #FFA500; }
  .enrichment-banner__body { margin: 0; color: var(--text-muted, #9aa0a6); font-size: 0.95em; }
  .enrichment-status { display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; padding: 12px 16px; background: rgba(0,0,0,0.18); border-radius: 8px; border: 1px solid var(--border, rgba(255,255,255,0.08)); margin-bottom: 16px; }
  .enrichment-status dt { font-weight: 600; color: var(--text-muted, #9aa0a6); }
  .enrichment-status dd { margin: 0; font-family: var(--font-mono, "Cascadia Code", Menlo, monospace); }
  .ai-badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px; font-size: 0.75em; font-weight: 600; background: rgba(255, 140, 0, 0.18); color: #FF8C00; border: 1px solid rgba(255, 140, 0, 0.45); white-space: nowrap; }
  .ai-badge::before { content: "IA"; display: inline-block; font-size: 0.7em; font-weight: 700; letter-spacing: 0.05em; }
  .enrichment-actions { display: flex; gap: 8px; margin-top: 12px; }
  .enrichment-actions button { padding: 8px 14px; border-radius: 6px; cursor: pointer; }
  .enrichment-actions button[disabled] { opacity: 0.5; cursor: not-allowed; }
`;

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = STYLE_CSS;
  document.head.appendChild(style);
}

/**
 * Rend le badge "IA generated" visible orange chaque fois qu'un payload
 * facade contient ai_generated === true. Helper exporte pour reutilisation
 * dans film-detail.js et bibliotheque.js lors de la phase runtime.
 *
 * @param {boolean} aiGenerated
 * @returns {string} HTML du badge ou chaine vide
 */
export function renderAiBadge(aiGenerated) {
  if (!aiGenerated) return "";
  return ` <span class="ai-badge" title="Contenu genere par IA locale (Ollama)"> generated</span>`;
}

/**
 * Recupere l'etat de la feature ai_enrichment (introspection).
 * Fallback gracieux si l'endpoint n'existe pas encore (404 -> degraded).
 */
async function fetchEnrichmentStatus() {
  try {
    const res = await apiPost("enrichment/get_status", {});
    return res || { feature_flag: false, ollama_available: false };
  } catch (err) {
    return { feature_flag: false, ollama_available: false, error: String(err) };
  }
}

function renderStatus(status) {
  const flag = status.feature_flag ? "ON" : "OFF";
  const ollama = status.ollama_available ? "detecte" : "indisponible";
  return `
    <dl class="enrichment-status">
      <dt>Feature flag</dt><dd>${escapeHtml(flag)}</dd>
      <dt>Ollama</dt><dd>${escapeHtml(ollama)}</dd>
      <dt>Modele</dt><dd>${escapeHtml(status.model || "-")}</dd>
      <dt>Endpoint</dt><dd>${escapeHtml(status.endpoint || "-")}</dd>
    </dl>
  `;
}

/**
 * Handler du bouton "Appliquer toutes les suggestions IA" — action
 * destructive (ecrit du contenu LLM sur la BDD). Passe par
 * dangerConfirmModal avec :
 *  - liste des films touches (max 5 visibles + "et N autres")
 *  - consequence claire
 *  - countdown 3s si la liste depasse 50 elements
 */
export function confirmApplyAllSuggestions(filmTitles) {
  const items = Array.isArray(filmTitles) ? filmTitles : [];
  const count = items.length;
  const countdown = count > 50 ? 3 : 0;
  return dangerConfirmModal({
    title: `Appliquer les suggestions IA a ${count} film${count > 1 ? "s" : ""} ?`,
    items,
    consequence:
      "Les synopsis et tags generes par IA seront ecrits sur la fiche " +
      "des films selectionnes, remplacant tout contenu existant. Action " +
      "reversible via l'historique d'enrichment (V4.1).",
    countdownSeconds: countdown,
    confirmLabel: "Appliquer",
    cancelLabel: "Annuler",
    onConfirm: async () => {
      try {
        await apiPost("enrichment/apply_bulk", { film_ids: [] });
        showToast("Suggestions IA appliquees", "success");
      } catch (err) {
        showToast(`Echec : ${err}`, "error");
      }
    },
  });
}

/**
 * Entree principale de la vue. Conserve la signature standard des autres
 * views (renderXxx(container)) pour le router.
 */
export async function renderEnrichment(container) {
  ensureStyle();
  const root = container || document.getElementById("dashContent") || document.body;
  root.innerHTML = `
    <section class="enrichment-view" data-view="enrichment">
      <div class="enrichment-view__header">
        <h1>Enrichissement IA${renderAiBadge(true)}</h1>
      </div>
      <div class="enrichment-banner">
        <p class="enrichment-banner__title">Fonctionnalite en preparation (V4.1)</p>
        <p class="enrichment-banner__body">
          La generation de synopsis et tags via LLM local (Ollama) est
          actuellement desactivee. Cette page expose uniquement l'etat
          de detection. Lorsque la feature sera activee, tout contenu
          genere par IA sera marque par le badge orange ci-dessus.
        </p>
      </div>
      <div data-status-root>Chargement de l'etat Ollama...</div>
      <div class="enrichment-actions">
        <button type="button" data-action="apply-all" disabled
          title="Disponible une fois le feature flag ON">
          Appliquer toutes les suggestions IA
        </button>
      </div>
    </section>
  `;

  const status = await fetchEnrichmentStatus();
  const statusRoot = root.querySelector("[data-status-root]");
  if (statusRoot) statusRoot.innerHTML = renderStatus(status);

  const applyBtn = root.querySelector('button[data-action="apply-all"]');
  if (applyBtn && status.feature_flag && status.ollama_available) {
    applyBtn.disabled = false;
    applyBtn.addEventListener("click", () => {
      // Liste reelle a injecter par le caller lors de la phase runtime.
      confirmApplyAllSuggestions([]);
    });
  }
}

export default renderEnrichment;
