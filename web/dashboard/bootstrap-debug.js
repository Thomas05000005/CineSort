/* bootstrap-debug.js — chargé AVANT app.js pour capturer les erreurs de modules.
 *
 * Les modules ESM qui échouent à charger émettent un 'error' event sur le tag
 * <script type="module"> mais window.onerror ne capture PAS ces erreurs.
 * Ce script installe un handler script-level qui les pousse dans
 * sessionStorage pour debug.
 */
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

  // Capture toutes les erreurs window
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

  // Capture les promesses rejetées
  window.addEventListener("unhandledrejection", function (ev) {
    record("unhandledrejection", { reason: String(ev.reason).slice(0, 500) });
  });

  // Capture les erreurs sur les <script> tags (modules ESM qui échouent)
  // Doit être au CAPTURE phase pour intercepter les script errors.
  document.addEventListener("error", function (ev) {
    const t = ev.target;
    if (t && (t.tagName === "SCRIPT" || t.tagName === "LINK")) {
      record("resource.error", {
        tag: t.tagName,
        src: t.src || t.href,
        type: t.type || "",
      });
    }
  }, true);

  console.log("[BOOT-DEBUG] handlers installed");

  // Probe : essayer de charger app.js en dynamic import pour capturer l'erreur reelle.
  // Le script type="module" classique echoue silencieusement, mais import() rejette
  // avec une vraie erreur que l on peut logger.
  window.__BOOT_DEBUG_PROBE = "starting";
  setTimeout(function () {
    window.__BOOT_DEBUG_PROBE = "probing";
    import("./app.js").then(function (mod) {
      window.__BOOT_DEBUG_PROBE = "app-loaded";
      console.log("[BOOT-DEBUG] app.js dynamic import OK", Object.keys(mod));
    }).catch(function (err) {
      window.__BOOT_DEBUG_PROBE = "app-failed";
      record("app.js-dynamic-import", {
        name: err && err.name,
        message: err && err.message,
        stack: err && err.stack && String(err.stack).slice(0, 2000),
      });
    });
  }, 200);
})();
