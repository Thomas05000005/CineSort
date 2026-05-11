/* V3-03 — Tooltip glossaire metier reutilisable.
 * Genere une icone (i) cliquable avec popover de definition pour les termes
 * techniques affiches dans le dashboard (LPIPS, HDR10+, perceptual hash, etc.). */

import { escapeHtml } from "../core/dom.js";

/**
 * Glossaire centralise. Cle = terme tel qu'affiche dans l'UI.
 * Valeur = definition courte (1-3 phrases) en francais.
 */
export const GLOSSARY = {
  "LPIPS": "Learned Perceptual Image Patch Similarity. Metrique IA qui compare 2 images comme un humain (difference percue, pas pixel-par-pixel). Utilisee pour detecter les re-encodages degrades.",
  "Perceptual hash": "Empreinte numerique d'une image basee sur son contenu visuel (pas le contenu binaire). 2 fichiers identiques visuellement ont des perceptual hashes proches meme si encodage different.",
  "Chromaprint": "Empreinte audio (audio fingerprint). Identifie une bande son independamment de la qualite audio. Utilise pour detecter les doublons.",
  "HDR10+": "Format HDR avec metadonnees dynamiques scene par scene. Plus precis que HDR10 statique. Detecte via SMPTE ST 2094-40.",
  "Dolby Vision": "Format HDR proprietaire de Dolby. 4 profils principaux : 5 (TV), 7 (Blu-ray dual layer), 8.1 (single track), 8.2.",
  "Bitrate": "Quantite de donnees par seconde de video (en kbps). Plus eleve = meilleure qualite, mais aussi gros fichier. 10 Mbps est typique pour 1080p HEVC.",
  "Banding": "Bandes de couleur visibles dans les degrades (ciel, ombres). Indique compression agressive ou bit depth insuffisant.",
  "Tier": "Categorie de qualite (Premium, Bon, Moyen, Mauvais). Calculee a partir des scores video + audio + metadonnees.",
  "Score perceptuel": "Note de qualite visuelle/audio basee sur l'analyse reelle du fichier (pas juste les metadonnees). Sur 100. >= 85 = excellent.",
  "Re-encode degrade": "Fichier qui a ete re-encode avec un bitrate trop bas pour sa resolution. Perte de qualite visible.",
  "Upscale suspect": "Video dont la resolution annoncee (ex. 1080p) est superieure a sa resolution reelle (ex. 480p upscale). Le fichier est plus gros pour rien.",
  "Faux 4K": "Fichier annonce 4K mais qui contient en realite de l'image 1080p ou moins, simplement upscalee. Detecte par analyse FFT.",
  "Run": "Une execution complete d'un scan + analyse + apply. Stocke en BDD pour historique.",
  "Apply": "Application physique des renommages/deplacements proposes. C'est l'etape qui modifie reellement les fichiers.",
  "Dry-run": "Simulation sans modification du disque. Permet de previsualiser avant de committer.",
  "Roots": "Dossiers racine ou chercher les films. Tu peux en avoir plusieurs (SSD + NAS + disque externe).",
  "TMDb": "The Movie Database. Base de donnees mondiale de films open. Source principale des metadonnees (titre, annee, posters, sagas).",
  "NFO": "Fichier XML qui accompagne un film, contient les metadonnees (titre, annee, IMDb ID). Standard Kodi/Jellyfin/Plex.",
};

/**
 * Genere le HTML d'un tooltip glossaire pour un terme donne.
 * Si le terme n'a pas de definition, retourne juste le label echappe.
 * @param {string} term - Le terme tel qu'affiche (cle GLOSSARY).
 * @param {string} [labelOverride] - Si different du terme, utilise pour l'affichage du libelle.
 * @returns {string} HTML pret a injecter (deja echappe).
 */
export function glossaryTooltip(term, labelOverride = null) {
  const def = GLOSSARY[term];
  const label = labelOverride || term;
  if (!def) return escapeHtml(label);
  return `<span class="glossary-term">${escapeHtml(label)}<button type="button" class="glossary-info" tabindex="0" aria-label="Definition de ${escapeHtml(term)}" data-term="${escapeHtml(term)}" data-tooltip="${escapeHtml(def)}">&#9432;</button></span>`;
}

/**
 * Init listener global (a appeler au boot du dashboard).
 * Affiche un popover au clic sur .glossary-info, fermeture au clic exterieur ou Escape.
 */
export function initGlossaryTooltips() {
  let activePopover = null;

  function closePopover() {
    if (activePopover) {
      activePopover.remove();
      activePopover = null;
    }
  }

  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".glossary-info");
    if (!btn) {
      // Clic en dehors d'un bouton glossaire : fermer popover ouvert
      if (activePopover && !ev.target.closest(".glossary-popover")) closePopover();
      return;
    }
    ev.preventDefault();
    ev.stopPropagation();

    // Si popover deja ouvert pour ce bouton : toggle off
    if (activePopover && activePopover.dataset.term === btn.dataset.term) {
      closePopover();
      return;
    }
    closePopover();

    const def = btn.dataset.tooltip || "";
    const term = btn.dataset.term || "";
    const popover = document.createElement("div");
    popover.className = "glossary-popover";
    popover.setAttribute("role", "tooltip");
    popover.dataset.term = term;
    popover.innerHTML = `<strong>${escapeHtml(term)}</strong><p>${escapeHtml(def)}</p>`;
    document.body.appendChild(popover);
    activePopover = popover;

    const r = btn.getBoundingClientRect();
    popover.style.position = "fixed";
    popover.style.left = `${Math.min(r.left, window.innerWidth - 340)}px`;
    popover.style.top = `${r.bottom + 6}px`;
  });

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closePopover();
  });
}
