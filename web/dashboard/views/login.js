/* views/login.js — Vue de connexion (saisie token Bearer) */

import { $, escapeHtml } from "../core/dom.js";
import { setToken, isPersistent } from "../core/state.js";
import { testConnection } from "../core/api.js";
import { navigateTo } from "../core/router.js";

/**
 * Detecte le mode pywebview desktop (4 signaux). Si on est en local,
 * la vue login n'a aucun sens et on redirige immediatement vers /accueil.
 * Derniere ceinture defensive en cas ou le router laisse passer.
 */
function _isNativeMode() {
  if (typeof window === "undefined") return false;
  if (window.__CINESORT_NATIVE__) return true;
  if (window.pywebview && window.pywebview.api) return true;
  const host = window.location && window.location.hostname;
  if (host === "127.0.0.1" || host === "localhost") return true;
  try { if (localStorage.getItem("cinesort.native") === "1") return true; } catch { /* no-op */ }
  return false;
}

/** Initialise les evenements du formulaire de login. */
export function initLogin() {
  // Mode natif : la vue login ne doit JAMAIS s'afficher. Derniere garde
  // de securite au cas ou le router aurait deja navigue ici malgre les
  // fixes router.js. On force /accueil immediatement.
  if (_isNativeMode()) {
    console.warn("[login] mode natif detecte, redirection vers /accueil");
    navigateTo("/accueil");
    return;
  }

  const form = $("loginForm");
  const input = $("loginToken");
  const persist = $("loginPersist");
  const msg = $("loginMsg");
  const btn = $("loginBtn");
  const spinner = $("loginSpinner");

  if (!form || !input) return;

  // Restaurer la preference "rester connecte"
  if (persist) persist.checked = isPersistent();

  // Focus auto sur l'input
  input.focus();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const token = input.value.trim();
    if (!token) {
      showMsg(msg, "Saisissez la clé d'accès.", true);
      return;
    }

    // UI loading
    if (btn) btn.disabled = true;
    if (spinner) spinner.classList.remove("hidden");
    showMsg(msg, "");

    try {
      const result = await testConnection(token);
      if (result.ok) {
        setToken(token, persist ? persist.checked : false);
        showMsg(msg, "");
        navigateTo("/status");
      } else {
        showMsg(msg, escapeHtml(result.message || "Connexion refusee."), true);
      }
    } catch (err) {
      showMsg(msg, "Erreur reseau. Verifiez l'adresse du serveur.", true);
      console.error("[login]", err);
    } finally {
      if (btn) btn.disabled = false;
      if (spinner) spinner.classList.add("hidden");
    }
  });
}

function showMsg(el, text, isError = false) {
  if (!el) return;
  el.innerHTML = text;
  el.className = "status-msg" + (isError ? " error" : "");
}
