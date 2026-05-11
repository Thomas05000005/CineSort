/* components/status.js — Status messages + button feedback */

const _statusVersions = new Map();
const _statusClearTimers = new Map();

function setStatusMessage(id, text, opts = {}) {
  const el = $(id);
  if (!el) return;
  const nextVersion = (Number(_statusVersions.get(id) || 0) + 1);
  _statusVersions.set(id, nextVersion);
  el.textContent = String(text || "");
  el.classList.toggle("isLoading", !!opts.loading);
  el.classList.toggle("isError", !!opts.error);
  el.classList.toggle("isSuccess", !!opts.success);
  if (opts.loading) {
    const prev = _statusClearTimers.get(id);
    if (prev) { window.clearTimeout(prev); _statusClearTimers.delete(id); }
  }
  if (Number(opts.clearMs || 0) > 0) {
    clearStatusMessageLater(id, Number(opts.clearMs));
  }
}

function clearStatusMessageLater(id, delayMs) {
  const statusId = String(id || "").trim();
  if (!statusId) return;
  const expectedVersion = Number(_statusVersions.get(statusId) || 0);
  const prev = _statusClearTimers.get(statusId);
  if (prev) window.clearTimeout(prev);
  const timerId = window.setTimeout(() => {
    if (Number(_statusVersions.get(statusId) || 0) !== expectedVersion) return;
    setStatusMessage(statusId, "");
    _statusClearTimers.delete(statusId);
  }, Math.max(120, Number(delayMs || 0)));
  _statusClearTimers.set(statusId, timerId);
}

function flashActionButton(target, kind) {
  const el = (typeof target === "string") ? $(target) : target;
  if (!(el instanceof HTMLElement)) return;
  const cls = kind === "error" ? "btn-feedback-error" : "btn-feedback-ok";
  el.classList.remove("btn-feedback-ok", "btn-feedback-error");
  void el.offsetWidth;
  el.classList.add(cls);
  window.setTimeout(() => el.classList.remove(cls), 420);
}
