/* components/modal.js — Modal system with focus trapping */

let _modalHandlersReady = false;
let _actionDialogResolver = null;

function getFocusableElements(container) {
  if (!(container instanceof HTMLElement)) return [];
  const sel = [
    "button:not([disabled])", "[href]",
    "input:not([disabled])", "select:not([disabled])",
    "textarea:not([disabled])", "[tabindex]:not([tabindex='-1'])",
  ].join(", ");
  return Array.from(container.querySelectorAll(sel)).filter((el) => {
    if (!(el instanceof HTMLElement) || el.hasAttribute("disabled")) return false;
    if (el.getAttribute("aria-hidden") === "true" || el.hidden) return false;
    return el.getClientRects().length > 0;
  });
}

function trapModalFocus(e, modal) {
  if (!(modal instanceof HTMLElement) || e.key !== "Tab") return;
  const focusables = getFocusableElements(modal);
  if (focusables.length === 0) { e.preventDefault(); modal.focus(); return; }
  if (focusables.length === 1) { e.preventDefault(); focusables[0].focus(); return; }
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  if (e.shiftKey) {
    if (active === first || !active || !modal.contains(active)) { e.preventDefault(); last.focus(); }
  } else {
    if (active === last || !active || !modal.contains(active)) { e.preventDefault(); first.focus(); }
  }
}

function openModal(id) {
  const modal = $(id);
  if (!modal) return;
  state.activeModalId = id;
  state.modalReturnFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  if (!modal.hasAttribute("tabindex")) modal.setAttribute("tabindex", "-1");
  const first = getFocusableElements(modal)[0];
  if (first instanceof HTMLElement) first.focus();
  else modal.focus();
}

function closeModal(id) {
  const modal = $(id);
  if (!modal) return;
  if (id === "modalActionDialog" && typeof _actionDialogResolver === "function") {
    _actionDialogResolver(false);
    _actionDialogResolver = null;
  }
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  if (state.activeModalId === id) {
    state.activeModalId = null;
    const restore = state.modalReturnFocusEl;
    state.modalReturnFocusEl = null;
    if (restore instanceof HTMLElement) restore.focus();
  }
}

function initModalHandlers() {
  if (_modalHandlersReady) return;
  _modalHandlersReady = true;
  document.addEventListener("keydown", (e) => {
    const activeModal = state.activeModalId ? $(state.activeModalId) : null;
    if (e.key === "Escape" && state.activeModalId) { closeModal(state.activeModalId); return; }
    if (e.key === "Tab" && activeModal instanceof HTMLElement) trapModalFocus(e, activeModal);
  });
  qsa(".modal").forEach((modal) => {
    if (!modal.hasAttribute("tabindex")) modal.setAttribute("tabindex", "-1");
    modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(modal.id); });
  });
  $("modalActionCancel")?.addEventListener("click", () => {
    if (typeof _actionDialogResolver === "function") { _actionDialogResolver(false); _actionDialogResolver = null; }
    closeModal("modalActionDialog");
  });
  $("modalActionConfirm")?.addEventListener("click", () => {
    if (typeof _actionDialogResolver === "function") { _actionDialogResolver(true); _actionDialogResolver = null; }
    closeModal("modalActionDialog");
  });
}

function showActionDialog(opts = {}) {
  const modal = $("modalActionDialog");
  if (!modal) return Promise.resolve(false);
  const titleEl = $("modalActionDialogTitle");
  const msgEl = $("modalActionDialogMessage");
  const cancelEl = $("modalActionCancel");
  const confirmEl = $("modalActionConfirm");
  if (titleEl) titleEl.textContent = String(opts.title || "Confirmation");
  if (msgEl) msgEl.textContent = String(opts.message || "Voulez-vous continuer ?");
  if (cancelEl) {
    cancelEl.textContent = String(opts.cancelLabel || "Annuler");
    cancelEl.classList.toggle("hidden", opts.allowCancel === false);
  }
  if (confirmEl) {
    confirmEl.textContent = String(opts.confirmLabel || "Continuer");
    confirmEl.classList.toggle("btn--primary", !opts.danger);
    confirmEl.classList.toggle("btn--danger", !!opts.danger);
  }
  if (typeof _actionDialogResolver === "function") { _actionDialogResolver(false); _actionDialogResolver = null; }
  openModal("modalActionDialog");
  return new Promise((resolve) => { _actionDialogResolver = resolve; });
}

async function uiConfirm(opts = {}) {
  if ($("modalActionDialog")) {
    return !!(await showActionDialog({
      title: opts.title || "Confirmation requise",
      message: opts.message || "Voulez-vous continuer ?",
      confirmLabel: opts.confirmLabel || "Continuer",
      cancelLabel: opts.cancelLabel || "Annuler",
      allowCancel: true,
      danger: !!opts.danger,
    }));
  }
  console.warn("[uiConfirm] modale indisponible, action annulee.");
  return false;
}

async function uiInfo(opts = {}) {
  if ($("modalActionDialog")) {
    await showActionDialog({
      title: opts.title || "Information",
      message: opts.message || "",
      confirmLabel: opts.confirmLabel || "OK",
      allowCancel: false,
    });
    return;
  }
  console.warn("[uiInfo] modale indisponible.", opts.message || "");
}
