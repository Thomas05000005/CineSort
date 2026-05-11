function $(id){ return document.getElementById(id); }
function qsa(sel){ return Array.from(document.querySelectorAll(sel)); }

const statusVersions = new Map(); // statusId -> monotonically increasing version
const statusClearTimers = new Map(); // statusId -> timeout id

function setPill(id, text){
  const el = $(id);
  if(el) el.textContent = text;
}

function setStatusMessage(id, text, opts = {}){
  const el = $(id);
  if(!el) return;
  const nextVersion = (Number(statusVersions.get(id) || 0) + 1);
  statusVersions.set(id, nextVersion);
  el.textContent = String(text || "");
  el.classList.toggle("isLoading", !!opts.loading);
  el.classList.toggle("isError", !!opts.error);
  el.classList.toggle("isSuccess", !!opts.success);
  if(opts.loading){
    const previous = statusClearTimers.get(id);
    if(previous){
      window.clearTimeout(previous);
      statusClearTimers.delete(id);
    }
  }
  if(Number(opts.clearMs || 0) > 0){
    clearStatusMessageLater(id, Number(opts.clearMs));
  }
}

function clearStatusMessageLater(id, delayMs){
  const statusId = String(id || "").trim();
  if(!statusId) return;
  const expectedVersion = Number(statusVersions.get(statusId) || 0);
  const previous = statusClearTimers.get(statusId);
  if(previous){
    window.clearTimeout(previous);
  }
  const timeoutMs = Math.max(120, Number(delayMs || 0));
  const timerId = window.setTimeout(() => {
    const liveVersion = Number(statusVersions.get(statusId) || 0);
    if(liveVersion !== expectedVersion){
      return;
    }
    setStatusMessage(statusId, "");
    statusClearTimers.delete(statusId);
  }, timeoutMs);
  statusClearTimers.set(statusId, timerId);
}

function flashActionButton(target, kind = "ok"){
  const el = (typeof target === "string") ? $(target) : target;
  if(!(el instanceof HTMLElement)) return;
  const cls = kind === "error" ? "btn-feedback-error" : "btn-feedback-ok";
  el.classList.remove("btn-feedback-ok", "btn-feedback-error");
  void el.offsetWidth;
  el.classList.add(cls);
  window.setTimeout(() => {
    el.classList.remove(cls);
  }, 420);
}

function probeToolStatusLine(label, tool){
  const t = (tool && typeof tool === "object") ? tool : {};
  const status = String(t.status || "missing");
  const ver = String(t.version || "").trim();
  const src = String(t.source || "none");
  const msg = String(t.message || "");
  const head = status === "ok" ? `${label}: OK` : `${label}: ${status}`;
  const suffix = ver ? `v${ver}` : "version n/d";
  return `${head} (${suffix}, source=${src})${msg ? ` — ${msg}` : ""}`;
}

async function apiCall(name, fn, opts = {}){
  try {
    const result = await fn();
    if(result === undefined || result === null){
      return { ok: false, message: `Réponse invalide pour ${name}.` };
    }
    return result;
  } catch(err){
    const details = String(err || "Erreur inconnue");
    const fallback = String(opts.fallbackMessage || `Erreur pendant ${name}.`);
    if(opts.statusId){
      setStatusMessage(opts.statusId, `${fallback}`, { error: true });
    }
    console.error(`[apiCall:${name}]`, err);
    return { ok: false, message: details };
  }
}

async function openPathWithFeedback(
  path,
  statusId,
  fallbackMessage = "Impossible d'ouvrir ce dossier.",
  opts = {},
){
  const res = await apiCall("open_path", () => window.pywebview.api.open_path(path), {
    statusId,
    fallbackMessage,
  });
  if(!res?.ok){
    setStatusMessage(statusId, `Impossible d'ouvrir ce dossier : ${res?.message || "erreur inconnue"}`, { error: true });
    flashActionButton(opts.triggerEl || null, "error");
    return res;
  }
  if(opts.successMessage){
    setStatusMessage(statusId, String(opts.successMessage), {
      success: true,
      clearMs: Number(opts.clearMs || 1800),
    });
  }
  flashActionButton(opts.triggerEl || null, "ok");
  return res;
}

function getStoredText(key){
  try {
    return String(localStorage.getItem(key) || "");
  } catch(_e){
    return "";
  }
}

function setStoredText(key, value){
  try {
    if(value === undefined || value === null || String(value) === ""){
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(key, String(value));
    }
  } catch(_e){
    // no-op
  }
}

