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

// =============================================================================
// dangerConfirmModal — modale specifique aux actions dangereuses
// =============================================================================
//
// P0 #233 : feedback-cinesort-actions-dangereuses impose qu'une suppression /
// reset / marquage destructif n'utilise PLUS window.confirm() mais une modale
// dediee montrant :
//   1. le titre exact de l'action (ex. "Confirmer la suppression de N films ?"),
//   2. la liste des elements concernes (5 max visibles, "+ N autres" sinon),
//   3. la consequence concrete (ex. "Deplaces vers _trash, reversible 30j"),
//   4. un compteur anti-clic-reflexe (>0 = bouton Confirmer desactive N s),
//   5. focus initial sur Annuler, Esc + clic backdrop = Annuler,
//   6. ARIA dialog/modal (lu par lecteurs d'ecran).
//
// La modale est INDEPENDANTE de showModal() : elle gere son propre overlay car
// elle a besoin d'attributs ARIA specifiques (role=alertdialog, aria-describedby)
// et d'un focus initial different (Annuler vs premier focusable).

const DANGER_MODAL_ID = "dashDangerModal";

/**
 * Affiche une modale de confirmation dangereuse.
 *
 * @param {object} opts
 * @param {string} opts.title - "Confirmer la suppression de N films ?"
 * @param {string[]} [opts.items] - elements concernes (max 5 visibles)
 * @param {string} [opts.consequence] - explication de la consequence
 * @param {number} [opts.countdownSeconds=0] - 0 = immediat, >0 = bouton desactive N s
 * @param {string} [opts.confirmLabel="Confirmer"] - libelle du bouton dangereux
 * @param {string} [opts.cancelLabel="Annuler"] - libelle du bouton d'annulation
 * @param {Function} opts.onConfirm - callback (peut etre async), execute apres confirmation
 * @returns {Promise<void>} resolue apres affichage (pas attente de l'utilisateur)
 */
export function dangerConfirmModal(opts) {
  // Fermer toute modale danger existante (re-trigger rapide)
  const existing = document.getElementById(DANGER_MODAL_ID);
  if (existing) existing.remove();

  const {
    title = "Confirmer ?",
    items = [],
    consequence = "",
    countdownSeconds = 0,
    confirmLabel = "Confirmer",
    cancelLabel = "Annuler",
    onConfirm = () => {},
  } = opts || {};

  const overlay = document.createElement("div");
  overlay.id = DANGER_MODAL_ID;
  overlay.className = "danger-modal-overlay";
  // role=alertdialog : modale critique requerant une decision immediate (WAI-ARIA).
  overlay.setAttribute("role", "alertdialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-labelledby", `${DANGER_MODAL_ID}Title`);
  if (consequence) {
    overlay.setAttribute("aria-describedby", `${DANGER_MODAL_ID}Consequence`);
  }

  // Items list : 5 visibles max + "et N autres"
  let itemsHtml = "";
  if (Array.isArray(items) && items.length > 0) {
    const visible = items.slice(0, 5);
    const more = items.length - visible.length;
    const li = visible.map((it) => `<li>${escapeHtml(String(it))}</li>`).join("");
    const moreHtml = more > 0
      ? `<li class="danger-modal-items-more">… et ${more} autre${more > 1 ? "s" : ""}</li>`
      : "";
    itemsHtml = `<ul class="danger-modal-items">${li}${moreHtml}</ul>`;
  }

  const consequenceHtml = consequence
    ? `<p id="${DANGER_MODAL_ID}Consequence" class="danger-modal-consequence">${escapeHtml(consequence)}</p>`
    : "";

  const countdown = Math.max(0, parseInt(countdownSeconds, 10) || 0);
  const confirmDisabled = countdown > 0 ? "disabled" : "";
  const countdownSuffix = countdown > 0
    ? ` <span class="danger-modal-confirm-countdown" data-danger-countdown>(${countdown}s)</span>`
    : "";

  overlay.innerHTML = `
    <div class="danger-modal card" role="document">
      <h3 id="${DANGER_MODAL_ID}Title" class="danger-modal-title">${escapeHtml(title)}</h3>
      ${itemsHtml}
      ${consequenceHtml}
      <div class="danger-modal-actions">
        <button type="button" class="v5-btn" data-danger-cancel>${escapeHtml(cancelLabel)}</button>
        <button type="button" class="v5-btn v5-btn--danger" data-danger-confirm ${confirmDisabled}>${escapeHtml(confirmLabel)}${countdownSuffix}</button>
      </div>
    </div>`;

  document.body.appendChild(overlay);

  // Memoriser le focus precedent pour restauration apres fermeture
  overlay._previouslyFocused = document.activeElement;

  const cancelBtn = overlay.querySelector("[data-danger-cancel]");
  const confirmBtn = overlay.querySelector("[data-danger-confirm]");

  // Fermeture / annulation centralisee
  const close = () => {
    if (overlay._countdownTimer) {
      clearInterval(overlay._countdownTimer);
      overlay._countdownTimer = null;
    }
    if (overlay._escHandler) {
      document.removeEventListener("keydown", overlay._escHandler);
    }
    const prev = overlay._previouslyFocused;
    overlay.remove();
    if (prev && typeof prev.focus === "function") {
      try { prev.focus(); } catch (e) { /* noop */ }
    }
  };

  // Clic backdrop (hors card) = annuler
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  // Esc = annuler
  overlay._escHandler = (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  };
  document.addEventListener("keydown", overlay._escHandler);

  // Focus trap Tab/Shift+Tab (reutilise trapFocus existant)
  trapFocus(overlay);

  // Bouton Annuler
  if (cancelBtn) cancelBtn.addEventListener("click", close);

  // Bouton Confirmer (await async onConfirm avant de fermer)
  if (confirmBtn) {
    confirmBtn.addEventListener("click", async () => {
      if (confirmBtn.disabled) return;
      // Eviter double-clic pendant l'execution
      confirmBtn.disabled = true;
      try {
        await Promise.resolve(onConfirm());
      } finally {
        close();
      }
    });
  }

  // Countdown : decrement chaque seconde, enabled a 0
  if (countdown > 0 && confirmBtn) {
    let remaining = countdown;
    const span = confirmBtn.querySelector("[data-danger-countdown]");
    overlay._countdownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(overlay._countdownTimer);
        overlay._countdownTimer = null;
        confirmBtn.disabled = false;
        if (span) span.remove();
      } else if (span) {
        span.textContent = `(${remaining}s)`;
      }
    }, 1000);
  }

  // Focus initial : Annuler (anti-clic-reflexe sur Confirmer)
  if (cancelBtn) {
    try { cancelBtn.focus(); } catch (e) { /* noop */ }
  }
}
