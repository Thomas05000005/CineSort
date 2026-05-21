/* bootstrap-bisect.js — module ESM qui test chaque import individuellement.
 * Identifie quel module bloque le chargement de app.js. */
window.__BISECT_RESULTS = {};

const MODULES = [
  "./core/dom.js",
  "./core/state.js",
  "./core/router.js",
  "./core/api.js",
  "./core/i18n.js",
  "./core/keyboard.js",
  "./core/drop.js",
  "./components/sidebar-v5.js",
  "./components/top-bar-v5.js",
  "./components/breadcrumb.js",
  "./components/notification-center.js",
  "./components/right-panel.js",
  "./components/command-palette.js",
  "./components/copy-to-clipboard.js",
  "./components/auto-tooltip.js",
  "./components/glossary-tooltip.js",
  "./components/film-detail.js",
  "./components/duplicate-comparator-modal.js",
  "./components/perceptual-modal.js",
  "./components/modal.js",
  "./views/login.js",
  "./views/accueil.js",
  "./views/processing.js",
  "./views/parametres.js",
  "./views/aide.js",
  "./views/doublons.js",
  "./views/historique.js",
  "./views/qualite.js",
  "./views/traitement.js",
  "./views/bibliotheque.js",
  "./views/film-detail.js",
];

window.__BISECT_STARTED = true;

for (const path of MODULES) {
  const t0 = Date.now();
  window.__BISECT_RESULTS[path] = "loading";
  Promise.race([
    import(path),
    new Promise((_, rej) => setTimeout(() => rej(new Error("TIMEOUT_5000")), 5000)),
  ])
    .then((mod) => {
      const dt = Date.now() - t0;
      window.__BISECT_RESULTS[path] = "ok " + dt + "ms keys=" + Object.keys(mod).length;
    })
    .catch((err) => {
      const dt = Date.now() - t0;
      const msg = err && err.message ? err.message : String(err);
      const stack = err && err.stack ? String(err.stack).slice(0, 600) : "";
      window.__BISECT_RESULTS[path] = "FAIL " + dt + "ms: " + msg.slice(0, 200) + " | " + stack;
    });
}

window.__BISECT_INSTALLED = true;