function copyTextSafe(text){
  const val = String(text || "").trim();
  if(!val){
    return false;
  }
  if(navigator?.clipboard?.writeText){
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
  } catch(_e){
    return false;
  }
}

function openModal(id){
  const modal = $(id);
  if(!modal) return;
  state.activeModalId = id;
  state.modalReturnFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  const firstFocusable = modal.querySelector("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
  if(firstFocusable instanceof HTMLElement){
    firstFocusable.focus();
  }
}

function closeModal(id){
  const modal = $(id);
  if(!modal) return;
  if(id === "modalActionDialog" && typeof actionDialogResolver === "function"){
    actionDialogResolver(false);
    actionDialogResolver = null;
  }
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  if(state.activeModalId === id){
    state.activeModalId = null;
    const restore = state.modalReturnFocusEl;
    state.modalReturnFocusEl = null;
    if(restore instanceof HTMLElement){
      restore.focus();
    }
  }
}

let modalHandlersReady = false;
let actionDialogResolver = null;

function initModalHandlers(){
  if(modalHandlersReady){
    return;
  }
  modalHandlersReady = true;
  document.addEventListener("keydown", (e) => {
    if(e.key === "Escape" && state.activeModalId){
      closeModal(state.activeModalId);
    }
  });
  qsa(".modal").forEach((modal) => {
    modal.addEventListener("click", (e) => {
      if(e.target === modal){
        closeModal(modal.id);
      }
    });
  });

  const btnCancel = $("modalActionCancel");
  const btnConfirm = $("modalActionConfirm");
  btnCancel?.addEventListener("click", () => {
    if(typeof actionDialogResolver === "function"){
      actionDialogResolver(false);
      actionDialogResolver = null;
    }
    closeModal("modalActionDialog");
  });
  btnConfirm?.addEventListener("click", () => {
    if(typeof actionDialogResolver === "function"){
      actionDialogResolver(true);
      actionDialogResolver = null;
    }
    closeModal("modalActionDialog");
  });
}

function showActionDialog(opts = {}){
  const modal = $("modalActionDialog");
  if(!modal){
    return Promise.resolve(false);
  }
  const title = String(opts.title || "Confirmation");
  const message = String(opts.message || "Voulez-vous continuer ?");
  const confirmLabel = String(opts.confirmLabel || "Continuer");
  const cancelLabel = String(opts.cancelLabel || "Annuler");
  const allowCancel = opts.allowCancel !== false;
  const danger = !!opts.danger;

  const titleEl = $("modalActionDialogTitle");
  const msgEl = $("modalActionDialogMessage");
  const cancelEl = $("modalActionCancel");
  const confirmEl = $("modalActionConfirm");
  if(titleEl) titleEl.textContent = title;
  if(msgEl) msgEl.textContent = message;
  if(cancelEl){
    cancelEl.textContent = cancelLabel;
    cancelEl.classList.toggle("hidden", !allowCancel);
  }
  if(confirmEl){
    confirmEl.textContent = confirmLabel;
    confirmEl.classList.toggle("primary", !danger);
    confirmEl.classList.toggle("danger", danger);
  }

  if(typeof actionDialogResolver === "function"){
    actionDialogResolver(false);
    actionDialogResolver = null;
  }

  openModal("modalActionDialog");
  return new Promise((resolve) => {
    actionDialogResolver = resolve;
  });
}

async function uiConfirm(opts = {}){
  if($("modalActionDialog")){
    const accepted = await showActionDialog({
      title: opts.title || "Confirmation requise",
      message: opts.message || "Voulez-vous continuer ?",
      confirmLabel: opts.confirmLabel || "Continuer",
      cancelLabel: opts.cancelLabel || "Annuler",
      allowCancel: true,
      danger: !!opts.danger,
    });
    return !!accepted;
  }
  const target = String(opts.statusId || "").trim();
  if(target && $(target)){
    setStatusMessage(target, "Confirmation indisponible : action annulée.", { error: true, clearMs: 3200 });
  }
  console.warn("[uiConfirm] modalActionDialog indisponible, action annulée.");
  return false;
}

async function uiInfo(opts = {}){
  if($("modalActionDialog")){
    await showActionDialog({
      title: opts.title || "Information",
      message: opts.message || "",
      confirmLabel: opts.confirmLabel || "OK",
      allowCancel: false,
      danger: false,
    });
    return;
  }
  const target = String(opts.statusId || "").trim();
  const msg = String(opts.message || "");
  if(target && $(target) && msg){
    setStatusMessage(target, msg, { error: !!opts.error, success: !opts.error, clearMs: 3200 });
  }
  console.warn("[uiInfo] modalActionDialog indisponible.", msg);
}
