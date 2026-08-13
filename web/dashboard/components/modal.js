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
/**
 * Qui possede la modale actuellement a l'ecran, ou `""`.
 *
 * POURQUOI CE N'EST PAS UN COMPTEUR PAR MODULE. Les modales de contenu
 * partagent UN SEUL conteneur : `showModal` commence par `closeModal()`, donc
 * ouvrir l'une detruit l'autre. Un jeton de generation declare DANS chaque
 * module ne voit que ses propres requetes : ouvrir le simulateur puis les
 * regles ne perime RIEN cote simulateur, et sa reponse en vol appelle
 * `_reouvrir()` — qui detruit la modale des regles que l'utilisateur regarde,
 * brouillon de saisie compris.
 *
 * La question qu'un module doit pouvoir poser n'est pas « ma requete est-elle la
 * plus recente ? » mais « suis-je encore la modale a l'ecran ? ». Elle ne se
 * repond qu'ICI, ou vit le conteneur partage.
 */
let _proprietaire = "";

export function modaleCourante() {
  return _proprietaire;
}

export function showModal(opts) {
  closeModal(); // Fermer une eventuelle modale precedente

  const { title = "", body = "", actions = [], proprietaire = "" } = opts;
  _proprietaire = String(proprietaire || "");

  const overlay = document.createElement("div");
  overlay.id = MODAL_CONTAINER_ID;
  overlay.className = "modal-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  // VN-A.3 (WCAG 4.1.2) : aria-labelledby pointe vers le H3 du titre pour que
  // les lecteurs d'ecran (NVDA, JAWS, VoiceOver) annoncent le titre a l'ouverture
  // au lieu de simplement "dialogue".
  overlay.setAttribute("aria-labelledby", "dashModalTitle");

  let actionsHtml = "";
  if (actions.length > 0) {
    actionsHtml = '<div class="modal-actions">';
    actions.forEach((a, i) => {
      // VN-A.3 : escape la classe cote callsite aussi (defense en profondeur
      // au cas ou un caller passe une cls construite a partir de donnees
      // externes : evite injection via attribut class="...").
      const safeCls = escapeHtml(a.cls || "");
      actionsHtml += `<button class="btn ${safeCls}" data-modal-action="${i}">${escapeHtml(a.label)}</button>`;
    });
    actionsHtml += "</div>";
  } else {
    actionsHtml = '<div class="modal-actions"><button class="btn" data-modal-close>Fermer</button></div>';
  }

  overlay.innerHTML = `
    <div class="modal-card card">
      <div class="modal-header">
        <h3 id="dashModalTitle">${escapeHtml(title)}</h3>
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
  // LE PROPRIETAIRE TOMBE MEME SI AUCUNE MODALE N'EST OUVERTE. Sortir avant
  // laisserait un module se croire « encore a l'ecran » apres une fermeture
  // deja consommee — exactement le cas que le jeton doit detecter.
  _proprietaire = "";
  const overlay = $(MODAL_CONTAINER_ID);
  if (!overlay) return;
  if (overlay._escHandler) {
    document.removeEventListener("keydown", overlay._escHandler);
  }
  // V2-D (a11y) : restaurer le focus precedent (avant ouverture de la modale).
  const previous = overlay._previouslyFocused;
  overlay.remove();
  // VN-A.3 : ne restaurer le focus que si l'element est TOUJOURS dans le DOM
  // (sinon focus tombe sur <body>, ce qui est pire que de laisser le navigateur
  // gerer le defaut). isConnected couvre les cas ou le previous a ete supprime
  // pendant l'ouverture de la modale (re-render react-like).
  if (previous && typeof previous.focus === "function" && previous.isConnected) {
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
 * QUAND EXIGER UN MOT TAPE — le critere, pour qu'il ne s'etende pas par habitude.
 * Le depot compte une vingtaine de confirmations dangereuses ; trois seulement
 * portent un mot a taper, et c'est deliberé : **la saisie ne protege que parce
 * qu'elle est rare**. L'imposer partout la transformerait en reflexe, donc en
 * rien.
 *
 * Deux conditions, ensemble :
 *   1. la perte est IRRECUPERABLE PAR L'APPLICATION (ni undo, ni corbeille, ni
 *      restauration depuis l'interface) ;
 *   2. la portee n'est PAS une selection que l'utilisateur vient de faire.
 *
 * Ce que cela EXCLUT, et pourquoi : « supprimer N films » ne fait que les
 * MARQUER ; « lancer l'apply » a un undo ; « regenerer le token » se refait ;
 * « re-calculer les scores » se recalcule. Aucune ne remplit les deux
 * conditions.
 *
 * @param {string} [opts.requireTyped=""] - mot que l'utilisateur doit TAPER
 *   pour armer le bouton de confirmation. Le texte saisi est transmis a
 *   `onConfirm(saisie)` : l'appelant envoie ce que l'utilisateur a ecrit, et non
 *   une constante — sinon le garde du backend ne verifierait plus rien.
 * @param {boolean} [opts.closeBeforeConfirm=false] - fermer la modale AVANT de
 *        lancer onConfirm au lieu d'attendre sa resolution (cf plus bas).
 * @returns {Promise<void>} resolue apres affichage (pas attente de l'utilisateur)
 */
/**
 * Delai de confirmation derive du NOMBRE d'elements (regle projet n3).
 *
 * Le seuil vit ici, et plus dans chaque appelant. Mesure du 2026-08-06 sur les
 * 19 sites d'appel de `dangerConfirmModal` : QUATRE conventions coexistaient —
 *
 *   graduee (n<=30 -> 0, n>50 -> 3, interpolation entre)   2 sites
 *   ternaire `n > 50 ? 3 : 0`                              4 sites
 *   fixe 3, quel que soit le volume                        8 sites
 *   rien passe -> 0                                        3 sites
 *
 * Le dernier groupe contient « Lancer l'apply » (processing.js), qui renomme et
 * deplace N films sur disque : ni liste, ni delai, quel que soit N. Une regle
 * appliquee de quatre facons differentes n'est pas une regle.
 *
 * Le clamp `> 50 -> 3` est celui de la regle utilisateur, pas une interpolation :
 * une version anterieure rendait 1 s ou 2 s pour n entre 51 et 99 et la violait.
 */
export function gradedCountdownSeconds(count) {
  const n = Number(count) || 0;
  if (n <= 30) return 0;
  if (n > 50) return 3;
  const linear = ((n - 30) / (100 - 30)) * 3;
  return Math.max(0, Math.min(3, Math.round(linear)));
}

export function dangerConfirmModal(opts) {
  // Fermer toute modale danger existante (re-trigger rapide)
  const existing = document.getElementById(DANGER_MODAL_ID);
  if (existing) existing.remove();

  const {
    title = "Confirmer ?",
    items = [],
    consequence = "",
    // `null` (ou absent) = DERIVE du nombre d'elements. Une valeur explicite
    // gagne toujours : les sites qui passent deja leur propre calcul ne changent
    // pas de comportement. Ceux qui ne passaient RIEN heritaient de 0 seconde,
    // y compris sur des actions massives — c'est ce trou que le defaut comble.
    countdownSeconds = null,
    // Nombre d'elements quand la LISTE n'est pas disponible (un compteur suffit
    // a graduer le delai). A defaut, on retombe sur `items.length`.
    itemCount = null,
    confirmLabel = "Confirmer",
    cancelLabel = "Annuler",
    onConfirm = () => {},
    // Fix audit 2026-06-07 UX high : onCancel optionnel, appele quand l'utilisateur
    // annule (clic Annuler, Esc, clic backdrop). Resout le deadlock UX ou la
    // bibliotheque laissait _state.bulkInFlight=true apres une annulation (boutons
    // bulk disabled jusqu'au reload). N'est jamais appele apres onConfirm.
    onCancel = null,
    // Ultra-audit 2026-08-03 (N13) : par defaut la modale reste affichee tant
    // que `onConfirm` n'a pas resolu — ce qui est le bon comportement pour une
    // action breve (on evite un double-clic sur le declencheur sous-jacent).
    // Pour une action LONGUE dont l'avancement est rendu DERRIERE la modale
    // (l'apply reel et sa barre de progression), l'overlay opaque devient au
    // contraire un ecran de veille : il masque la seule information utile
    // pendant plusieurs minutes. Ces appelants passent closeBeforeConfirm:true
    // et doivent porter leur PROPRE garde de re-entrance (cf _handleApplyNow).
    // Opt-in deliberement : les ~20 autres sites d'appel gardent la semantique
    // historique, aucun n'est modifie par ce correctif.
    // LE DERNIER CRAN AVANT L'IRREVERSIBLE. `settings.reset_all_user_data`
    // exige `confirmation == "RESET"` (reset_support.py:266) : sans affordance
    // de saisie, cette capacite etait INATTEIGNABLE depuis toute l'application —
    // la seule des dix methodes de la vague B3 a l'etre restee.
    requireTyped = "",
    closeBeforeConfirm = false,
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

  const motAttendu = String(requireTyped || "");
  const saisieHtml = motAttendu
    ? `<label class="danger-modal-saisie">
        <span>Pour confirmer, tapez <strong>${escapeHtml(motAttendu)}</strong></span>
        <input type="text" data-danger-saisie autocomplete="off" spellcheck="false"
               aria-label="Tapez ${escapeHtml(motAttendu)} pour confirmer">
      </label>`
    : "";

  const nbElements = itemCount === null || itemCount === undefined
    ? (Array.isArray(items) ? items.length : 0)
    : (Number(itemCount) || 0);
  const countdown = countdownSeconds === null || countdownSeconds === undefined
    ? gradedCountdownSeconds(nbElements)
    : Math.max(0, parseInt(countdownSeconds, 10) || 0);
  // Les deux verrous sont INDEPENDANTS : le decompte n'arme rien si le mot
  // manque, et le mot n'arme rien tant que le decompte court.
  const confirmDisabled = countdown > 0 || motAttendu ? "disabled" : "";
  const countdownSuffix = countdown > 0
    ? ` <span class="danger-modal-confirm-countdown" data-danger-countdown>(${countdown}s)</span>`
    : "";

  overlay.innerHTML = `
    <div class="danger-modal card" role="document">
      <h3 id="${DANGER_MODAL_ID}Title" class="danger-modal-title">${escapeHtml(title)}</h3>
      ${itemsHtml}
      ${consequenceHtml}
      ${saisieHtml}
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
  const champ = overlay.querySelector("[data-danger-saisie]");

  // Fix audit 2026-06-07 UX high : drapeau pour distinguer fermeture-apres-confirm
  // de fermeture-via-cancel (clic Annuler, Esc, backdrop). onCancel n'est appele
  // QUE dans le cas annulation.
  overlay._confirmed = false;

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
    const wasCancel = !overlay._confirmed;
    overlay.remove();
    // VN-A.3 : verifier isConnected avant de restaurer le focus precedent
    // (l'element a pu etre supprime pendant que la modale etait ouverte,
    //  ex. re-render apres l'action confirmee).
    if (prev && typeof prev.focus === "function" && prev.isConnected) {
      try { prev.focus(); } catch (e) { /* noop */ }
    }
    // onCancel apres remove() pour eviter qu'un re-render synchrone du caller
    // n'interagisse avec une modale en cours de demontage.
    if (wasCancel && typeof onCancel === "function") {
      try { onCancel(); } catch (e) { console.error("[dangerConfirmModal] onCancel failed", e); }
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
      // CE QUE L'UTILISATEUR A TAPE, et non le mot attendu : l'appelant le
      // transmet au backend, dont le garde reste ainsi une verification reelle.
      const saisie = champ ? String(champ.value || "").trim() : "";
      // Eviter double-clic pendant l'execution
      confirmBtn.disabled = true;
      // Fix audit 2026-06-07 UX high : marquer _confirmed avant close() pour
      // que onCancel ne soit PAS appele dans ce cas (cf close()).
      overlay._confirmed = true;
      if (closeBeforeConfirm) {
        // N13 : la confirmation a rempli son office des le clic. On demonte
        // l'overlay AVANT de lancer l'action pour que l'UI de progression
        // qu'elle declenche soit reellement visible. `_confirmed` etant deja
        // pose, close() n'appelle pas onCancel.
        close();
        await Promise.resolve(onConfirm(saisie));
        return;
      }
      try {
        await Promise.resolve(onConfirm(saisie));
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
        // La fin du decompte ne leve QUE son propre verrou : si un mot est
        // exige et n'est pas encore tape, le bouton reste desarme.
        confirmBtn.disabled = !!(motAttendu && !overlay._motTape);
        if (span) span.remove();
      } else if (span) {
        span.textContent = `(${remaining}s)`;
      }
    }, 1000);
  }

  // Le champ de saisie arme le bouton ; le decompte ne le fait jamais seul.
  if (champ && confirmBtn) {
    champ.addEventListener("input", () => {
      // Comparaison EXACTE, espaces de bord retires : ni insensible a la casse,
      // ni tolerante. « reset » n'est pas « RESET », et le backend refuserait
      // de toute facon — l'ecran ne doit pas promettre l'inverse.
      // UNE ACTION DEJA ENGAGEE NE SE RE-ARME PAS. Le clic pose
      // `confirmBtn.disabled = true` pour empecher une double soumission, mais la
      // modale reste affichee tant que `onConfirm` n'a pas resolu — et sans ce
      // garde, retoucher le champ pendant ce temps RE-ARMAIT le bouton. Sur
      // « Tout reinitialiser », cela lancait un second wipe pendant le premier.
      if (overlay._confirmed) return;
      overlay._motTape = String(champ.value || "").trim() === motAttendu;
      confirmBtn.disabled = !overlay._motTape || !!overlay._countdownTimer;
    });
  }

  // Focus initial : Annuler (anti-clic-reflexe sur Confirmer)
  if (cancelBtn) {
    try { cancelBtn.focus(); } catch (e) { /* noop */ }
  }
}
