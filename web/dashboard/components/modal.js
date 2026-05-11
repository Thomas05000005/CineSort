/* components/modal.js — Modale reutilisable pour le dashboard */

import { $, escapeHtml } from "../core/dom.js";

const MODAL_CONTAINER_ID = "dashModal";

// V2-D (a11y) : selecteur des elements focusables a l'interieur d'une modale.
// Utilise par trapFocus() pour capturer Tab / Shift+Tab.
const _FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * V2-D (WCAG 2.1.2 Focus Trap) : capture Tab / Shift+Tab dans la modale.
 * - Tab sur le dernier element focusable -> focus sur le premier.
 * - Shift+Tab sur le premier element focusable -> focus sur le dernier.
 * - Si aucun element focusable, le keydown est bloque pour eviter de "fuir" la modale.
 *
 * @param {HTMLElement} modalEl - element racine de la modale (l'overlay).
 * @returns {Function} handler attache (utilisable pour cleanup eventuel).
 */
export function trapFocus(modalEl) {
  if (!modalEl) return null;
  const handler = (e) => {
    if (e.key !== "Tab") return;
    const focusable = Array.from(modalEl.querySelectorAll(_FOCUSABLE_SELECTOR)).filter(
      (el) => el.offsetParent !== null || el === document.activeElement,
    );
    if (focusable.length === 0) {
      e.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !modalEl.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !modalEl.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  };
  modalEl.addEventListener("keydown", handler);
  modalEl._trapFocusHandler = handler;
  return handler;
}

/**
 * Affiche une modale.
 * @param {object} opts
 * @param {string} opts.title - titre de la modale
 * @param {string} opts.body - contenu HTML de la modale
 * @param {Array<{label:string, cls?:string, onClick:Function}>} [opts.actions] - boutons
 */
export function showModal(opts) {
  closeModal(); // Fermer une eventuelle modale precedente

  const { title = "", body = "", actions = [] } = opts;

  const overlay = document.createElement("div");
  overlay.id = MODAL_CONTAINER_ID;
  overlay.className = "modal-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");

  let actionsHtml = "";
  if (actions.length > 0) {
    actionsHtml = '<div class="modal-actions">';
    actions.forEach((a, i) => {
      actionsHtml += `<button class="btn ${a.cls || ""}" data-modal-action="${i}">${escapeHtml(a.label)}</button>`;
    });
    actionsHtml += "</div>";
  } else {
    actionsHtml = '<div class="modal-actions"><button class="btn" data-modal-close>Fermer</button></div>';
  }

  overlay.innerHTML = `
    <div class="modal-card card">
      <div class="modal-header">
        <h3>${escapeHtml(title)}</h3>
        <button class="modal-close-btn" data-modal-close aria-label="Fermer">&times;</button>
      </div>
      <!-- body is pre-escaped HTML built by callers with escapeHtml() on each field -->
      <div class="modal-body">${body}</div>
      ${actionsHtml}
    </div>`;

  document.body.appendChild(overlay);

  // V2-D (a11y) : memoriser le focus actif pour le restaurer a la fermeture.
  overlay._previouslyFocused = document.activeElement;

  // Fermeture clic sur l'overlay (hors de la card)
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });

  // Fermeture Escape
  overlay._escHandler = (e) => {
    if (e.key === "Escape") closeModal();
  };
  document.addEventListener("keydown", overlay._escHandler);

  // V2-D (WCAG 2.1.2) : focus trap Tab/Shift+Tab a l'interieur de la modale.
  trapFocus(overlay);

  // V2-D (a11y) : poser le focus sur le premier element focusable (ou sur la card).
  const firstFocusable = overlay.querySelector(_FOCUSABLE_SELECTOR);
  if (firstFocusable) {
    try { firstFocusable.focus(); } catch (e) { /* noop */ }
  }

  // Boutons close
  overlay.querySelectorAll("[data-modal-close]").forEach((btn) => {
    btn.addEventListener("click", closeModal);
  });

  // Boutons action
  overlay.querySelectorAll("[data-modal-action]").forEach((btn) => {
    const idx = parseInt(btn.dataset.modalAction, 10);
    if (actions[idx]?.onClick) {
      btn.addEventListener("click", () => {
        actions[idx].onClick();
        closeModal();
      });
    }
  });
}

/** Ferme la modale active. */
export function closeModal() {
  const overlay = $(MODAL_CONTAINER_ID);
  if (!overlay) return;
  if (overlay._escHandler) {
    document.removeEventListener("keydown", overlay._escHandler);
  }
  // V2-D (a11y) : restaurer le focus precedent (avant ouverture de la modale).
  const previous = overlay._previouslyFocused;
  overlay.remove();
  if (previous && typeof previous.focus === "function") {
    try { previous.focus(); } catch (e) { /* noop */ }
  }
}

/**
 * Modale de confirmation avec 2 boutons.
 * @param {string} title
 * @param {string} bodyHtml
 * @param {Function} onConfirm
 */
export function confirmModal(title, bodyHtml, onConfirm) {
  showModal({
    title,
    body: bodyHtml,
    actions: [
      { label: "Annuler", cls: "", onClick: () => {} },
      { label: "Confirmer", cls: "btn-primary", onClick: onConfirm },
    ],
  });
}
