/* views/login.js — Vue de connexion (saisie token Bearer) */

import { $, escapeHtml } from "../core/dom.js";
import { setToken, isPersistent } from "../core/state.js";
import { testConnection } from "../core/api.js";
import { navigateTo } from "../core/router.js";

/** Initialise les evenements du formulaire de login. */
export function initLogin() {
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
      console.log("[login] attempt");
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
