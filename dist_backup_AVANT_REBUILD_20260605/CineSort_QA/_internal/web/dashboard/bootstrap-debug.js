/* bootstrap-debug.js — chargé AVANT app.js pour capturer les erreurs de modules. */
(function () {
  const errors = [];
  function record(label, info) {
    errors.push({ label, time: Date.now(), info });
    try { sessionStorage.setItem("cinesort.boot.errors", JSON.stringify(errors)); } catch (e) {}
    try { localStorage.setItem("cinesort.boot.errors", JSON.stringify(errors)); } catch (e) {}
    console.error("[BOOT-DEBUG] " + label, info);
  }
  window.__BOOT_DEBUG_INSTALLED = true;
  window.__BOOT_DEBUG_ERRORS = errors;
  window.addEventListener("error", function (ev) {
    record("window.error", {
      message: ev.message,
      source: ev.filename,
      line: ev.lineno,
      col: ev.colno,
      error_name: ev.error && ev.error.name,
      error_msg: ev.error && ev.error.message,
      error_stack: ev.error && ev.error.stack && String(ev.error.stack).slice(0, 1000),
    });
  }, true);
  window.addEventListener("unhandledrejection", function (ev) {
    record("unhandledrejection", { reason: String(ev.reason).slice(0, 500) });
  });
  document.addEventListener("error", function (ev) {
    const t = ev.target;
    if (t && (t.tagName === "SCRIPT" || t.tagName === "LINK")) {
      record("resource.error", { tag: t.tagName, src: t.src || t.href, type: t.type || "" });
    }
  }, true);
  console.log("[BOOT-DEBUG] handlers installed");
})();
